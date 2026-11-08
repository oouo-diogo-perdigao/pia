"""Automatic reconciliation of the account profile using the server's revision check."""

from hashlib import sha256
import hmac
import json
import re
import threading
from urllib.parse import urlsplit

import requests

from src.config_transfer import import_config
from src.plugin_logs import write
from src.profile_migration import FIXED_PATHS
from src.settings_store import get_store, synchronized, values

from .profile import SECTION, history_rows, pack, shared_backup, snapshot, update_history, validate_history

ROOT = '/pia-profile'
LOCAL_SETTINGS = {'HOST', 'PORT', 'PUBLIC_BASE_URL'}
GROUPS = ('settings', 'documents', 'preferences', 'secrets', 'files')
HISTORY = ('folders', 'chats', 'messages', 'branches')
_workers = {}
_lock = threading.Lock()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def records(profile):
    if not profile:
        return {name: {} for name in GROUPS + HISTORY}
    backup = shared_backup(profile['backup'])
    root = backup.get('user_dir', '').replace('\\', '/').rstrip('/')
    settings = {}
    for section, name, raw, kind, reference in backup['settings']:
        if name in FIXED_PATHS or (section == 'general' and name in LOCAL_SETTINGS):
            continue
        if kind in ('path', 'file') and not reference:
            path = json.loads(raw).replace('\\', '/')
            if not root or not path.startswith(root + '/files/'):
                continue
            raw = encode(ROOT + path[len(root):])
        settings[encode([section, name])] = [section, name, raw, kind, reference]

    documents = {}
    for name, raw in backup['documents']:
        value = json.loads(raw)
        if name == 'Apps/screenshots' and isinstance(value, dict):
            value.pop('output_folder', None)
            if not value:
                continue
        documents[name] = [name, encode(value)]
    history = validate_history(profile['chats'])
    return {
        'settings': settings, 'documents': documents,
        'preferences': {key: [key, encode(json.loads(raw))] for key, raw in backup.get('preferences', []) if key.startswith('ui:')},
        'secrets': backup['secrets'], 'files': backup.get('files', {}),
        **{name: {str(row[0]): row for row in history.get(name, [])} for name in HISTORY},
    }


def backup_for(items):
    return pack({
        'version': 1, 'user_dir': ROOT, 'settings': list(items['settings'].values()),
        'documents': list(items['documents'].values()), 'preferences': list(items['preferences'].values()),
        'secrets': items['secrets'], 'files': items['files'],
    })


def profile_for(items):
    return {'version': 1, 'backup': backup_for(items),
            'chats': {name: list(items[name].values()) for name in HISTORY}}


def signatures(items, token):
    def digest(value):
        return hmac.digest(token, encode(value).encode(), 'sha256').hex()

    return {group: {key: [digest(field) for field in value] if group == 'chats' else digest(value)
                    for key, value in rows.items()} for group, rows in items.items()}


def separate_message_ids(local, remote):
    # Older clients allocated sequential IDs in each database. Preserve both
    # messages if they have the same ID and different content or ownership.
    collisions = [row[0] for key, row in local['messages'].items()
                  if key in remote['messages'] and row[:4] != remote['messages'][key][:4]]
    if not collisions:
        return local
    mapping = {}
    for identity in sorted(collisions):
        row = local['messages'][str(identity)]
        candidate = (1 << 48) + (int.from_bytes(sha256(encode(row[:4]).encode()).digest()[:6], 'big'))
        while (candidate in mapping.values() or str(candidate) in local['messages'] or
               (str(candidate) in remote['messages'] and row[1:4] != remote['messages'][str(candidate)][1:4])):
            candidate += 1
        mapping[identity] = candidate

    def remap(identity):
        return mapping.get(identity, identity)

    messages = {str(remap(i)): [remap(i), chat, role, body, remap(parent)]
                for i, chat, role, body, parent in local['messages'].values()}
    chats = {key: row[:6] + [remap(row[6]), remap(row[7])] for key, row in local['chats'].items()}
    branches = {}
    for key, raw in local['branches'].values():
        prefix, parent = key.rsplit(':', 1)
        key = prefix + ':' + (str(remap(int(parent))) if parent.isdecimal() else parent)
        branches[key] = [key, encode(remap(json.loads(raw)))]
    return {**local, 'messages': messages, 'chats': chats, 'branches': branches}


def merge(local, remote, baseline, token):
    local = separate_message_ids(local, remote)
    local_hashes, remote_hashes = signatures(local, token), signatures(remote, token)
    merged = {}
    for group in GROUPS + HISTORY:
        rows = merged[group] = {}
        for key in sorted(local[group].keys() | remote[group].keys()):
            old = baseline.get(group, {}).get(key)
            left, right = local_hashes[group].get(key), remote_hashes[group].get(key)
            # On first connection keep the server value for an existing item.
            # Later, use the local change when both sides changed the same item.
            source = local if left != old and (old is not None or right is None) else remote
            if group == 'chats' and left != old and right != old and left and right and old:
                # Concurrent replies remain as separate message branches.
                local_row, remote_row = local[group][key], remote[group][key]
                rows[key] = [local_row[i] if left[i] != old[i] else remote_row[i] for i in range(7)]
                rows[key].append(max(local_row[7] or 0, remote_row[7] or 0))
            elif key in source[group]:
                rows[key] = source[group][key]
    # Don't retain children of a deleted conversation, or dangling references.
    chats, messages = merged['chats'], merged['messages']
    messages = merged['messages'] = {key: row for key, row in messages.items() if row[1] in chats}
    for key, row in messages.items():
        if row[4] is not None and messages.get(str(row[4]), [None, None])[1] != row[1]:
            messages[key] = row[:4] + [None]
    for key, row in chats.items():
        folder = row[3] if row[3] in merged['folders'] else None
        leaf = row[6] if messages.get(str(row[6]), [None, None])[1] == key else None
        chats[key] = row[:3] + [folder] + row[4:6] + [leaf, row[7]]
    merged['branches'] = {key: row for key, row in merged['branches'].items()
                          if messages.get(str(json.loads(row[1])), [None, None])[1] == key.split(':')[1]}
    for row in merged['settings'].values():
        reference = row[4]
        if reference and reference not in merged['secrets']:
            merged['secrets'][reference] = (local['secrets'] | remote['secrets'])[reference]
    return merged


class ConcurrentChange(Exception):
    pass


@synchronized
def apply(store, before, merged, metadata_key, metadata, active):
    if not active():
        raise ConcurrentChange
    current = records(snapshot(store))
    if current != before:
        raise ConcurrentChange
    changed = {group: {key: value for key, value in merged[group].items() if current[group].get(key) != value}
               for group in GROUPS}
    removed = {group: [value for key, value in current[group].items() if key not in merged[group]]
               for group in ('settings', 'documents', 'preferences')}
    for group in ('secrets', 'files'):
        removed[group] = list(current[group].keys() - merged[group].keys())
    for row in changed['settings'].values():
        if row[4]:
            changed['secrets'][row[4]] = merged['secrets'][row[4]]
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        history = history_rows(db)
        if any({str(row[0]): list(row) for row in history[group]} != before[group] for group in HISTORY):
            raise ConcurrentChange
        update_history(db, before, merged)
        db.execute('INSERT OR REPLACE INTO values_store VALUES(?,?)', (metadata_key, encode(metadata)))
        if any(changed.values()) or any(removed.values()):
            import_config(backup_for(changed), '', remove=removed, preserve_local=True, connection=db)
    return any(row[0] == 'general' for row in [*changed['settings'].values(), *removed['settings']]) or any(
        row[0].startswith('main/') for row in [*changed['documents'].values(), *removed['documents']]
    )


def sync(store, post, token, key, cached=None, ready=lambda: True, active=lambda: True):
    server = post('read', {'metadata': True})
    local = records(snapshot(store))
    baseline = store.get(key, {})
    current = signatures(local, token)
    revision = server['revision']
    if baseline.get('revision') == revision and baseline.get('items') == current:
        return cached, revision, False
    if not cached or cached[0] != revision:
        server = post('read', {})
        revision = server['revision']
        cached = revision, records(server.get('snapshot'))
    remote = cached[1]
    merged = merge(local, remote, baseline.get('items', {}), token)
    if not active() or (merged != local and not ready()):
        raise ConcurrentChange
    if merged != remote:
        revision = post('write', {'revision': revision, 'snapshot': profile_for(merged)})['revision']
        cached = revision, merged
    if not active():
        raise ConcurrentChange
    restart = apply(store, local, merged, key, {'revision': revision, 'items': signatures(merged, token)}, active)
    return cached, revision, restart


def identity():
    config = values(SECTION)
    token = config.get('PIA_SERVER_DEVICE_TOKEN', '')
    url = urlsplit(config['PIA_SERVER_URL'])
    if (url.scheme == 'https' and url.hostname and not (url.username or url.password or url.query or url.fragment)
            and url.path in ('', '/') and re.fullmatch(r'[A-Za-z0-9_-]{43}', token)):
        return f'https://{url.netloc}', token
    return None


def status(store):
    with _lock:
        worker = _workers.get(store.path)
        return dict(worker['status']) if worker else {'state': 'disconnected'}


def stop(store):
    with _lock:
        worker = _workers.pop(store.path, None)
        if worker:
            worker['wake'].set()


def start(store, ready, reload_runtime):
    account = identity()
    if not account:
        return
    with _lock:
        worker = _workers.get(store.path)
        if worker and worker['account'] == account and (
            worker['thread'].is_alive() or worker['status']['state'] == 'different-account'
        ):
            return
        worker = {'account': account, 'status': {'state': 'pending'}, 'wake': threading.Event()}
        thread = threading.Thread(target=run, args=(store, ready, reload_runtime, worker), daemon=True, name='pia-server-profile')
        worker['thread'] = thread
        _workers[store.path] = worker
        thread.start()


def wake(store):
    with _lock:
        worker = _workers.get(store.path)
        if worker:
            worker['wake'].set()


def run(store, ready, reload_runtime, worker):
    base, token = worker['account']
    key = 'profile-sync:' + sha256((base + '\n' + token).encode()).hexdigest()
    cached = None
    failed = False
    verified = False

    def active():
        with _lock:
            current = _workers.get(store.path) is worker
        return current and identity() == worker['account']

    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + token

        def post(action, data):
            if not active():
                raise ConcurrentChange
            response = session.post(base + '/device/profile/' + action, json=data,
                                    timeout=(5, 45), allow_redirects=False)
            if response.status_code == 409:
                raise ConcurrentChange
            if response.status_code != 200:
                raise RuntimeError(f'HTTP {response.status_code}')
            return response.json()

        while active():
            worker['wake'].clear()
            try:
                if not verified:
                    response = session.get(base + '/device/account', timeout=(5, 15), allow_redirects=False)
                    if response.status_code != 200:
                        raise RuntimeError('Não foi possível validar a conta.')
                    email = response.json()['email'].strip().casefold()
                    if not email or not active():
                        raise ConcurrentChange
                    owner = sha256((base + '\n' + email).encode()).hexdigest()
                    with store.connect() as db:
                        db.execute("INSERT OR IGNORE INTO values_store VALUES('profile-sync:owner',?)", (encode(owner),))
                        bound = db.execute("SELECT value FROM values_store WHERE key='profile-sync:owner'").fetchone()[0]
                    if bound != encode(owner):
                        worker['status'] = {'state': 'different-account'}
                        return
                    verified = True
                cached, revision, restart = sync(store, post, token.encode(), key, cached, ready, active)
                worker['status'] = {'state': 'synced', 'revision': revision}
                failed = False
                if restart and active():
                    reload_runtime()
            except ConcurrentChange:
                worker['status'] = {'state': 'pending'}
            except Exception as error:
                worker['status'] = {'state': 'retrying'}
                if not failed:
                    write(SECTION, 'sincronização', 'Falha ao sincronizar o perfil: ' + type(error).__name__)
                failed = True
            worker['wake'].wait(15 if failed else 5)

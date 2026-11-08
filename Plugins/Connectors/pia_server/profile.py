"""Versioned profile transfer. Device credentials and notification preferences stay local."""

import base64
import json
import re
from urllib.parse import urlsplit

import requests

from src.config_transfer import PLAIN_MAGIC, decode, export_config, import_config
from src.settings_store import values

from .service import SECTION
from .remote import SECTIONS, managed_secret

TABLES = {
    'folders': ('id', 'name', 'created'),
    'chats': ('id', 'title', 'created', 'folder', 'pinned', 'archived', 'leaf', 'read_message'),
    'messages': ('id', 'chat', 'role', 'text', 'parent'),
}


def snapshot(store):
    backup = export_config('')
    payload = decode(backup['data'], '')
    payload['settings'] = [row for row in payload['settings'] if row[0] not in SECTIONS and row[0] != SECTION]
    payload['documents'] = [row for row in payload['documents'] if row[0] not in SECTIONS]
    payload['secrets'] = {key: secret for key, secret in payload['secrets'].items()
                          if not managed_secret(key) and not key.startswith('setting:' + SECTION + ':')}
    payload['preferences'] = [row for row in payload.get('preferences', []) if row[0] != 'notifications:settings']
    data = base64.b64encode(PLAIN_MAGIC + json.dumps(payload, ensure_ascii=False).encode()).decode()
    with store.connect() as db:
        db.execute('BEGIN')
        history = {name: db.execute(f"SELECT {','.join(columns)} FROM {name} ORDER BY id").fetchall()
                   for name, columns in TABLES.items()}
        history['branches'] = db.execute("SELECT key,value FROM values_store WHERE key LIKE 'branch:%' ORDER BY key").fetchall()
    return {'version': 1, 'backup': data, 'chats': history}


def restore(store, remote):
    history = remote['chats']
    for name, columns in TABLES.items():
        rows = history.get(name)
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(columns) or
            any(value is not None and type(value) not in (str, int, float) for value in row) for row in rows):
            raise ValueError('Histórico do servidor inválido.')
        if len({row[0] for row in rows}) != len(rows):
            raise ValueError('Histórico do servidor contém registros duplicados.')
    branches = history.get('branches', [])
    if not isinstance(branches, list) or any(not isinstance(row, list) or len(row) != 2 or
        not all(isinstance(value, str) for value in row) or not row[0].startswith('branch:') for row in branches):
        raise ValueError('Ramificações de conversa inválidas.')
    payload = decode(remote['backup'], '')
    if (any(row[0] in SECTIONS or row[0] == SECTION for row in payload['settings']) or
        any(row[0] in SECTIONS for row in payload['documents']) or
        any(managed_secret(key) or key.startswith('setting:' + SECTION + ':') for key in payload['secrets']) or
        any(row[0] == 'notifications:settings' for row in payload.get('preferences', []))):
        raise ValueError('O perfil remoto contém configurações locais do computador.')
    result = import_config(remote['backup'], '')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for table in reversed(TABLES):
            db.execute(f'DELETE FROM {table}')
        for table, columns in TABLES.items():
            db.executemany(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", history[table])
        db.execute("DELETE FROM values_store WHERE key LIKE 'branch:%' OR key LIKE 'draft:%'")
        db.executemany('INSERT INTO values_store(key,value) VALUES(?,?)', branches)
    return result


def transfer(action, store, revision=None):
    config = values(SECTION)
    url = urlsplit(config['PIA_SERVER_URL'])
    token = config.get('PIA_SERVER_DEVICE_TOKEN', '')
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or
        url.query or url.fragment or url.path not in ('', '/') or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token)):
        raise ValueError('Pareie este computador com a PIA Server antes de sincronizar.')

    def post(path, data):
        try:
            result = requests.post(f'https://{url.netloc}/device/profile/{path}', json=data,
                                   headers={'Authorization': 'Bearer ' + token},
                                   allow_redirects=False, timeout=45)
        except requests.RequestException:
            raise ValueError('Não foi possível acessar a PIA Server.') from None
        if result.status_code == 409:
            raise ValueError('O perfil do servidor mudou. Atualize a versão exibida e tente novamente.')
        if result.status_code != 200:
            raise ValueError('A PIA Server recusou a sincronização.')
        return result.json()

    if action == 'status':
        return post('read', {'metadata': True})
    if not isinstance(revision, str) or not re.fullmatch(r'\d{1,18}', revision):
        raise ValueError('Confira a revisão do servidor antes de sincronizar.')
    if action == 'push':
        return post('write', {'revision': revision, 'snapshot': snapshot(store)})
    if action == 'pull':
        result = post('read', {})
        if result['revision'] != revision or not result.get('snapshot'):
            raise ValueError('A revisão do servidor mudou ou ainda não existe um perfil.')
        return {**restore(store, result['snapshot']), 'revision': revision}
    raise ValueError('Ação de perfil inválida.')

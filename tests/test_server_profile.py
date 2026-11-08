import json

from Plugins.Connectors.pia_server.profile import SECTION, snapshot
from src.config_transfer import decode
from src.notifications import NotificationCenter
from src.workspace_store import WorkspaceStore


def test_profile_transfers_chat_and_excludes_device_settings(isolated_profile):
    store = WorkspaceStore(isolated_profile.path)
    isolated_profile.save(SECTION, {'PIA_SERVER_DEVICE_TOKEN': 'test-device-token'})
    isolated_profile.save('Connectors/taverns', {'TAVERNS_BOT_TOKEN': 'tavbot_fixture'})
    isolated_profile.set_document('Connectors/google', {'accounts': [{'id': 'fixture'}]})
    isolated_profile.save('general', {'OPENAI_COMPAT_API_KEY': 'test-shared-secret'})
    store.set('notifications:settings', {'muted': ['Bot/secretaria'], 'read_aloud': False})
    chat = store.new_chat('Sessão')
    store.append(chat, 'user', 'Oi')
    store.append(chat, 'assistant', 'Olá')

    remote = json.loads(json.dumps(snapshot(store)))
    backup = decode(remote['backup'], '')
    assert all(not key.startswith('setting:' + SECTION + ':') for key in backup['secrets'])
    assert not any('taverns' in key for key in backup['secrets'])
    assert not any(row[0] == 'Connectors/google' for row in backup['documents'])
    assert backup['secrets']['setting:general:OPENAI_COMPAT_API_KEY'] == 'test-shared-secret'
    assert all(key != 'notifications:settings' for key, _ in backup['preferences'])

    assert remote['chats']['chats'][0][:2] == [chat, 'Sessão']
    assert remote['chats']['messages'][-1][3] == 'Olá'
    assert isolated_profile.values(SECTION)['PIA_SERVER_DEVICE_TOKEN'] == 'test-device-token'


def test_secretary_retry_does_not_repeat_desktop_notification(tmp_path):
    store = WorkspaceStore(tmp_path / 'workspace.sqlite3')
    displayed = []
    center = NotificationCenter(store, lambda *notice: displayed.append(notice), lambda _: None)
    for _ in range(2):
        center.publish('Bot/secretaria', 'E-mail', 'Chegou uma mensagem', external_id='server-secretary:12')
    assert len(displayed) == 1
    assert center.snapshot()['unread'] == 1


def test_storage_runtime_cache_separates_metadata_and_account_credentials(monkeypatch):
    from Plugins.Connectors.pia_server import remote

    monkeypatch.setattr(remote, '_cache', {})
    monkeypatch.setattr(remote, 'values', lambda _: {
        'PIA_SERVER_URL': 'https://pia.example', 'PIA_SERVER_DEVICE_TOKEN': 'fixture',
    })
    calls = []

    def request(path, provider, identity):
        calls.append((path, provider, identity))
        return {'secret': identity} if identity else {'config': {}}

    monkeypatch.setattr(remote, 'request', request)
    assert remote.runtime('object_storage') == {'config': {}}
    assert remote.runtime('object_storage', 'r2') == {'secret': 'r2'}
    assert remote.runtime('object_storage', 's3') == {'secret': 's3'}
    assert remote.runtime('object_storage', 'r2') == {'secret': 'r2'}
    assert len(calls) == 3


def test_automatic_profile_reconciles_changes_from_two_devices(isolated_profile, monkeypatch, tmp_path):
    from Plugins.Connectors.pia_server.profile_sync import sync
    from src import settings_store

    other = settings_store.SettingsStore(tmp_path / 'other' / 'workspace.sqlite3', type(isolated_profile.vault)())
    first, second = WorkspaceStore(isolated_profile.path), WorkspaceStore(other.path)
    revision, remote = '0', None
    writes = []

    def post(action, data):
        nonlocal revision, remote
        if action == 'read':
            result = {'revision': revision}
            if not data.get('metadata') and remote is not None:
                result['snapshot'] = remote
            return result
        assert data['revision'] == revision
        remote = json.loads(json.dumps(data['snapshot']))
        revision = str(int(revision) + 1)
        writes.append(revision)
        return {'revision': revision}

    def step(settings, workspace):
        monkeypatch.setattr(settings_store, '_store', settings)
        return sync(workspace, post, b'device-key', 'profile-test')[1]

    chat = first.new_chat('Primeira')
    first.append(chat, 'user', 'Pergunta')
    first.set('draft:' + chat, 'rascunho local')
    isolated_profile.set_document('Apps/screenshots', {'output_folder': 'C:/capturas', 'sound': True})
    other.set_document('Apps/screenshots', {'output_folder': '/capturas'})
    other_chat = second.new_chat('Segunda')
    second.append(other_chat, 'user', 'Outra pergunta')
    assert step(isolated_profile, first) == '1'
    assert step(other, second) == '2'
    assert other.document('Apps/screenshots') == {'output_folder': '/capturas', 'sound': True}
    assert step(isolated_profile, first) == '2'
    assert first.get('draft:' + chat) == 'rascunho local'
    assert dict(first.chats()) == dict(second.chats())

    first.update_chat(chat, title='Novo título')
    first.append(chat, 'assistant', 'Resposta A')
    second.update_chat(chat, pinned=True)
    second.append(chat, 'assistant', 'Resposta B')
    isolated_profile.save('general', {'OPENAI_COMPAT_API_KEY': 'shared-value'})
    other.set_document('main/keywords.yaml', 'nome: PIA')
    step(isolated_profile, first)
    step(other, second)
    step(isolated_profile, first)
    with first.connect() as db:
        assert {row[0] for row in db.execute('SELECT text FROM messages WHERE chat=?', (chat,))} == {
            'Pergunta', 'Resposta A', 'Resposta B',
        }
    assert next(item for item in first.chat_records() if item['id'] == chat)['pinned']
    assert dict(first.chats())[chat] == 'Novo título'
    assert isolated_profile.document('main/keywords.yaml') == 'nome: PIA'
    assert other.vault.get('setting:general:OPENAI_COMPAT_API_KEY') == 'shared-value'

    first.delete_chat(other_chat)
    step(isolated_profile, first)
    step(other, second)
    assert other_chat not in dict(second.chats())
    with other.connection() as db:
        db.execute("DELETE FROM documents WHERE name='main/keywords.yaml'")
    step(other, second)
    step(isolated_profile, first)
    assert isolated_profile.document('main/keywords.yaml') is None
    total = len(writes)
    step(isolated_profile, first)
    step(other, second)
    assert len(writes) == total


def test_automatic_profile_preserves_conflicting_legacy_message_ids(isolated_profile):
    from Plugins.Connectors.pia_server.profile_sync import merge, records

    workspace = WorkspaceStore(isolated_profile.path)
    chat = workspace.new_chat('Conversa')
    with workspace.connect() as db:
        db.execute('INSERT INTO messages VALUES(1,?,?,?,NULL)', (chat, 'user', 'Texto local'))
        db.execute('UPDATE chats SET leaf=1,read_message=1 WHERE id=?', (chat,))
    local = records(snapshot(workspace))
    remote = json.loads(json.dumps(local))
    remote['messages']['1'][3] = 'Texto remoto'

    result = merge(local, remote, {}, b'device-key')
    assert {row[3] for row in result['messages'].values()} == {'Texto local', 'Texto remoto'}
    assert result['chats'][chat][6] in [row[0] for row in result['messages'].values()]


def test_automatic_profile_retries_without_losing_pending_changes(isolated_profile):
    import pytest
    from Plugins.Connectors.pia_server.profile_sync import ConcurrentChange, sync

    store = WorkspaceStore(isolated_profile.path)
    chat = store.new_chat('Offline')
    revision, remote = '0', None

    def post(action, data):
        nonlocal revision, remote
        if action == 'read':
            return {'revision': revision, 'snapshot': remote}
        if remote is None:
            remote = json.loads(json.dumps(data['snapshot']))
            remote['chats']['chats'].clear()
            revision = '1'
            raise ConcurrentChange
        assert data['revision'] == '1'
        remote = data['snapshot']
        revision = '2'
        return {'revision': revision}

    with pytest.raises(ConcurrentChange):
        sync(store, post, b'device-key', 'profile-test')
    assert store.get('profile-test') is None
    assert dict(store.chats()) == {chat: 'Offline'}
    assert sync(store, post, b'device-key', 'profile-test')[1] == '2'
    assert remote['chats']['chats'][0][:2] == [chat, 'Offline']

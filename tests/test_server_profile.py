import json

from Plugins.Connectors.pia_server.profile import SECTION, restore, snapshot
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

    target = WorkspaceStore(isolated_profile.path.with_name('other.sqlite3'))
    target.new_chat('Local')
    restore(target, remote)
    assert target.chats() == [(chat, 'Sessão')]
    assert target.messages(chat)[-1]['content'] == 'Olá'
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

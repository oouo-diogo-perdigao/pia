"""Offline persistence, migration, account isolation and secretary scheduling."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import threading
import types
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

from src.config_paths import migrate_config, initialize_config
from src.resource_plugins import ResourcePlugins, save_json
from src.workspace_store import WorkspaceStore
from Plugins.Bot.secretaria import Secretary

ROOT = Path(__file__).resolve().parents[1]


class Vault:
    def __init__(self): self.values = {}
    def get(self, name): return self.values.get(name)
    def set(self, name, value): self.values[name] = value
    def delete(self, name): self.values.pop(name, None)


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


class PersistenceTests(unittest.TestCase):
    def test_migration_preserves_conflicts_and_examples(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.env').write_text('SECRET=old')
            (root / 'config').mkdir()
            (root / 'config/.env').write_text('SECRET=new')
            (root / 'config/keywords.example.txt').write_text('pia')
            initialize_config(root)
            self.assertFalse((root / '.env').exists())
            self.assertEqual((root / 'config/.env').read_text(), 'SECRET=new')
            self.assertEqual(next((root / 'config/legacy').iterdir()).read_text(), 'SECRET=old')
            self.assertEqual((root / 'config/keywords.txt').read_text(), 'pia')
            migrate_config(root)
            self.assertEqual(len(list((root / 'config/legacy').iterdir())), 1)

    def test_history_drafts_and_claims_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'history.sqlite'
            store = WorkspaceStore(path)
            chat = store.new_chat()
            store.append(chat, 'user', 'Mensagem de teste')
            store.set('draft:' + chat, 'Ainda estou escrevendo')
            self.assertTrue(store.claim('event:1'))
            reopened = WorkspaceStore(path)
            self.assertFalse(reopened.claim('event:1'))
            self.assertEqual(reopened.messages(chat)[0]['content'], 'Mensagem de teste')
            self.assertEqual(reopened.get('draft:' + chat), 'Ainda estou escrevendo')
            self.assertEqual(reopened.chats()[0][1], 'Mensagem de teste')


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        shutil.copytree(ROOT / 'Plugins/Connectors', root / 'connectors', ignore=shutil.ignore_patterns('config.json'))
        self.vault, self.session = Vault(), Mock()
        self.plugins = ResourcePlugins(root / 'connectors', vault=self.vault, session=self.session)
        self.plugins.configure('google', 'client-id', 'client-secret')
        data = self.plugins.config('google')
        data['accounts'] = [{'id': 'personal', 'label': 'Pessoal'}, {'id': 'work', 'label': 'Trabalho'}]
        save_json(self.plugins.root / 'google/config.json', data)
        for account in ('personal', 'work'):
            self.vault.set('token:google:' + account, {'access_token': account + '-token', 'expires_at': 99999999999})
        self.session.get.return_value = response({'messages': []})

    def test_explicit_accounts_and_token_isolation(self):
        with self.assertRaises(ValueError):
            self.plugins.call('google', 'mail.list')
        for account in ('personal', 'work'):
            self.plugins.call('google', 'mail.list', account=account, q='is:important')
            self.assertEqual(self.session.get.call_args.kwargs['headers']['Authorization'], 'Bearer ' + account + '-token')
        self.assertEqual(len(self.plugins.call('google', 'accounts.list')), 2)
        with self.assertRaises(ValueError):
            self.plugins.call('google', 'mail.send', account='work')
        with self.assertRaises(ValueError):
            self.plugins.call('google', 'files.list', account='missing')
        with self.assertRaises(ValueError):
            self.plugins.call('google', 'files.list', account='work', arbitrary_url='https://evil.test')

    def test_refresh_and_disconnect(self):
        self.vault.set('token:google:work', {'access_token': 'expired', 'expires_at': 0, 'refresh_token': 'refresh'})
        self.session.post.return_value = response({'access_token': 'fresh', 'expires_in': 3600})
        self.plugins.call('google', 'mail.list', account='work')
        self.assertEqual(self.session.get.call_args.kwargs['headers']['Authorization'], 'Bearer fresh')
        self.assertEqual(self.vault.get('token:google:work')['refresh_token'], 'refresh')
        self.assertEqual(self.session.post.call_args.kwargs['data']['grant_type'], 'refresh_token')
        self.plugins.disconnect('google', 'work')
        self.assertIsNone(self.vault.get('token:google:work'))
        self.assertEqual(len(self.plugins.accounts('google')), 1)
        stored = (self.plugins.root / 'google/config.json').read_text()
        self.assertNotIn('fresh', stored)
        self.assertNotIn('client-secret', stored)

    def test_bounded_file_read(self):
        self.session.get.side_effect = None
        download = response({})
        download.headers = {'Content-Type': 'text/plain'}
        download.iter_content.return_value = [b'hello']
        download.__enter__ = Mock(return_value=download)
        download.__exit__ = Mock(return_value=False)
        self.session.get.side_effect = [response({'mimeType': 'application/vnd.google-apps.document'}), download]
        result = self.plugins.call('google', 'files.read', account='work', file_id='file', max_bytes=10)
        self.assertEqual(base64.b64decode(result['data_base64']), b'hello')
        self.assertIn('/export', self.session.get.call_args.args[0])
        self.session.get.side_effect = [response({'mimeType': 'text/plain'}), download]
        with self.assertRaises(ValueError):
            self.plugins.call('google', 'files.read', account='work', file_id='file', max_bytes=1)

    def test_microsoft_account_and_allowlisted_endpoints(self):
        self.plugins.configure('microsoft', 'ms-client')
        data = self.plugins.config('microsoft')
        data['accounts'] = [{'id': 'office', 'label': 'Trabalho'}]
        save_json(self.plugins.root / 'microsoft/config.json', data)
        self.vault.set('token:microsoft:office', {'access_token': 'ms-token', 'expires_at': 99999999999})
        self.plugins.call('microsoft', 'calendar.list', account='office', startDateTime='2026-10-24T00:00:00Z', endDateTime='2026-10-25T00:00:00Z')
        self.assertEqual(self.session.get.call_args.args[0], 'https://graph.microsoft.com/v1.0/me/calendarView')
        self.assertEqual(self.session.get.call_args.kwargs['headers']['Authorization'], 'Bearer ms-token')
        self.assertIsNone(self.vault.get('client:microsoft'))
        with self.assertRaises(ValueError):
            self.plugins.call('microsoft', 'mail.send', account='office')

    def test_pkce_state_loopback_and_identity(self):
        captured = {}
        session = self.session
        session.post.return_value = response({'access_token': 'access', 'refresh_token': 'refresh'})
        session.get.return_value = response({'id': 'google-123', 'email': 'me@example.com'})
        class Server:
            def __init__(self, address, handler):
                self.handler, self.server_port, self.calls = handler, 8765, 0
                self.address = address
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def handle_request(self):
                self.calls += 1
                obj = self.handler.__new__(self.handler)
                state = captured['state'][0] if self.calls > 1 else 'bad-state'
                obj.path = '/callback?code=code&state=' + state
                obj.send_response = Mock()
                obj.send_header = Mock()
                obj.end_headers = Mock()
                obj.wfile = io.BytesIO()
                obj.do_GET()
                if self.calls == 1:
                    captured['invalid_state_rejected'] = obj.send_response.call_args.args[0] == 400
        def open_browser(url):
            captured.update(parse_qs(urlsplit(url).query))
            return True
        with patch('src.resource_plugins.HTTPServer', Server), patch('src.resource_plugins.webbrowser.open', open_browser):
            account = self.plugins.connect('google', 'Pessoal')
        payload = session.post.call_args.kwargs['data']
        challenge = base64.urlsafe_b64encode(hashlib.sha256(payload['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(captured['code_challenge'][0], challenge)
        self.assertEqual(captured['code_challenge_method'], ['S256'])
        self.assertTrue(captured['invalid_state_rejected'])
        self.assertTrue(payload['redirect_uri'].startswith('http://127.0.0.1:'))
        self.assertEqual(self.vault.get('token:google:' + account)['access_token'], 'access')
        self.assertIn('me@example.com', (self.plugins.root / 'google/config.json').read_text())
        self.assertNotIn('refresh_token', (self.plugins.root / 'google/config.json').read_text())


class DesktopBackendTests(unittest.TestCase):
    def test_history_retry_and_stop_without_remote_calls(self):
        from src.desktop_backend import DesktopBackend
        with tempfile.TemporaryDirectory() as directory:
            backend = DesktopBackend.__new__(DesktopBackend)
            backend.store = WorkspaceStore(Path(directory) / 'history.sqlite')
            backend.chat_lock = threading.Lock()
            backend.voice_stop = threading.Event()
            backend.agent = Mock()
            backend.agent.complete.return_value = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='Resposta'))])
            runtime = Mock(active=False)
            loader = types.ModuleType('src.commands_loader')
            loader.process_command = lambda text, fallback: fallback(text)
            skills = types.ModuleType('src.skills_runtime')
            skills.get_runtime = lambda: runtime
            skills.is_stop_phrase = lambda text: text == 'finalizar'
            generic = types.ModuleType('src.agents.GenericAgent')
            generic.GenericAgent = Mock()
            chat = backend.store.new_chat()
            with patch.dict(sys.modules, {'src.commands_loader': loader, 'src.skills_runtime': skills,
                                          'src.agents.GenericAgent': generic}):
                self.assertEqual(backend.reply(chat, 'Olá'), 'Resposta')
                self.assertEqual(len(backend.store.messages(chat)), 2)
                backend.agent.complete.side_effect = RuntimeError('offline')
                with self.assertRaises(RuntimeError): backend.reply(chat, 'Outra pergunta')
                backend.agent.complete.side_effect = None
                backend.reply(chat, 'Outra pergunta')
                self.assertEqual(len(backend.store.messages(chat)), 4)
                self.assertEqual(backend.agent.complete.call_args.args[0][-1]['content'], 'Outra pergunta')
                backend.reply(chat, 'finalizar')
                self.assertTrue(backend.voice_stop.is_set())
                runtime.cancel.assert_called_once()

    def test_embedded_podcast_merge_runs_without_external_window(self):
        from src.desktop_backend import DesktopBackend
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first, second, output = folder / 'primeira legenda.srt', folder / 'segunda.srt', folder / 'resultado.srt'
            first.write_text('1\n00:00:00,000 --> 00:00:02,000\nPrimeira fala.\n', encoding='utf-8')
            second.write_text('1\n00:00:00,000 --> 00:00:01,000\nSegunda fala.\n', encoding='utf-8')
            backend = DesktopBackend.__new__(DesktopBackend)
            backend.podcast_lock = threading.Lock()
            backend.podcast_process = None
            process = backend.start_podcast_task('utilities.merge_srt', first, second, '-o', output)
            stdout, _ = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout)
            text = output.read_text(encoding='utf-8-sig')
            self.assertIn('00:00:02,000 --> 00:00:03,000', text)
            self.assertIn('Segunda fala.', text)
            with self.assertRaises(ValueError):
                backend.start_podcast_task('arbitrary.module')

    def test_dictation_delivers_text_without_commands_or_reply(self):
        import src
        from src.desktop_backend import DesktopBackend
        backend=DesktopBackend.__new__(DesktopBackend)
        backend.voice_lock=threading.Lock();backend.voice_stop=threading.Event();backend.voice_thread=None;backend.notify=Mock()
        state=types.ModuleType('src.state');state.LOCK=threading.Lock();state.SESSION_ACTIVE=False
        http=types.ModuleType('src.HTTPServer');http.STT_MANAGER=Mock();http.LOCAL_ACTIONS=Mock()
        stream=queue.Queue();stream.put('finalizar');http.STT_MANAGER.add_stream_queue.return_value=stream
        skills=types.ModuleType('src.skills_runtime');runtime=Mock();skills.get_runtime=lambda:runtime;skills.is_stop_phrase=lambda text:True
        delivered=[];ended=Mock()
        def receive(text):
            delivered.append(text);backend.voice_stop.set()
        with patch.dict(sys.modules,{'src.state':state,'src.HTTPServer':http,'src.skills_runtime':skills}),patch.object(src,'state',state,create=True):
            self.assertTrue(backend.toggle_voice(receive,dictation=True,on_end=ended))
            backend.voice_thread.join(timeout=2)
        self.assertEqual(delivered,['finalizar'])
        runtime.dispatch.assert_not_called();runtime.cancel.assert_not_called();ended.assert_called_once()

    def test_voice_uses_own_subscription_and_stop_phrase(self):
        import src
        from src.desktop_backend import DesktopBackend
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.voice_lock = threading.Lock()
        backend.voice_stop = threading.Event()
        backend.voice_thread = None
        backend.notify = Mock()
        state = types.ModuleType('src.state')
        state.LOCK, state.SESSION_ACTIVE = threading.Lock(), False
        http = types.ModuleType('src.HTTPServer')
        stream = queue.Queue()
        http.STT_MANAGER = Mock()
        http.STT_MANAGER.recorder.speech_started=threading.Event()
        http.STT_MANAGER.add_stream_queue.return_value = stream
        http.LOCAL_ACTIONS = Mock()
        def start(**kwargs):
            for text in ('Primeiro', 'Segundo', 'finalizar'):
                stream.put(text)
        http.LOCAL_ACTIONS.start_local_record.side_effect = start
        skills = types.ModuleType('src.skills_runtime')
        runtime = Mock()
        runtime.dispatch.return_value = False
        skills.get_runtime = lambda: runtime
        skills.is_stop_phrase = lambda text: text == 'finalizar'
        delivered = []
        with patch.dict(sys.modules, {'src.state': state, 'src.HTTPServer': http, 'src.skills_runtime': skills}), patch.object(src, 'state', state, create=True):
            self.assertTrue(backend.toggle_voice(delivered.append))
            backend.voice_thread.join(timeout=2)
        self.assertFalse(backend.voice_thread.is_alive())
        self.assertEqual(delivered, ['Primeiro', 'Segundo'])
        http.STT_MANAGER.remove_stream_queue.assert_called_once_with(stream)
        http.LOCAL_ACTIONS.start_local_record.assert_called_once_with(insert_at_cursor=False)
        self.assertFalse(state.SESSION_ACTIVE)


class SecretaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = WorkspaceStore(self.root / 'local.sqlite')
        self.resources = Mock()
        self.resources.accounts.return_value = [{'id': 'work'}, {'id': 'personal'}]
        self.resources.call.return_value = {'items': []}
        self.notify, self.open = Mock(), Mock()
        self.bot = Secretary(self.resources, self.store, self.notify, self.open, self.root / 'bot/config.json')
        self.bot.configure({'enabled': True, 'accounts': ['work'], 'important_email': False, 'open_meetings': True})
        self.now = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)

    def event(self, identity='meeting', offset=120, **extra):
        return {'id': identity, 'summary': 'Reunião', 'start': {'dateTime': (self.now + timedelta(seconds=offset)).isoformat()},
                'hangoutLink': 'https://meet.google.com/abc-defg-hij', **extra}

    def test_two_minute_meeting_and_reminder_once_across_restart(self):
        self.resources.call.return_value = {'items': [self.event()]}
        self.bot.poll(self.now)
        self.bot.poll(self.now + timedelta(seconds=20))
        self.assertEqual(self.open.call_count, 1)
        self.assertEqual(self.notify.call_count, 1)
        restarted = Secretary(self.resources, WorkspaceStore(self.store.path), self.notify, self.open, self.bot.path)
        restarted.poll(self.now + timedelta(seconds=30))
        self.assertEqual(self.open.call_count, 1)
        self.assertEqual(self.notify.call_count, 1)

    def test_configurable_meeting_advance(self):
        self.bot.configure({'meet_minutes':7,'reminders':False})
        self.resources.call.return_value = {'items':[self.event(offset=8*60)]}
        self.bot.poll(self.now)
        self.open.assert_not_called()
        self.bot.poll(self.now+timedelta(minutes=1))
        self.open.assert_called_once()

    def test_declined_cancelled_all_day_and_unsafe_links(self):
        events = [self.event('cancelled', status='cancelled'), self.event('declined', attendees=[{'self': True, 'responseStatus': 'declined'}]),
                  self.event('all-day', start={'date': '2026-10-24'}), self.event('ended', offset=-1),
                  self.event('unsafe', hangoutLink='https://evil.test/meeting')]
        self.resources.call.return_value = {'items': events}
        self.bot.poll(self.now)
        self.open.assert_not_called()
        self.assertEqual(self.notify.call_count, 1)  # the unsafe link doesn't suppress a legitimate reminder

    def test_new_important_mail_baseline_pagination_and_dedup(self):
        self.bot.configure({'reminders': False, 'open_meetings': False, 'important_email': True})
        self.bot.poll(self.now)
        self.resources.call.assert_not_called()
        def call(plugin, operation, **params):
            if operation == 'mail.list':
                self.assertIn('is:unread is:important after:', params['q'])
                return {'messages': [{'id': 'second'}]} if params.get('pageToken') else {'messages': [{'id': 'first'}], 'nextPageToken': 'next'}
            return {'payload': {'headers': [{'name': 'Subject', 'value': params['id']}]}}
        self.resources.call.side_effect = call
        self.bot.poll(self.now + timedelta(seconds=30))
        self.bot.poll(self.now + timedelta(seconds=60))
        self.assertEqual(self.notify.call_count, 2)

    def test_disabled_and_account_validation(self):
        self.bot.configure({'enabled': False})
        self.bot.poll(self.now)
        self.resources.call.assert_not_called()
        with self.assertRaises(ValueError):
            self.bot.configure({'accounts': ['not-connected']})
        with self.assertRaises(ValueError):
            self.bot.configure({'poll_seconds': 1})

    def test_calendar_failure_does_not_block_other_account(self):
        self.bot.configure({'accounts': ['work', 'personal']})
        def call(plugin, operation, **params):
            if params['account'] == 'work': raise RuntimeError('expired')
            return {'items': [self.event()]}
        self.resources.call.side_effect = call
        self.bot.poll(self.now)
        self.assertTrue(self.store.get('secretary:status:work')['errors'])
        self.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from Plugins.Connectors.taverns import service
from src.pia.service import WorkspaceService


def test_connector_discovers_text_channels_and_sends_test(isolated_profile, monkeypatch):
    tavern = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    channel = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
    destination = f'{tavern}/{channel}'
    sent = []
    age_restricted = threading.Event()

    class SimulatedTaverns(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            if self.headers.get('Authorization') != 'Bot tavbot_fixture':
                return self.reply(401, {})
            if self.path == '/api/v1/bots/@me/taverns':
                return self.reply(200, [{'id': tavern, 'name': 'Mesa'}])
            if self.path == f'/api/v1/taverns/{tavern}/channels':
                if age_restricted.is_set():
                    return self.reply(403, {'error': 'AGE_VERIFICATION_REQUIRED'})
                return self.reply(200, {'categories': [], 'channels': [
                    {'id': channel, 'name': 'sessões', 'type': 'TEXT'},
                    {'id': tavern, 'name': 'voz', 'type': 'VOICE'},
                ]})
            self.reply(404, {})

        def do_POST(self):
            if self.headers.get('Authorization') != 'Bot tavbot_fixture':
                return self.reply(401, {})
            if self.path != f'/api/v1/taverns/{tavern}/channels/{channel}/messages':
                return self.reply(403, {'message': 'fixture private detail'})
            sent.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.reply(201, {'id': 'fixture-message', 'status': 'SENT'})

    with ThreadingHTTPServer(('127.0.0.1', 0), SimulatedTaverns) as server:
        monkeypatch.setattr(service, 'API_URL', f'http://127.0.0.1:{server.server_port}/api/v1')
        monkeypatch.setattr(service, 'write', lambda *args: None)
        isolated_profile.save(service.IDENTITY, {'TAVERNS_BOT_TOKEN': 'tavbot_fixture'})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def dispatch(action, data):
                return WorkspaceService._dispatch(SimpleNamespace(), 'POST', '/integrations/taverns/' + action, data, {})

            assert dispatch('channels', {}) == {
                'configured': True, 'channels': [{'label': 'Mesa / #sessões', 'value': destination}],
            }
            assert dispatch('test', {'destination': destination}) == {'id': 'fixture-message'}
            assert 'Mensagem de teste' in sent[0]['content']
            with pytest.raises(ValueError, match='HTTP 403') as error:
                dispatch('test', {'destination': f'{tavern}/{tavern}'})
            assert 'fixture private detail' not in str(error.value)
            assert len(sent) == 1
            age_restricted.set()
            with pytest.raises(ValueError, match='AGE_VERIFICATION_REQUIRED'):
                dispatch('channels', {})
        finally:
            server.shutdown()
            thread.join()

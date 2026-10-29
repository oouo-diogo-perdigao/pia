"""Same-origin, loopback-only workspace routes, independent of /v1 Bearer APIs."""
import json
import mimetypes
from pathlib import Path
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlsplit

from .service import get_service

ROOT = Path(__file__).resolve().parent
_sessions = {}


def respond(handler, status, data, mime='application/json; charset=utf-8', headers=None):
    body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
    handler.send_response(status)
    handler.send_header('Content-Type', mime)
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def route(handler):
    url = urlsplit(handler.path)
    path = url.path
    if path != '/' and not path.startswith(('/pia/', '/mini/', '/api/pia/', '/apps/', '/bots/', '/connectors/')):
        return False
    port = handler.server.server_address[1]
    host = handler.headers.get('Host', '')
    allowed = {f'localhost:{port}', f'127.0.0.1:{port}', f'[::1]:{port}'}
    if handler.client_address[0] not in ('127.0.0.1', '::1') or host not in allowed:
        respond(handler, 403, {'error': 'A interface PIA é acessível somente pelo localhost.'})
        return True
    if handler.command == 'POST' and handler.headers.get('Origin') != 'http://' + host:
        respond(handler, 403, {'error': 'Origem inválida.'})
        return True
    try:
        if path == '/api/pia/session' and handler.command == 'POST':
            # Drain the small request body before using this HTTP connection again.
            length = int(handler.headers.get('Content-Length', '0'))
            if length > 1024:
                raise ValueError('Sessão inválida.')
            handler.rfile.read(length)
            token = secrets.token_urlsafe(32)
            now = time.time()
            for key in list(_sessions):
                if _sessions[key] < now:
                    _sessions.pop(key, None)
            _sessions[token] = now + 86400
            respond(handler, 200, {'ok': True}, headers={'Set-Cookie': f'pia_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400'})
            return True
        if path.startswith('/api/pia/'):
            cookie = SimpleCookie()
            cookie.load(handler.headers.get('Cookie', ''))
            token = cookie.get('pia_session')
            if not token or _sessions.get(token.value, 0) < time.time():
                respond(handler, 401, {'error': 'Sessão expirada. Recarregue a página.'})
                return True
            service = get_service()
            if path.startswith('/api/pia/chat/assets/') and handler.command=='GET':
                import re
                name=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg|webp)',name):raise ValueError('Imagem não encontrada.')
                from src.config_paths import BASE_DIR
                file=BASE_DIR/'data/chat-images'/name
                if not file.is_file():
                    respond(handler,404,{'error':'Imagem não encontrada.'})
                else:respond(handler,200,file.read_bytes(),mimetypes.guess_type(file.name)[0])
                return True
            if handler.command == 'GET' and not path.startswith('/api/pia/events/') and path.removeprefix('/api/pia') not in {
                '/state', '/chat/messages', '/settings', '/accounts', '/bots', '/bots/secretaria', '/logs', '/preferences'}:
                respond(handler, 405, {'error': 'Use POST para esta operação.'})
                return True
            if path.startswith('/api/pia/events/'):
                job = service.jobs.get(path.rsplit('/', 1)[1])
                if not job:
                    raise ValueError('Tarefa não encontrada.')
                cursor = int(handler.headers.get('Last-Event-ID') or parse_qs(url.query).get('after', ['0'])[0])
                handler.send_response(200)
                handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                handler.send_header('Cache-Control', 'no-store')
                handler.end_headers()
                while True:
                    with job.changed:
                        events = job.events[cursor:]
                        finished = job.status != 'running'
                        if not events and not finished:
                            job.changed.wait(timeout=10)
                    for event in events:
                        cursor += 1
                        handler.wfile.write(f'id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'.encode())
                    if not events:
                        handler.wfile.write(b': heartbeat\n\n')
                    handler.wfile.flush()
                    if finished:
                        break
                return True
            data = {}
            if handler.command == 'POST':
                length = int(handler.headers.get('Content-Length', '0'))
                if length < 0 or length > 40 * 1024 * 1024:
                    raise ValueError('Corpo da solicitação excede 40 MiB.')
                data = json.loads(handler.rfile.read(length) or b'{}')
                if not isinstance(data, dict):
                    raise ValueError('Esperado objeto JSON.')
            value = service.dispatch(handler.command, path.removeprefix('/api/pia'), data, parse_qs(url.query))
            respond(handler, 202 if path == '/api/pia/chat/send' else 200, value)
            return True
        if handler.command != 'GET':
            raise ValueError('Método não permitido.')
        if path.startswith('/connectors/'):
            import re
            match=re.fullmatch(r'/connectors/([a-z][a-z0-9_]*)/web/([a-zA-Z0-9_.-]+)',path)
            if not match:raise ValueError('Recurso inválido.')
            base=ROOT.parent.parent/'Plugins/Connectors'/match[1]/'web'
            relative=match[2]
        elif path.startswith('/bots/'):
            import re
            match=re.fullmatch(r'/bots/([a-z][a-z0-9_]*)/(avatar\.svg|web/[a-zA-Z0-9_.-]+)',path)
            if not match:
                respond(handler,404,{'error':'Arquivo não encontrado.'})
                return True
            base=ROOT.parent.parent/'Plugins/Bot'/match[1]
            relative=match[2]
        elif path.startswith('/mini/'):
            base = ROOT.parent / 'piamini'
            relative = path.removeprefix('/mini/')
        elif path.startswith('/apps/'):
            _, _, identity, relative = path.split('/', 3)
            base = get_service().apps.find(identity)['folder'] / 'web'
            # Only the app's web/ directory is published, never .env, Python or config.
        else:
            base = ROOT
            relative = 'index.html' if path == '/' else path.removeprefix('/pia/')
        file = (base / unquote(relative)).resolve()
        if not file.is_relative_to(base.resolve()) or not file.is_file() or file.name.startswith('.'):
            respond(handler, 404, {'error': 'Arquivo não encontrado.'})
        else:
            mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            respond(handler, 200, file.read_bytes(), mime + ('; charset=utf-8' if mime.startswith('text/') or mime == 'application/javascript' else ''))
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
    except (ValueError, KeyError, StopIteration) as exc:
        respond(handler, 400, {'error': str(exc) or 'Solicitação inválida.'})
    except Exception as exc:
        respond(handler, 500, {'error': str(exc)})
    return True

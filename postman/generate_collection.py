"""Build the manual API catalogue from source, without importing PIA or using accounts."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).with_name('PIA.postman_collection.json')


def tree(file):
    return ast.parse((ROOT / file).read_text(encoding='utf-8-sig'))


def compared(node, name):
    """Only equality/membership dispatch guards; not arbitrary strings/comments."""
    found = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare) or not isinstance(item.left, ast.Name) or item.left.id != name:
            continue
        for op, value in zip(item.ops, item.comparators):
            if isinstance(op, ast.Eq) and isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(value.value)
            if isinstance(op, ast.In) and isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                found.update(v.value for v in value.elts if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return found


def functions(file, names):
    return [n for n in ast.walk(tree(file)) if isinstance(n, ast.FunctionDef) and n.name in names]


BODIES = {
    '/v1/chat/completions': {'model': 'local', 'messages': [{'role': 'user', 'content': 'Olá!'}], 'stream': False},
    '/v1/audio/speech': {'model': 'tts-1', 'input': 'Olá, esta é a PIA.', 'voice': 'pf_dora', 'response_format': 'mp3'},
    '/v1/images/generations': {'prompt': 'Uma paisagem roxa e azul', 'n': 1, 'response_format': 'b64_json'},
    '/v1/music/generations': {'prompt': 'Piano instrumental tranquilo', 'lyrics': '', 'provider': 'local', 'duration': 30},
    '/action/camera': {'device': 0, 'width': 1280, 'height': 720},
    '/action/text-at-cursor': {'text': 'Texto de exemplo'},
    '/action/local-record': {'insert_at_cursor': False},
    '/action/play-audio': {'path': '{{audio_path}}'},
    '/action/play-audio-queue': {'path': '{{audio_path}}'},
    '/action/image': {'image': '{{image_data_url}}'},
    '/tts/speak': {'text': 'Olá!', 'voice': 'pf_dora', 'speed': 1},
    '/tts/generate': {'text': 'Olá!', 'voice': 'pf_dora', 'speed': 1},
    '/tts/storytelling': {'text': 'Uma história começa aqui.', 'speed': 1},
    '/tts/stream_text': {'text': 'Uma frase completa.', 'flush': True},
    '/protocols/ag-ui': {'threadId': '{{thread_id}}', 'runId': '{{$guid}}', 'messages': [{'role': 'user', 'content': 'Olá!'}]},
    '/chat/new': {}, '/chat/send': {'chat': '{{chat_id}}', 'text': 'Olá!'},
    '/chat/cancel': {'job': '{{job_id}}'}, '/chat/draft': {'chat': '{{chat_id}}', 'text': 'Rascunho'},
    '/chat/update': {'chat': '{{chat_id}}', 'title': 'Minha conversa'},
    '/chat/message': {'chat': '{{chat_id}}', 'id': 1, 'action': 'fork'},
    '/chat/delete': {'chat': '{{chat_id}}'}, '/chat/delete-many': {'chats': ['{{chat_id}}']},
    '/chat/read': {'chat': '{{chat_id}}', 'through': 1},
    '/folder/save': {'name': 'Minha pasta'}, '/folder/delete': {'id': '{{folder_id}}'},
    '/settings/save': {'section': 'general', 'values': {}},
    '/settings/upload': {'section': '{{section}}', 'name': '{{file_variable}}', 'filename': 'example.json', 'data': '{{file_base64}}'},
    '/preferences': {'language': 'pt-BR'}, '/apps/order': {'order': ['music', 'object_storage', 'podcast_automation', 'screenshots']},
    '/accounts/connect': {'plugin': 'google', 'client_id': '{{client_id}}', 'client_secret': '{{client_secret}}', 'label': 'Minha conta'},
    '/accounts/disconnect': {'plugin': 'google', 'account': '{{account_id}}'},
    '/notifications/settings': {'read_aloud': False, 'muted': []},
    '/notifications/read': {'source': 'Apps/music'},
    '/notifications/publish': {'source': 'Apps/music', 'title': 'Teste', 'text': 'Notificação de teste', 'links': []},
    '/media/state': {'client': '{{media_client}}', 'playing': False},
    '/logs/read': {'name': '{{log_name}}'}, '/logs/open': {'name': '{{log_name}}'}, '/logs/clear': {'name': '{{log_name}}'},
    '/native': {'action': 'inspect'},
}

APP_BODIES = {
    'music/generate': BODIES['/v1/music/generations'] | {'count': 1}, 'music/cancel': {'job': '{{job_id}}'},
    'podcast_automation/start': {'task': 'process', 'monitor': False, 'shutdown_after': False},
    'podcast_automation/save-options': {'outputs': {'mp3': True, 'txt': True, 'srt': True, 'vtt': True, 'resumo.json': True}, 'integrations': {}},
    'podcast_automation/save-config': {'value': {'nomes_reais': {}, 'campaign_details': {}, 'publication': {}, 'audio': {}, 'processing': {}}},
    'screenshots/capture': {'mode': 'selection'}, 'screenshots/image': {'id': '{{capture_id}}'},
    'screenshots/list-saved': {'offset': 0, 'limit': 24}, 'screenshots/color': {'value': '#8257e5'},
    'screenshots/delete-saved': {'names': ['{{capture_name}}']},
    'screenshots/save-config': {'value': {'format': 'png', 'quality': 92}},
    'object_storage/save-account': {'name': 'Minha conta', 'endpoint': '{{storage_endpoint}}', 'region': 'auto', 'access_key': '{{storage_access_key}}', 'secret_key': '{{storage_secret_key}}'},
    'object_storage/remove-account': {'id': '{{account_id}}'},
    'object_storage/delete': {'keys': ['{{object_key}}']},
    'object_storage/upload-begin': {'key': '{{object_key}}', 'size': 0},
    'object_storage/upload-chunk': {'id': '{{upload_id}}', 'offset': 0, 'data': '{{file_base64}}'},
}


def example_for_node(node, base):
    """Document mandatory data keys without reading any runtime configuration."""
    result = dict(base)
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name) and child.value.id == 'data' and isinstance(child.slice, ast.Constant) and isinstance(child.slice.value, str):
            key = child.slice.value
            result.setdefault(key, '{{' + key + '}}')
    return result


def build():
    folders = {}
    seen = set()

    def add(group, method, path, data=None, suffix='', description='', query=''):
        identity = (method, path, suffix)
        if identity in seen:
            return
        seen.add(identity)
        local = path.startswith('/api/pia/')
        request = {'method': method, 'header': [], 'url': '{{base_url}}' + path + query,
                   'description': description or ('API da interface: sessão local obrigatória. Consulte postman/README.md.' if local else 'Rota extraída do código atual. Consulte os contratos e limites no repositório.')}
        if local or not path.startswith(('/v1/', '/protocols/', '/action/camera')):
            request['auth'] = {'type': 'noauth'}
        if local:
            request['header'].append({'key': 'Origin', 'value': '{{base_url}}'})
        if method in ('POST', 'DELETE'):
            request['header'].append({'key': 'Content-Type', 'value': 'application/json'})
            request['body'] = {'mode': 'raw', 'raw': json.dumps(data if data is not None else BODIES.get(path, {}), ensure_ascii=False, indent=2), 'options': {'raw': {'language': 'json'}}}
        item = {'name': method + ' ' + path + (' · ' + suffix if suffix else ''), 'request': request, 'response': []}
        folders.setdefault(group, []).append(item)
        return item

    add('00 · Sessão local', 'POST', '/api/pia/session', {}, description='Execute primeiro para as APIs /api/pia. Postman armazena pia_session no cookie jar. Origin deve coincidir exatamente com base_url; use Desktop Agent para localhost. Não usa Bearer.')
    for fn in functions('src/HTTPServer.py', {'do_GET', 'do_POST', 'do_DELETE'}):
        method = fn.name.removeprefix('do_')
        for path in sorted(compared(fn, 'path')):
            if not path.startswith('/'):
                continue
            group = '01 · OpenAI' if path.startswith('/v1/') else '02 · Ações nativas' if path.startswith('/action/') else '03 · TTS' if path.startswith('/tts/') else '04 · Mini PIA e voz'
            unsupported = path in ('/v1/audio/translations', '/v1/audio/voice_consents')
            item = add(group, method, path, description='Compatibilidade: esta rota retorna 501 not_implemented.' if unsupported else '')
            if method == 'POST' and path in ('/v1/audio/transcriptions', '/v1/images/edits', '/v1/images/variations'):
                fields = [{'key': 'file' if 'transcriptions' in path else 'image', 'type': 'file', 'src': []}]
                fields += [{'key': k, 'value': v, 'type': 'text'} for k, v in ({'model': 'whisper-1', 'response_format': 'verbose_json', 'language': 'pt'} if 'transcriptions' in path else {'prompt': 'Edite esta imagem', 'response_format': 'b64_json'}).items()]
                item['request']['header'] = []
                item['request']['body'] = {'mode': 'formdata', 'formdata': fields}
                if 'transcriptions' in path:
                    item['request']['header'] = [{'key': 'X-PIA-Transcription-ID', 'value': '{{transcription_id}}'}]
                    for fmt in ('json', 'text', 'srt', 'vtt'):
                        variant = add(group, method, path, suffix=fmt)
                        variant['request']['header'] = item['request']['header'].copy()
                        variant['request']['body'] = json.loads(json.dumps(item['request']['body']))
                        next(f for f in variant['request']['body']['formdata'] if f['key'] == 'response_format')['value'] = fmt
    for method, path in [('GET', '/v1/images/files/{{image_token}}'), ('GET', '/v1/audio/transcriptions/progress/{{transcription_id}}'), ('GET', '/v1/music/files/{{music_file}}'), ('POST', '/action/camera'), ('POST', '/v1/music/generations')]:
        add('05 · Câmera e música', method, path)
    for name, body in [('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'postman', 'version': '1.0'}}), ('ping', {}), ('tools/list', {}), ('tools/call', {'name': 'pia_accounts', 'arguments': {}}), ('notifications/initialized', {})]:
        rpc = {'jsonrpc': '2.0', 'method': name, 'params': body}
        if not name.startswith('notifications/'):
            rpc['id'] = 1
        add('06 · MCP e AG-UI', 'POST', '/protocols/mcp', rpc, suffix=name)
    add('06 · MCP e AG-UI', 'POST', '/protocols/ag-ui', description='SSE RunAgentInput. Perfil PIA; resposta text/event-stream. Não há ACP nem A2A.')
    readable = {'/state', '/chat/messages', '/settings', '/accounts', '/bots', '/bots/secretaria', '/logs', '/preferences', '/notifications', '/notifications/counts'}
    for fn in functions('src/pia/service.py', {'_dispatch'}):
        for path in sorted(compared(fn, 'path')):
            methods = ['GET', 'POST'] if path in ('/preferences', '/bots/secretaria') else ['GET' if path in readable else 'POST']
            for method in methods:
                body = BODIES.get(path, {})
                if path == '/bots/secretaria':
                    body = {'enabled': False}
                item = add('07 · Workspace e serviços', method, '/api/pia' + path, body, query='?chat={{chat_id}}' if path == '/chat/messages' else '')
                if path == '/chat/new':
                    item['event'] = [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': ['if (pm.response.code === 200) pm.collectionVariables.set("chat_id", pm.response.json().id);']}}]
    integrations = {
        'agents': {'status': {}, 'ask': {'provider': 'codex', 'prompt': 'Explique suas capacidades.'}},
        'google': {'accounts': {}, 'folders': {'account': '{{account_id}}', 'folder': 'root'}},
        'object_storage': {'secrets': {'account': '{{account_id}}'}},
        'discord': {n: {} for n in ('status', 'logs', 'channels', 'diagnose', 'test', 'register-link', 'unlink')},
    }
    integrations['discord'].update(send={'text': 'Mensagem de exemplo', 'channel': '{{discord_channel_id}}'}, listener={'enabled': True})
    for plugin, actions in integrations.items():
        for action, body in actions.items():
            add('08 · Conectores', 'POST', '/api/pia/integrations/' + plugin + '/' + action, body)
    for file in sorted((ROOT / 'Plugins/Apps').glob('*/web_api.py')):
        app = file.parent.name
        for fn in functions(file.relative_to(ROOT), {'handle'}):
            actions = compared(fn, 'action')
            for n in ast.walk(fn):
                if app == 'screenshots' and isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'allowed' for t in n.targets):
                    actions.update(ast.literal_eval(n.value))
            # generate/prepare-local are accepted by a negative guard.
            if app == 'music':
                actions.update(('generate', 'prepare-local'))
            if app == 'podcast_automation':
                actions.add('start')
            for action in sorted(actions):
                body = APP_BODIES.get(app + '/' + action, {})
                for guard in ast.walk(fn):
                    if isinstance(guard, ast.If) and action in compared(guard.test, 'action'):
                        body = example_for_node(ast.Module(body=guard.body, type_ignores=[]), body)
                if app == 'object_storage' and action not in ('accounts', 'save-account', 'remove-account', 'cancel', 'upload-chunk', 'upload-finish', 'upload-cancel'):
                    body = {'account': '{{account_id}}', 'bucket': '{{bucket}}', **body}
                if app == 'screenshots':
                    if action in ('copy', 'save', 'desktop', 'drag', 'print', 'edit', 'finalize'):
                        body = {'data': '{{image_data_url}}', 'title': 'Captura', 'format': 'png'}
                    if action in ('saved-image', 'open-saved', 'copy-saved'):
                        body = {'name': '{{capture_name}}'}
                add('09 · Apps / ' + app, 'POST', '/api/pia/apps/' + app + '/' + action, body)
    add('10 · Arquivos e eventos', 'GET', '/api/pia/events/{{job_id}}', query='?after=0', description='SSE de job. Sessão local; Last-Event-ID ou after permite retomar. Requer um job existente.')
    add('10 · Arquivos e eventos', 'GET', '/api/pia/logs/file', query='?name={{log_name}}')
    for path in ('/api/pia/music/files/{{music_file}}', '/api/pia/chat/assets/{{chat_asset}}', '/', '/pia/{{pia_asset}}', '/mini/{{mini_asset}}', '/apps/{{app_id}}/{{app_asset}}', '/bots/{{bot_id}}/avatar.svg', '/bots/{{bot_id}}/web/{{bot_asset}}', '/connectors/{{connector_id}}/web/{{connector_asset}}'):
        add('10 · Arquivos e eventos', 'GET', path)
    add('10 · Arquivos e eventos', 'OPTIONS', '/', description='Preflight CORS comum do servidor; não é uma ação de aplicação.')
    variables = {'base_url': 'http://127.0.0.1:8762', 'api_key': '', 'chat_id': '', 'folder_id': '', 'job_id': '', 'transcription_id': 'postman-transcription', 'thread_id': 'postman-thread', 'account_id': '', 'music_file': '', 'image_token': '', 'log_name': 'plugins/Apps/music.log', 'media_client': 'postman', 'app_id': 'screenshots', 'app_asset': 'about.html', 'bot_id': 'secretaria', 'bot_asset': 'about.html', 'connector_id': 'agents', 'connector_asset': 'about.html', 'pia_asset': 'sdk.js', 'mini_asset': 'index.html'}
    collection = {'info': {'name': 'PIA', 'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json', 'description': 'Catálogo manual das rotas atuais da PIA, gerado do código por postman/generate_collection.py. Não execute a collection inteira: há ações nativas, exclusões, publicações e gerações. Preencha IDs e arquivos antes de enviar. Bearer api_key é opcional quando a chave da PIA está vazia. Para /api/pia execute primeiro POST /api/pia/session, com cookie jar habilitado e Origin igual à base_url. Leia postman/README.md. ACP/A2A e rotas de outros servidores não fazem parte desta API.'}, 'auth': {'type': 'bearer', 'bearer': [{'key': 'token', 'value': '{{api_key}}', 'type': 'string'}]}, 'variable': [{'key': k, 'value': v, 'type': 'string'} for k, v in variables.items()], 'item': [{'name': name, 'item': items} for name, items in folders.items()]}
    # Populate all placeholders with empty values, never with real credentials.
    import re
    keys = set(re.findall(r'\{\{([a-zA-Z_][a-zA-Z_0-9]*)\}\}', json.dumps(collection)))
    collection['variable'].extend({'key': k, 'value': '', 'type': 'string'} for k in sorted(keys - variables.keys()))
    return collection


if __name__ == '__main__':
    collection = build()
    OUT.write_text(json.dumps(collection, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{sum(len(f["item"]) for f in collection["item"])} requests -> {OUT}')

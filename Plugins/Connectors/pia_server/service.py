"""Opt-in bridge for explicitly allowed desktop actions."""

import base64
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from src.plugin_logs import write
from src.settings_store import values

SECTION = 'Connectors/pia_server'
IMAGE_LIMIT = 12 * 1024 * 1024


def capture(action):
    if action == 'camera':
        from src.camera import capture as take_photo
        return take_photo(0)
    if action == 'screenshot':
        from src.LocalActions import LocalActions
        return LocalActions.screenshot_all()
    raise ValueError('Ação local indisponível.')


def run(notifications):
    config = values(SECTION)
    token = config.get('PIA_SERVER_DEVICE_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return
    url = urlsplit(config['PIA_SERVER_URL'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        write(SECTION, 'pareamento', 'URL HTTPS inválida')
        return
    base = f'https://{url.netloc}'
    capabilities = [action for action in ('camera', 'screenshot')
                    if config.get('PIA_SERVER_ALLOW_' + action.upper()) == 'true']
    secretary = config.get('PIA_SERVER_SECRETARY') == 'true'
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + token

        def post(path, payload, timeout):
            response = session.post(base + path, json=payload, timeout=timeout, allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeError('O servidor recusou o pedido.')
            return response.json()

        failed = False
        while values(SECTION).get('PIA_SERVER_DEVICE_TOKEN') == token:
            try:
                response = post('/device/poll', {'capabilities': capabilities}, 10)
                job = response.get('job')
                if secretary:
                    delivered = []
                    for item in response.get('notices', []):
                        if not re.fullmatch(r'\d{1,18}', item['id']):
                            continue
                        links = [{'label': 'Abrir no Google', 'url': item['url']}] if item.get('url') else []
                        notifications.publish('Bot/secretaria', item['title'], item['text'], links,
                                              external_id='server-secretary:' + item['id'])
                        delivered.append(item['id'])
                    if delivered:
                        post('/device/notices/ack', {'ids': delivered}, 10)
                if job:
                    result = {'job': job['id']}
                    try:
                        if job['action'] not in capabilities:
                            raise ValueError('Ação não autorizada.')
                        image = capture(job['action'])
                        if len(image) > IMAGE_LIMIT:
                            raise ValueError('Imagem excede 12 MiB.')
                        result['png'] = base64.b64encode(image).decode('ascii')
                    except Exception:
                        result['failed'] = True
                        write(SECTION, 'captura', 'Falha no dispositivo')
                    if not post('/device/complete', result, 120).get('ok'):
                        write(SECTION, 'captura', 'Falha no envio ao servidor')
                failed = False
            except (ValueError, KeyError, RuntimeError, requests.RequestException):
                if not failed:
                    write(SECTION, 'pareamento', 'Servidor indisponível ou token recusado')
                failed = True
            time.sleep(15 if failed else 5)


def start(notifications):
    from .media import run as upload_media
    threading.Thread(target=run, args=(notifications,), daemon=True, name='pia-server-device').start()
    threading.Thread(target=upload_media, daemon=True, name='pia-server-media').start()

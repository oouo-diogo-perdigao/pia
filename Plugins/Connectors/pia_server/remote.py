"""Read the central connector registry from a paired device."""

from copy import deepcopy
from hashlib import sha256
import re
import threading
from time import monotonic
from urllib.parse import urlsplit

import requests

from src.settings_store import values

SECTION = 'Connectors/pia_server'
TOKEN_FIELD = 'PIA_SERVER_DEVICE_TOKEN'


class DeviceUnauthorized(ValueError):
    pass


PROVIDERS = frozenset(('google', 'microsoft', 'object_storage', 'discord', 'taverns'))
SECTIONS = frozenset('Connectors/' + name for name in PROVIDERS)
_lock = threading.Lock()
_cache = {}


def managed():
    return bool(values(SECTION).get(TOKEN_FIELD))


def managed_secret(name):
    return (
        name == 'client:google' or name == 'client:microsoft' or
        name.startswith(('token:google:', 'token:microsoft:', 'storage:')) or
        any(name.startswith((f'setting:{section}:', f'file:{section}:')) for section in SECTIONS)
    )


def server_base(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or
            url.query or url.fragment or url.path not in ('', '/')):
        raise ValueError('Informe a URL HTTPS da PIA Server.')
    return f'https://{url.netloc}'


def server_request(method, path, payload=None):
    config = values(SECTION)
    base = server_base(config.get('PIA_SERVER_URL', ''))
    token = config.get(TOKEN_FIELD, '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise DeviceUnauthorized('Entre na PIA Server para conectar este computador.')
    try:
        response = requests.request(
            method, f'{base}/device/{path}', json=payload,
            headers={'Authorization': 'Bearer ' + token}, allow_redirects=False, timeout=15,
        )
        if response.status_code == 401:
            raise DeviceUnauthorized('Este computador precisa entrar novamente na PIA Server.')
        if response.status_code != 200:
            result = response.json()
            raise ValueError(result.get('error') or 'A PIA Server recusou o acesso ao conector.')
        return response.json()
    except requests.RequestException:
        raise ValueError('Não foi possível consultar os conectores na PIA Server.') from None


def account_profile():
    server = values(SECTION).get('PIA_SERVER_URL', '')
    if not managed():
        return {'authenticated': False, 'server': server}
    try:
        return {**server_request('GET', 'account'), 'authenticated': True, 'server': server}
    except DeviceUnauthorized:
        return {'authenticated': False, 'server': server}
    except ValueError:
        return {'authenticated': True, 'server': server, 'offline': True}


def request(path, provider, identity=None):
    return server_request('POST', 'connectors/' + path, {'provider': provider, 'id': identity})


def runtime(provider, identity=None):
    # Cache is process-local and bounded. Provider credentials are never written here.
    config = values(SECTION)
    token = sha256(config.get(TOKEN_FIELD, '').encode()).digest()
    key = (config.get('PIA_SERVER_URL'), token, provider, identity)
    with _lock:
        now = monotonic()
        for cached_key, (expires, _) in list(_cache.items()):
            if expires <= now:
                del _cache[cached_key]
        cached = _cache.get(key)
        if cached:
            return deepcopy(cached[1])
    result = request('runtime', provider, identity)
    with _lock:
        if len(_cache) >= 100:
            _cache.clear()
        _cache[key] = (monotonic() + 5, deepcopy(result))
    return result

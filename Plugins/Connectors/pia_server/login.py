"""Browser authorization for this desktop's PIA Server session."""

import hashlib
import platform
import re
import secrets
import threading
from time import monotonic

import requests

from src.settings_store import get_store, values
from .remote import DeviceUnauthorized, SECTION, TOKEN_FIELD, server_base, server_request

_lock = threading.Lock()
_pending = {}
_id = re.compile(r'[A-Za-z0-9_-]{43}')


def _post(base, action, data):
    try:
        response = requests.post(
            base + '/device/login/' + action, json=data, timeout=12, allow_redirects=False,
        )
        result = response.json()
    except requests.RequestException:
        raise ValueError('Não foi possível acessar o login da PIA Server.') from None
    if not response.ok:
        raise ValueError(result.get('error') or 'A PIA Server recusou o login.')
    return result


def begin(url):
    base = server_base(url)
    verifier = secrets.token_urlsafe(32)
    result = _post(base, 'start', {
        'challenge': hashlib.sha256(verifier.encode()).hexdigest(),
        'name': platform.node()[:60].strip() or 'PIA Desktop',
    })
    identity, code = result.get('id', ''), result.get('code', '')
    if not isinstance(identity, str) or not _id.fullmatch(identity) or not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('Resposta inválida ao iniciar login.')
    with _lock:
        for old, (_, _, deadline) in list(_pending.items()):
            if deadline <= monotonic():
                del _pending[old]
        _pending.clear()
        _pending[identity] = (base, verifier, monotonic() + 600)
    return {'id': identity, 'code': code, 'url': base + '/auth/device/' + identity}


def poll(identity):
    with _lock:
        attempt = _pending.get(identity)
    if not attempt:
        return {'status': 'expired'}
    base, verifier, expires = attempt
    result = _post(base, 'poll', {'id': identity, 'verifier': verifier}) if expires > monotonic() else {'status': 'expired'}
    status = result.get('status')
    if status == 'authorized':
        token = result.get('token', '')
        if not isinstance(token, str) or not _id.fullmatch(token):
            raise ValueError('A PIA Server enviou uma credencial inválida.')
        with _lock:
            if identity not in _pending:
                return {'status': 'expired'}
            current = values(SECTION)
            changed = current.get(TOKEN_FIELD) != token
            get_store().save(SECTION, {'PIA_SERVER_URL': base, TOKEN_FIELD: token})
            _pending.clear()
        return {'status': status, 'changed': changed}
    if status == 'expired':
        with _lock:
            _pending.pop(identity, None)
    if status not in ('pending', 'expired'):
        raise ValueError('Resposta inválida do login da PIA Server.')
    return {'status': status}


def logout():
    try:
        server_request('POST', 'logout', {})
    except DeviceUnauthorized:
        pass
    with _lock:
        get_store().save(SECTION, {TOKEN_FIELD: ''})
        _pending.clear()
    return {'ok': True}

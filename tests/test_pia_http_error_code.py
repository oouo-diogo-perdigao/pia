"""src/pia/http.py: the generic 400 handler forwards a safe ``code``."""

import io
import json
import time
from types import SimpleNamespace

import pytest

from Plugins.Apps.music import service as music
from src.pia import http as pia_http


class _Handler:
    def __init__(self, path="/api/pia/apps/music/generate", body=b"{}"):
        self.path = path
        self.command = "POST"
        self.client_address = ("127.0.0.1", 50000)
        self.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
        self.headers = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Cookie": "pia_session=t4-test-session",
            "Content-Length": str(len(body)),
        }
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass

    def json(self):
        return json.loads(self.wfile.getvalue().decode())


def _route_raising(monkeypatch, exc):
    def dispatch(*_args, **_kwargs):
        raise exc

    monkeypatch.setitem(pia_http._sessions, "t4-test-session", time.time() + 60)
    monkeypatch.setattr(
        pia_http, "get_service", lambda: SimpleNamespace(dispatch=dispatch, jobs={})
    )
    handler = _Handler()
    assert pia_http.route(handler) is True
    return handler


def test_suno_job_refused_error_carries_code(monkeypatch):
    exc = music.SunoJobRefusedError(music.SUNO_CONNECT_MESSAGE, "suno_not_connected")
    handler = _route_raising(monkeypatch, exc)
    assert handler.status == 400
    assert handler.json() == {
        "error": "Conecte o Suno em Configurações → Música.",
        "code": "suno_not_connected",
    }


def test_plain_value_error_has_no_code(monkeypatch):
    handler = _route_raising(monkeypatch, ValueError("Escolha de 1 a 10 músicas."))
    assert handler.status == 400
    assert handler.json() == {"error": "Escolha de 1 a 10 músicas."}


class _CodedError(ValueError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


@pytest.mark.parametrize(
    "code", ["Suno_Not_Connected", "a" * 65, "", "with-dash", "x y", 42, None]
)
def test_invalid_code_is_not_forwarded(monkeypatch, code):
    handler = _route_raising(monkeypatch, _CodedError("Inválido.", code))
    assert handler.status == 400
    assert handler.json() == {"error": "Inválido."}


def test_max_length_code_is_forwarded(monkeypatch):
    handler = _route_raising(monkeypatch, _CodedError("Inválido.", "a" * 64))
    assert handler.json() == {"error": "Inválido.", "code": "a" * 64}

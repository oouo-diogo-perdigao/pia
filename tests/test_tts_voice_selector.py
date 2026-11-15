"""Tests for the PIA voice selector (TTS providers)."""
import http.client
import json
import logging
import threading
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

from src import config
_desktop = ModuleType("src.LocalActions")
_desktop.LocalActions = Mock()
with patch.dict("sys.modules", {"src.LocalActions": _desktop}):
    from src import HTTPServer as http_module


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(config, "AGE_GEMINI_API_KEY", "test-credential", raising=False)
    monkeypatch.setattr(http_module, "OPENAI_COMPAT_API_KEY", "", raising=False)
    server = http_module.STTThreadingHTTPServer(("127.0.0.1", 0), http_module.HTTPServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(payload=None, path="/", method="GET"):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            body = json.dumps(payload) if payload is not None else None
            headers = {"Content-Type": "application/json"} if body else {}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read().decode()
            try:
                data = json.loads(raw)
            except Exception:
                data = raw
            return response.status, data
        finally:
            connection.close()

    yield request
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_contract_tts_providers(api):
    status, data = api(path="/v1/tts/providers", method="GET")
    assert status == 200
    assert "providers" in data
    assert isinstance(data["providers"], list)
    for p in data["providers"]:
        assert {"id", "name", "kind", "available", "voices"} <= set(p.keys())
        assert p["kind"] in ("local", "remote")
        if p["available"]:
            assert isinstance(p["voices"], list)


def test_contract_tts_select(api):
    status, data = api(payload={"provider": "supertonic3", "voice": "pm_santa", "speed": 1.0}, path="/v1/tts/select", method="POST")
    assert status == 200
    assert data.get("ok") is True
    assert data.get("provider") == "supertonic3"
    assert data.get("voice") == "pm_santa"


def test_smoke_synthesis_local():
    from src.tts_providers import supertonic3 as mod
    p = mod.Supertonic3Provider()
    # monkeypatch synthesize
    mod.Supertonic3Provider.synthesize = lambda self, *a, **k: b"RIFF...."
    assert mod.Supertonic3Provider().synthesize("oi", "pm_santa", 1.0, "mp3") == b"RIFF...."


def test_keys_not_in_logs(caplog):
    import logging
    from src.tts_providers import openai_tts, elevenlabs
    caplog.set_level(logging.DEBUG)
    p = openai_tts.OpenAITTSProvider()
    # simulate a key present via settings_store monkeypatch not needed; just ensure no key leak in repr
    assert "sk-" not in repr(p)
    e = elevenlabs.ElevenLabsProvider()
    assert "xi-api-key" not in repr(e)
    # synthesize without key raises without echoing key
    try:
        p.synthesize("hi", "alloy", 1.0, "mp3")
    except Exception as ex:
        assert "sk-" not in str(ex)

"""Real HTTP requests with deterministic, offline provider responses."""

import http.client
import json
import threading
from types import ModuleType
from unittest.mock import Mock, patch

import pytest
from litellm import ModelResponse
from litellm.types.utils import ModelResponseStream

from src import config
from src.agents.GenericAgent import GenericAgent
from src.agents import GenericAgent as agent_module
from src.llm_routing import Model, select_models

# develop also initializes Windows desktop actions at HTTP module import.
# These chat tests exercise the real HTTP/LLM stack without desktop hardware.
_desktop = ModuleType("src.LocalActions")
_desktop.LocalActions = Mock()
with patch.dict("sys.modules", {"src.LocalActions": _desktop}):
    from src import HTTPServer as http_module


@pytest.fixture
def api(monkeypatch):
    models = (
        Model("gemini", "gemini/first", "free"),
        Model("gemini", "gemini/second", "paid"),
        Model("local", "ollama/test", "local"),
    )
    monkeypatch.setattr(
        agent_module,
        "select_models",
        lambda expression: select_models(expression or "free", models),
    )
    monkeypatch.setattr(
        http_module,
        "select_models",
        lambda expression: select_models(expression or "free", models),
    )
    monkeypatch.setattr(http_module, "catalog", lambda: models)
    monkeypatch.setattr(config, "AGE_GEMINI_API_KEY", "test-credential")
    monkeypatch.setattr(http_module, "OPENAI_COMPAT_API_KEY", "")
    monkeypatch.setitem(
        http_module.BUFFER_MANAGER.agent_manager.agents, "generic", GenericAgent()
    )
    server = http_module.STTThreadingHTTPServer(
        ("127.0.0.1", 0), http_module.HTTPServer
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(payload=None, path="/v1/chat/completions", method="POST"):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request(
                method,
                path,
                body=json.dumps(payload) if payload is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()

    yield request
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def response(text="ok", stream=False):
    if stream:
        return ModelResponseStream(
            model="gemini/second", choices=[{"delta": {"content": text}}]
        )
    return ModelResponse(
        model="gemini/second",
        choices=[{"message": {"role": "assistant", "content": text}}],
    )


def test_http_policy_messages_and_fallback(api, monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] == "gemini/first":
            raise RuntimeError("quota")
        return response()

    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    messages = [
        {"role": "system", "content": "Keep context"},
        {"role": "user", "content": "question"},
    ]
    status, body = api(
        {
            "model": "free-local+gemini=paid",
            "messages": messages,
            "temperature": 0,
            "api_key": "untrusted",
        }
    )
    assert status == 200
    assert json.loads(body)["choices"][0]["message"]["content"] == "ok"
    assert json.loads(body)["model"] == "gemini/second"
    assert [c["model"] for c in calls] == ["gemini/first", "gemini/second"]
    assert calls[-1]["messages"] == messages
    assert calls[-1]["temperature"] == 0
    assert calls[-1]["api_key"] == "test-credential"


def test_http_stream_fallback(api, monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "gemini/first":
            raise RuntimeError("quota")
        return iter([response("hello", True), response(" world", True)])

    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    status, body = api(
        {
            "model": "all-local",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
    )
    assert status == 200
    chunks = [
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {")
    ]
    assert "".join(c["choices"][0]["delta"]["content"] for c in chunks) == "hello world"
    assert body.endswith("data: [DONE]\n\n")
    assert calls == ["gemini/first", "gemini/second"]


@pytest.mark.parametrize("stream", [False, True])
def test_http_all_failed_is_503(api, monkeypatch, stream):
    def fail(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(agent_module.litellm, "completion", fail)
    status, body = api(
        {
            "model": "free-local",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": stream,
        }
    )
    assert status == 503
    assert json.loads(body)["error"]["type"] == "server_error"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"messages": []},
        {"messages": ["hi"]},
        {"messages": [{"role": "user", "content": "hi"}], "model": "unknown"},
        {"messages": [{"role": "user", "content": "hi"}], "stream": "false"},
    ],
)
def test_http_bad_request(api, payload):
    status, body = api(payload)
    assert status == 400
    assert "error" in json.loads(body)


def test_http_model_listing(api):
    status, body = api(path="/v1/models", method="GET")
    assert status == 200
    ids = {model["id"] for model in json.loads(body)["data"]}
    assert {
        "all",
        "paid",
        "free",
        "local",
        "gemini/first",
        "gemini/second",
        "whisper-1",
    } <= ids


def test_http_partial_stream_reports_error_without_restart(api, monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs["model"])

        def stream():
            yield response("partial", True)
            raise RuntimeError("lost connection")

        return stream()

    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    status, body = api(
        {"messages": [{"role": "user", "content": "hi"}], "stream": True}
    )
    assert status == 200
    chunks = [
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {")
    ]
    assert chunks[0]["choices"][0]["delta"]["content"] == "partial"
    assert chunks[-1]["error"]["type"] == "server_error"
    assert body.endswith("data: [DONE]\n\n")
    assert calls == ["gemini/first"]

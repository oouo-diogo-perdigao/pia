from src.settings_store import get_store,save_document,document
import pytest

from src import config
from src.llm_routing import GEMINI_FREE_MODELS, Model, catalog, select_models
from src.agents import GenericAgent as agent_module
from src.agents.GenericAgent import GenericAgent
from litellm import ModelResponse
from litellm.types.utils import ModelResponseStream


@pytest.fixture
def models():
    return (
        Model("gemini", "gemini/free", "free"),
        Model("gemini", "gemini/paid", "paid"),
        Model("groq", "groq/free", "free"),
        Model("groq", "groq/paid", "paid"),
        Model("openrouter", "openrouter/free", "free"),
        Model("cloudflare", "cloudflare/paid", "paid"),
        Model("local", "ollama/test", "local"),
    )


@pytest.mark.parametrize("expression,indices", [
    ("local", [6]), ("free", [0, 2, 4, 6]),
    ("paid", list(range(7))), ("all", list(range(7))),
    ("all-local", list(range(6))), ("-local", list(range(6))),
    ("+gemini=free", [0]), ("free-local+gemini=paid", [0, 1, 2, 4]),
    ("all-gemini", [2, 3, 4, 5, 6]),
    ("local+cloudflare=paid+openrouter=free", [4, 5, 6]),
    ("all-gemini+gemini=free", [0, 2, 3, 4, 5, 6]),
    ("free-local+local", [0, 2, 4, 6]),
])
def test_policy(expression, indices, models):
    assert select_models(expression, models) == tuple(models[i] for i in indices)


@pytest.mark.parametrize("expression", ["", "all+", "free--local", "free=paid", "unknown", "all local", 42])
def test_invalid_policy(expression, models):
    with pytest.raises(ValueError):
        select_models(expression, models)


def test_exact_model_with_hyphens(models):
    model = Model("gemini", "gemini/gemini-3.8-flash", "free")
    assert select_models(model.model, (model,)) == (model,)


def test_default_and_alias(monkeypatch, models):
    monkeypatch.setattr(config, "LLM_MODEL", "free-local")
    assert select_models(None, models) == select_models("my-agent", models) == select_models("free-local", models)


def test_default_gemini_order(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDERS", ("gemini", "local"))
    monkeypatch.setattr(config, "LLM_MODEL_CATALOG", "[]")
    monkeypatch.delenv("LLM_GEMINI_FREE_MODELS", raising=False)
    monkeypatch.delenv("LLM_GEMINI_PAID_MODELS", raising=False)
    assert [m.model for m in catalog() if m.provider == "gemini"] == ["gemini/" + name for name in GEMINI_FREE_MODELS]


def test_provider_configuration(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDERS", ("openrouter", "cloudflare"))
    monkeypatch.setattr(config, "LLM_MODEL_CATALOG", '[{"provider":"custom","model":"openai/test","tier":"paid","api_key_env":"TEST_KEY","api_base_env":"TEST_BASE"}]')
    get_store().save("general",{"LLM_OPENROUTER_FREE_MODELS":"vendor/free:free"})
    get_store().save("general",{"LLM_CLOUDFLARE_PAID_MODELS":"@cf/vendor/model"})
    get_store().save("general",{"TEST_KEY":"test-credential"})
    get_store().save("general",{"TEST_BASE":"https://example.invalid/v1"})
    entries = catalog()
    assert [m.provider for m in entries] == ["openrouter", "cloudflare", "custom"]
    assert entries[-1].params() == {"model": "openai/test", "api_key": "test-credential", "api_base": "https://example.invalid/v1"}
    assert select_models("paid-local", entries) == entries


@pytest.fixture
def agent(monkeypatch):
    models = (Model("gemini", "gemini/first", "free"), Model("gemini", "gemini/second", "free"), Model("local", "ollama/test", "local"))
    monkeypatch.setattr(agent_module, "select_models", lambda policy: select_models(policy or "free", models))
    monkeypatch.setattr(config, "AGE_GEMINI_API_KEY", "test-credential")
    return GenericAgent()


def reply(text="ok"):
    return ModelResponse(model="gemini/second", choices=[{"message": {"role": "assistant", "content": text}}])


def chunk(text=None, **delta):
    return ModelResponseStream(model="gemini/second", choices=[{"delta": {"content": text, **delta}}])


def test_fallback_and_per_model_cooldown(agent, monkeypatch):
    calls = []
    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] == "gemini/first":
            raise RuntimeError("quota")
        return reply()
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    assert agent.run("hi", "free-local") == "ok"
    assert [c["model"] for c in calls] == ["gemini/first", "gemini/second"]
    assert agent.run("again", "free-local") == "ok"
    assert [c["model"] for c in calls] == ["gemini/first", "gemini/second", "gemini/second"]


def test_full_messages_and_options(agent, monkeypatch):
    seen = []
    monkeypatch.setattr(agent_module.litellm, "completion", lambda **kw: seen.append(kw) or reply())
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "question"}, {"role": "assistant", "content": "answer"}, {"role": "user", "content": "followup"}]
    agent.complete(messages, "local", temperature=0, response_format={"type": "json_object"})
    assert seen[0]["messages"] == messages
    assert seen[0]["temperature"] == 0
    assert seen[0]["model"] == "ollama/test"


def test_stream_fallback_before_content(agent, monkeypatch):
    calls = []
    def completion(**kw):
        calls.append(kw["model"])
        def stream():
            yield chunk(role="assistant")
            if kw["model"] == "gemini/first":
                raise RuntimeError("quota")
            yield chunk("ok")
        return stream()
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    assert list(agent.run_stream("hi", "free-local")) == ["ok"]
    assert calls == ["gemini/first", "gemini/second"]


def test_no_restart_after_stream_output(agent, monkeypatch):
    calls = []
    def completion(**kw):
        calls.append(kw["model"])
        def stream():
            yield chunk("partial")
            raise RuntimeError("connection lost")
        return stream()
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    stream = agent.run_stream("hi")
    assert next(stream) == "partial"
    with pytest.raises(RuntimeError, match="connection lost"):
        next(stream)
    assert calls == ["gemini/first"]


def test_empty_stream_falls_back(agent, monkeypatch):
    monkeypatch.setattr(agent_module.litellm, "completion", lambda **kw: iter([]) if kw["model"] == "gemini/first" else iter([chunk("ok")]))
    assert list(agent.run_stream("hi")) == ["ok"]


def test_all_failed_and_explicit_selection(agent, monkeypatch):
    calls = []
    def completion(**kw):
        calls.append(kw["model"])
        raise RuntimeError("offline")
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    with pytest.raises(RuntimeError, match="Todos os modelos"):
        agent.run("hi", "gemini/first")
    assert calls == ["gemini/first"]


def test_missing_credentials_uses_local(agent, monkeypatch):
    monkeypatch.setattr(config, "AGE_GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(agent_module.litellm, "completion", lambda **kw: calls.append(kw["model"]) or reply())
    assert agent.run("hi") == "ok"
    assert calls == ["ollama/test"]


def test_cooldown_expires(agent, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: clock[0])
    failed_once = set()
    calls = []
    def completion(**kwargs):
        name = kwargs["model"]
        calls.append(name)
        if name == "gemini/first" and name not in failed_once:
            failed_once.add(name)
            raise RuntimeError("quota")
        return reply()
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    agent.run("hi")
    clock[0] += agent_module.LLM_REMOTE_COOLDOWN_SECONDS + 1
    agent.run("hi")
    assert calls == ["gemini/first", "gemini/second", "gemini/first"]


def test_tool_stream_does_not_fallback_after_tool_call(agent, monkeypatch):
    calls = []
    def completion(**kwargs):
        calls.append(kwargs["model"])
        def stream():
            yield chunk(tool_calls=[{"index": 0, "id": "call_1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}])
            raise RuntimeError("interrupted tool")
        return stream()
    monkeypatch.setattr(agent_module.litellm, "completion", completion)
    stream = agent.complete_stream([{"role": "user", "content": "weather"}])
    assert next(stream).choices[0].delta.tool_calls
    with pytest.raises(RuntimeError, match="interrupted tool"):
        next(stream)
    assert calls == ["gemini/first"]


def test_custom_provider_with_reserved_prefix():
    model = Model("localai", "openai/test", "local")
    assert select_models("free-local+localai", (model,)) == (model,)


def test_multiple_local_models(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDERS", ("local",))
    monkeypatch.setattr(config, "LLM_MODEL_CATALOG", "[]")
    get_store().save("general",{"LLM_LOCAL_MODELS":"ollama/first,ollama/second"})
    assert [m.model for m in select_models("local")] == ["ollama/first", "ollama/second"]

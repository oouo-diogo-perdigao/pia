import io
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.desktop_backend import DesktopBackend  # noqa: E402
from src.llm_routing import available_chat_models, select_models  # noqa: E402
from src.mcp_chat_tools import (  # noqa: E402
    rpg_sessions,
    storage_get,
    storage_list,
    take_screenshot,
)
from src.pia.service import WorkspaceService  # noqa: E402
from src.workspace_store import WorkspaceStore  # noqa: E402


class _FakeS3Client:
    def __init__(self, buckets, objects):
        self._buckets = buckets
        self._objects = objects

    def list_buckets(self):
        return {"Buckets": [{"Name": b} for b in self._buckets]}

    def get_paginator(self, name):
        objects = self._objects

        class _Paginator:
            def paginate(self, Bucket, Prefix=""):
                contents = [
                    {
                        "Key": k,
                        "Size": len(v.encode("utf-8")),
                        "LastModified": "2026-11-10T20:00:00Z",
                    }
                    for k, v in objects.get(Bucket, {}).items()
                    if k.startswith(Prefix)
                ]
                return [{"Contents": contents}]

        return _Paginator()

    def get_object(self, Bucket, Key):
        data = self._objects.get(Bucket, {})
        if Key not in data:
            raise FileNotFoundError(Key)
        return {"Body": io.BytesIO(data[Key].encode("utf-8"))}


class _FakeStorage:
    def __init__(self, buckets, objects):
        self._buckets = buckets
        self._objects = objects
        self._client = _FakeS3Client(buckets, objects)

    def accounts(self):
        return [{"id": "acc-1", "bucket": self._buckets[0]}]

    def account(self, account=None):
        return {"id": account or "acc-1", "bucket": self._buckets[0]}

    def bucket(self, acc_id, bucket=None):
        return bucket or self._buckets[0]

    def key(self, key):
        return str(key or "").lstrip("/")

    def client(self, acc_id):
        return self._client

    def list(self, acc_id, bucket=None, prefix="", limit=100):
        target_bucket = bucket or self._buckets[0]
        objs = [
            {
                "key": k,
                "size": len(v.encode("utf-8")),
                "modified": "2026-11-10T20:00:00Z",
            }
            for k, v in self._objects.get(target_bucket, {}).items()
            if k.startswith(prefix)
        ][:limit]
        return {"bucket": target_bucket, "prefixes": [], "objects": objs}


def _create_chat(store: WorkspaceStore, chat_id: str = "chat-test") -> str:
    with store.connect() as db:
        db.execute(
            "INSERT INTO chats(id,title,created) VALUES(?,?,?)",
            (chat_id, "Teste", time.time()),
        )
    return chat_id


def test_chat_models_route_and_selection(tmp_path):
    assert '"/chat/models"' in (ROOT / "src" / "pia" / "http.py").read_text(
        encoding="utf-8"
    )
    store = WorkspaceStore(tmp_path / "workspace.db")
    backend = DesktopBackend(lambda *a, **kw: None)
    backend.store = store
    service = WorkspaceService(backend=backend)
    catalog = service._dispatch("GET", "/chat/models", {}, {})
    assert isinstance(catalog["default"], str) and catalog["default"]
    ids = [m["id"] for m in catalog["models"]]
    assert "auto" in ids
    assert any(m["provider"] == "gemini" for m in catalog["models"])
    chosen = select_models("gemini:gemini-2.5-flash")
    assert chosen[0].provider == "gemini"
    assert chosen[0].model == "gemini/gemini-2.5-flash"


def test_workspace_send_persists_and_emits_model_metadata(monkeypatch, tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    chat_id = _create_chat(store, "chat-meta")
    monkeypatch.setitem(
        sys.modules,
        "src.skills_runtime",
        SimpleNamespace(
            get_runtime=lambda: SimpleNamespace(
                active=False, dispatch=lambda *a: False, cancel=lambda: None
            ),
            is_stop_phrase=lambda *a: False,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.commands_loader",
        SimpleNamespace(
            process_command=lambda text, fallback: fallback(text) and False
        ),
    )

    class _FakeAgent:
        def last_meta(self):
            return {"provider": "gemini", "model": "gemini-2.5-flash"}

        def complete_stream(self, messages, model=None):
            delta = SimpleNamespace(content="Resposta de teste")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

        def complete(self, messages, model=None):
            msg = SimpleNamespace(content="Resposta de teste", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setitem(
        sys.modules,
        "src.agents.GenericAgent",
        SimpleNamespace(GenericAgent=_FakeAgent),
    )

    backend = DesktopBackend(lambda *a, **kw: None)
    backend.store = store
    backend.agent = _FakeAgent()
    service = WorkspaceService(backend=backend)

    job_id = service.send(chat_id, "Olá mundo", model="gemini:gemini-2.5-flash")
    job = service.jobs[job_id]
    deadline = time.time() + 5.0
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.02)

    assert job.status == "done", job.events
    done_events = [e for e in job.events if e.get("type") == "done"]
    assert done_events
    assert done_events[-1]["model"] == "gemini-2.5-flash"
    assert done_events[-1]["provider"] == "gemini"

    records = store.message_records(chat_id)
    assistant = [r for r in records if r["role"] == "assistant"][-1]
    assert assistant["model"] == "gemini-2.5-flash"
    assert assistant["provider"] == "gemini"


def test_storage_blocks_sensitive_files_and_lists_objects(monkeypatch):
    fake = _FakeStorage(
        ["pia-bucket"],
        {
            "pia-bucket": {
                "campaigns/RPG 2025 Origem e Destructo/2026-11-10 - S02E14 - Origem e Destructo.txt": "Sessão 14",
                "secrets/google-service-account.json": '{"private_key": "secret"}',
            }
        },
    )
    monkeypatch.setattr("src.mcp_chat_tools._get_storage", lambda: fake)

    listed = storage_list()
    assert listed["bucket"] == "pia-bucket"
    keys = [o["key"] for o in listed["objects"]]
    assert "secrets/google-service-account.json" not in keys
    assert any("S02E14" in k for k in keys)

    with pytest.raises(PermissionError):
        storage_get("secrets/google-service-account.json")

    ok = storage_get(
        "campaigns/RPG 2025 Origem e Destructo/2026-11-10 - S02E14 - Origem e Destructo.txt"
    )
    assert "Sessão 14" in ok["content"]


def test_rpg_sessions_fuzzy_matches_origem_e_destructo(monkeypatch, tmp_path):
    resumo = json.dumps({"resumo": "O grupo enfrentou o dragão.", "episodio": "S02E14"})
    fake = _FakeStorage(
        ["pia-bucket"],
        {
            "pia-bucket": {
                "campaigns/RPG 2025 Origem e Destructo/2026-11-03 - S02E13 - Origem e Destructo.txt": "Anterior",
                "campaigns/RPG 2025 Origem e Destructo/2026-11-10 - S02E14 - Origem e Destructo.resumo.json": resumo,
                "campaigns/RPG 2025 Origem e Destructo/2026-11-10 - S02E14 - Origem e Destructo.txt": "Transcrição completa",
            }
        },
    )
    monkeypatch.setattr("src.mcp_chat_tools._get_storage", lambda: fake)
    monkeypatch.setattr(
        "src.mcp_chat_tools.user_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    result = rpg_sessions(campaign="origem e destructor", action="transcript")
    assert result["matched_campaign"] == "RPG 2025 Origem e Destructo"
    assert "S02E14" in result["latest_session"]
    assert "S02E14" in result["summary"]
    assert "Transcrição completa" in result["transcript"]


def test_screenshot_saves_to_chat_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.mcp_chat_tools.user_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    class _FakeImage:
        size = (1280, 720)

        def save(self, path, format="PNG"):
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

    monkeypatch.setattr(
        "PIL.ImageGrab.grab",
        lambda all_screens=True: _FakeImage(),
    )

    result = take_screenshot()
    assert result["image_url"].startswith("/api/pia/chat/assets/")
    assert Path(result["path"]).exists()


def test_multiturn_music_tool_is_allowed():
    # The direct Suno MCP chat call (call_suno_mcp) was removed in T8 (RN18).
    from src import chat_tools, mcp_chat_tools, tool_registry

    history = [
        {"role": "user", "content": "Crie uma letra sobre piratas do espaço"},
        {"role": "assistant", "content": "Verso 1: Navegando entre estrelas..."},
    ]
    tools = chat_tools.allowed_tools("agora crie essa musica", history=history)
    assert "pia_music" in tools
    assert "pia_music" in {t["name"] for t in tool_registry.TOOLS}
    assert not hasattr(mcp_chat_tools, "call_suno_mcp")


def test_tts_stop_endpoint_calls_manager(monkeypatch, tmp_path):
    from src.TTSManager import TTSManager

    stopped = []
    monkeypatch.setattr(TTSManager, "stop", lambda self: stopped.append(True))
    store = WorkspaceStore(tmp_path / "workspace.db")
    backend = DesktopBackend(lambda *a, **kw: None)
    backend.store = store
    service = WorkspaceService(backend=backend)

    resp = service._dispatch("POST", "/tts/stop", {}, {})
    assert resp == {"ok": True}
    assert stopped == [True]
    assert backend.voice_stop.is_set()


def test_complete_with_tools_return_meta_unpacks_in_desktop_backend(
    monkeypatch, tmp_path
):
    from src.tool_registry import complete_with_tools

    store = WorkspaceStore(tmp_path / "workspace.db")
    chat_id = _create_chat(store, "chat-tools-meta")

    class _FakeToolCall:
        id = "call-1"

        class function:
            name = "pia_screenshot"
            arguments = "{}"

    class _FakeMsg:
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

        def model_dump(self, exclude_none=True):
            return {"role": "assistant", "content": self.content or ""}

    class _FakeToolAgent:
        def __init__(self):
            self.turn = 0

        def last_meta(self):
            return {"provider": "groq", "model": "groq/openai/gpt-oss-120b"}

        def complete(self, messages, model=None, tools=None):
            self.turn += 1
            if self.turn == 1:
                msg = _FakeMsg("", tool_calls=[_FakeToolCall()])
            else:
                msg = _FakeMsg("Print capturado!", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(
        "src.tool_registry.call",
        lambda name, args: {
            "image_url": "/api/pia/chat/assets/abc.png",
            "markdown": "![Captura](/api/pia/chat/assets/abc.png)",
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "src.skills_runtime",
        SimpleNamespace(
            get_runtime=lambda: SimpleNamespace(
                active=False, dispatch=lambda *a: False, cancel=lambda: None
            ),
            is_stop_phrase=lambda *a: False,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.commands_loader",
        SimpleNamespace(
            process_command=lambda text, fallback: fallback(text) and False
        ),
    )

    agent = _FakeToolAgent()
    text, meta = complete_with_tools(
        agent,
        [{"role": "user", "content": "Tire um print"}],
        allowed={"pia_screenshot"},
        return_meta=True,
    )
    assert text == "Print capturado!"
    assert meta["tools_used"] == ["mcp:pia_screenshot"]
    assert meta["attachments"] == [
        {"type": "image", "url": "/api/pia/chat/assets/abc.png"}
    ]

    # Also verify full DesktopBackend.reply flow doesn't raise ValueError on unpack
    agent.turn = 0
    backend = DesktopBackend(lambda *a, **kw: None)
    backend.store = store
    backend.agent = agent
    out = backend.reply(chat_id, "Tire um print da tela", model="auto")
    assert out == "Print capturado!"
    rec = [r for r in store.message_records(chat_id) if r["role"] == "assistant"][-1]
    assert rec["tools_used"] == ["mcp:pia_screenshot"]
    assert rec["attachments"] == [
        {"type": "image", "url": "/api/pia/chat/assets/abc.png"}
    ]

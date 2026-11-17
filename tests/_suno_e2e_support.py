"""Helpers dos e2e T8 do Suno via mock MCP (CA05–CA07, CA10).

O mock é registrado no ``MCPConnectorManager`` (como a T3) e o áudio em
loopback é liberado só nos testes. Sem chamada real ou paga ao Suno.
"""

from __future__ import annotations

import io
import re
import json
import time
from types import SimpleNamespace
from typing import Any

from Plugins.Apps.music import service
from Plugins.Apps.music import tools as music_tools
from Plugins.Apps.music import web_api
from src import mcp_connectors
from src.pia import http as pia_http
from tests.fixtures.fake_suno_mcp import DEFAULT_TOKEN, FakeSunoMcpServer

MUSIC = "music"
JOB_WAIT = 12
TIMEOUT_SECONDS = 1
TIMEOUT_DELAY = 2
SUNO = {"prompt": "piano suave", "provider": "suno_mcp", "duration": 30}
SECRET_NEEDLES = (DEFAULT_TOKEN, "fake-suno-signature", "X-Amz-Signature")


def assert_t3_t4_surface() -> None:
    """Probes de comportamento (hasattr), não leitura de fonte."""
    assert hasattr(service, "suno_job_refusal")
    assert hasattr(service, "redact_secrets")
    assert hasattr(service, "generate_suno_batch")
    assert hasattr(service, "select_suno_clips")
    assert hasattr(service, "SunoIncompleteBatchError")
    assert hasattr(service, "SunoJobRefusedError")
    assert hasattr(service, "SunoDownloadError")
    assert hasattr(service, "SunoNoCreditsError")
    assert hasattr(service, "SunoClipFailedError")
    assert hasattr(service, "tracks_ready_text")


class Context:
    def __init__(self):
        self.jobs = {}
        self.notifications = []

    def publish_notification(self, source, title, text, **_kw):
        self.notifications.append((source, title, text))


def isolated_manager(tmp_path, monkeypatch):
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    mgr = mcp_connectors.MCPConnectorManager(
        store=WorkspaceStore(tmp_path / "ws.sqlite3"), vault=MemoryVault()
    )
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)
    return mgr


def register_mock(mgr, server: FakeSunoMcpServer) -> None:
    mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "transport": "http_streaming",
            "url": server.url,
            "bearer_token": server.token,
        },
        server_id="suno_mcp",
    )


def patch_music_runtime(monkeypatch, tmp_path, *, timeout: int = 20):
    """Pasta de saída isolada, timeouts curtos e loopback só no teste."""
    out = tmp_path / "music"
    monkeypatch.setattr(service, "OUTPUT", out)
    monkeypatch.setattr(service, "_AUDIO_TIMEOUT", (2, 2))
    monkeypatch.setattr(service, "_SUNO_SLEEP_SLICE", 0.01)
    monkeypatch.setattr(service, "_ALLOW_LOOPBACK_HTTP_AUDIO", True)
    monkeypatch.setattr(music_tools, "DEFAULT_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(
        service,
        "settings",
        lambda: {"MUSIC_SUNO_TIMEOUT": timeout, "MUSIC_PROVIDER": "suno_mcp"},
    )
    from Plugins.Connectors.pia_server import media

    monkeypatch.setattr(media, "enqueue", lambda path: None)
    return out


def wait_job(job, timeout: float = JOB_WAIT):
    with job.changed:
        assert job.changed.wait_for(lambda: job.status != "running", timeout=timeout)
    return job


def run_generate(data, context=None):
    context = context or Context()
    response = web_api.handle("generate", data, context)
    job = wait_job(context.jobs[response["job"]])
    return job, context


def events(job, kind):
    return [event for event in job.events if event["type"] == kind]


def error_event(job):
    found = events(job, "error")
    assert len(found) == 1, job.events
    return found[0]


def last_progress(job) -> dict[str, Any]:
    found = events(job, "progress")
    assert found, job.events
    return found[-1]["value"]


def assert_interrupted(job, *, completed: int, total: int, ready: str):
    progress = last_progress(job)
    assert progress["label"] == "Geração interrompida"
    assert progress["state"] == "interrupted"
    assert (progress["completed"], progress["total"]) == (completed, total)
    assert progress["ready_text"] == ready
    error = error_event(job)
    # "k de N" mora em ready_text/completed/total, não em event.error
    # (frases como "tente de novo" são válidas).
    assert re.search(r"\d+ de \d+", error["error"]) is None
    assert (error["completed"], error["total"]) == (completed, total)
    assert error["ready_text"] == ready
    return error, progress


def audio_files(out):
    if not out.exists():
        return []
    return sorted(p for p in out.iterdir() if p.suffix == ".mp3")


def assert_no_secrets(*parts: Any, extra: tuple[str, ...] = ()) -> None:
    corpus = ""
    for part in parts:
        if part is None:
            continue
        if hasattr(part, "events"):
            corpus += json.dumps(part.events, ensure_ascii=False)
            corpus += str(getattr(part, "error", "") or "")
        elif hasattr(part, "notifications"):
            corpus += json.dumps(part.notifications, ensure_ascii=False)
        elif isinstance(part, (list, dict, tuple)):
            corpus += json.dumps(part, ensure_ascii=False)
        else:
            path = getattr(part, "read_text", None)
            if callable(path):
                corpus += part.read_text(encoding="utf-8")
            else:
                corpus += str(part)
    for needle in SECRET_NEEDLES + extra:
        if needle:
            assert needle not in corpus, needle


class _Handler:
    def __init__(self, path="/api/pia/apps/music/generate", body=b"{}"):
        self.path = path
        self.command = "POST"
        self.client_address = ("127.0.0.1", 50000)
        self.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
        self.headers = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Cookie": "pia_session=t8-e2e-session",
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


def post_generate_http(monkeypatch, data: dict, context=None):
    """POST /api/pia/apps/music/generate via ``http.route`` (JSON 400 incluído)."""
    context = context or Context()

    def dispatch(_method, path, payload, _query):
        action = path.rstrip("/").rsplit("/", 1)[-1]
        return web_api.handle(action, payload, context)

    monkeypatch.setitem(pia_http._sessions, "t8-e2e-session", time.time() + 60)
    monkeypatch.setattr(
        pia_http, "get_service", lambda: SimpleNamespace(dispatch=dispatch, jobs={})
    )
    body = json.dumps(data, ensure_ascii=False).encode()
    handler = _Handler(body=body)
    assert pia_http.route(handler) is True
    return handler, context

"""Tests for OpenBot dynamic bots: CRUD, SVG sanitization, runs, delegation, and workspace integration."""

from __future__ import annotations

import http.client
import json
import threading
import time
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

from Plugins.OpenBot.models import OpenBotError, sanitize_svg
from Plugins.OpenBot.repository import OpenBotRepository
from Plugins.OpenBot.runtime import OpenBotRuntime
from Plugins.OpenBot.service import OpenBotService
from src import settings_store
from src.tts_service import TTSService

_desktop = ModuleType("src.LocalActions")
_desktop.LocalActions = Mock()
with patch.dict("sys.modules", {"src.LocalActions": _desktop}):
    from src import HTTPServer as http_module


@pytest.fixture
def isolated_openbot(tmp_path, monkeypatch):
    db_path = tmp_path / "settings.sqlite3"
    store = settings_store.SettingsStore(path=db_path)
    monkeypatch.setattr(settings_store, "_store", store)
    monkeypatch.setattr(
        "src.user_paths.user_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    monkeypatch.setattr(
        "Plugins.OpenBot.service.user_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    import src.tts_service as ts_mod

    tts_svc = TTSService()
    monkeypatch.setattr(ts_mod, "_tts_service", tts_svc)

    repo = OpenBotRepository()
    svc = OpenBotService(repo=repo)
    rt = OpenBotRuntime(service=svc)

    import Plugins.OpenBot.service as ob_svc_mod
    import Plugins.OpenBot.runtime as ob_rt_mod

    monkeypatch.setattr(ob_svc_mod, "_openbot_service", svc)
    monkeypatch.setattr(ob_rt_mod, "_openbot_runtime", rt)
    return store, svc, rt


def test_svg_sanitizer_accepts_talking_svg_and_rejects_xss():
    valid = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
        '<circle cx="80" cy="80" r="40" fill="#ad83ff"/>'
        '<g class="enable-mouth animation-talking"><ellipse cx="80" cy="95" rx="8" ry="4"/></g>'
        "</svg>"
    )
    cleaned = sanitize_svg(valid)
    assert "enable-mouth" in cleaned
    assert "animation-talking" in cleaned

    for bad in [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>x</div></foreignObject></svg>',
        '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><style>rect{fill:url(https://evil.test/x)}</style></svg>',
    ]:
        with pytest.raises(OpenBotError):
            sanitize_svg(bad)


def test_openbot_http_crud_avatar_and_workspace_records(isolated_openbot):
    server = http_module.STTThreadingHTTPServer(
        ("127.0.0.1", 0), http_module.HTTPServer
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"

    def req(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            hdrs = dict(headers or {})
            payload = json.dumps(body) if body is not None else None
            if payload is not None:
                hdrs.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                parsed = json.loads(raw.decode()) if raw else None
            except Exception:
                parsed = raw
            return resp.status, parsed, dict(resp.getheaders())
        finally:
            conn.close()

    try:
        st, _, h = req("POST", "/api/pia/session", body={}, headers={"Origin": origin})
        assert st == 200
        cookie = (h.get("Set-Cookie") or h.get("set-cookie")).split(";", 1)[0]
        auth = {"Cookie": cookie, "Origin": origin}

        # Upload sanitized avatar
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="30"/></svg>'
        st_av, av, _ = req(
            "POST", "/api/pia/openbot/avatars", body={"svg": svg}, headers=auth
        )
        assert st_av == 201
        assert av["url"].startswith("/api/pia/openbot/avatars/")

        st_get_av, raw_av, av_hdrs = req("GET", av["url"], headers={"Cookie": cookie})
        assert st_get_av == 200
        assert b"<svg" in raw_av
        assert "image/svg+xml" in (
            av_hdrs.get("Content-Type") or av_hdrs.get("content-type")
        )

        # Create dynamic bot
        st_c, bot, _ = req(
            "POST",
            "/api/pia/openbot/bots",
            body={
                "name": "Revisor Python",
                "description": "Revisa código Python.",
                "instructions": "Seja objetivo.",
                "avatar_id": av["avatar_id"],
                "voice": {
                    "mode": "custom",
                    "profile": {
                        "provider": "kokoro",
                        "model": "kokoro-v1.0",
                        "voice": "pf_dora",
                        "speed": 1.1,
                    },
                },
            },
            headers=auth,
        )
        assert st_c == 201
        bot_id = bot["id"]
        assert bot["kind"] == "dynamic"
        assert bot["voice"]["mode"] == "custom"

        # Workspace /api/pia/bots lists native Secretaria + dynamic bot
        st_list, bots_ws, _ = req("GET", "/api/pia/bots", headers={"Cookie": cookie})
        assert st_list == 200
        kinds = {b["id"]: b["kind"] for b in bots_ws}
        assert kinds["secretaria"] == "native"
        assert kinds[bot_id] == "dynamic"

        # Cannot delete native Secretaria via openbot route
        st_del_sec, _, _ = req(
            "DELETE", "/api/pia/openbot/bots/secretaria", headers=auth
        )
        assert st_del_sec == 403

        # Patch with stale revision -> 409
        st_patch_ok, updated, _ = req(
            "PATCH",
            f"/api/pia/openbot/bots/{bot_id}",
            body={"revision": 1, "name": "Revisor Senior"},
            headers=auth,
        )
        assert st_patch_ok == 200
        assert updated["revision"] == 2

        st_patch_stale, _, _ = req(
            "PATCH",
            f"/api/pia/openbot/bots/{bot_id}",
            body={"revision": 1, "name": "Old"},
            headers=auth,
        )
        assert st_patch_stale == 409

        # Delete dynamic bot with current revision -> 204
        st_del, _, _ = req(
            "DELETE",
            f"/api/pia/openbot/bots/{bot_id}",
            headers={**auth, "If-Match": '"2"'},
        )
        assert st_del == 204
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_openbot_run_execution_and_delegation_limits(isolated_openbot, monkeypatch):
    _, svc, rt = isolated_openbot
    bot_b = svc.create_bot({"name": "Bot B", "instructions": "Responda curto."})
    bot_a = svc.create_bot(
        {
            "name": "Bot A",
            "instructions": "Orquestre.",
            "delegation_targets": [bot_b["id"]],
        }
    )

    class FakeAgentMgr:
        def complete_stream(self, messages, model=None, **options):
            yield "Olá "
            yield "do bot!"

    started = rt.start_run(
        bot_a["id"],
        input_text="Teste",
        speak=False,
        agent_manager=FakeAgentMgr(),
    )
    for _ in range(250):
        snap = rt.get_run(started["run_id"])
        if snap["status"] != "running":
            break
        time.sleep(0.02)
    assert snap.get("error") is None
    assert snap["status"] == "done"
    assert snap["result"] == "Olá do bot!"

    # Delegation allowed
    delegated = rt.delegate_to_bot(
        source_bot_id=bot_a["id"],
        target_bot_id=bot_b["id"],
        task="Subtarefa",
        agent_manager=FakeAgentMgr(),
    )
    assert delegated["status"] == "done"
    assert delegated["result"] == "Olá do bot!"

    # Unauthorized delegation target -> 403
    with pytest.raises(OpenBotError) as exc_info:
        rt.delegate_to_bot(
            source_bot_id=bot_b["id"],
            target_bot_id=bot_a["id"],
            task="Proibido",
            agent_manager=FakeAgentMgr(),
        )
    assert exc_info.value.status == 403

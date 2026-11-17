"""Sanidade do mock HTTP do servidor MCP do Suno (T8 item 1)."""

from __future__ import annotations

import json
import math
import threading
import time

import pytest
import requests

from tests.fixtures.fake_suno_mcp import (
    CLIPS_PER_CALL,
    DEFAULT_REDIRECT_LOCATION,
    DEFAULT_TOKEN,
    FAKE_AUDIO_BYTES,
    FakeSunoMcpServer,
    clips_from_result,
    take_n_clips,
)


def _rpc(
    url: str,
    method: str,
    params: dict | None = None,
    *,
    token: str | None = DEFAULT_TOKEN,
    rpc_id: int = 1,
    timeout: float = 5,
    session: str | None = None,
) -> requests.Response:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session:
        headers["Mcp-Session-Id"] = session
    return requests.post(
        url,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params or {},
        },
        timeout=timeout,
        allow_redirects=False,
    )


def _generate_clips(suno: FakeSunoMcpServer, prompt: str = "piano") -> list[dict]:
    response = _rpc(
        suno.url,
        "tools/call",
        {"name": "generate_music", "arguments": {"prompt": prompt}},
        rpc_id=2,
    )
    assert response.status_code == 200
    return clips_from_result(response.json()["result"])


def test_initialize_and_tools_list_use_heuristic_contract(fake_suno_mcp):
    assert fake_suno_mcp.tools_list_source == "plano-heuristico"
    assert fake_suno_mcp.generation_tool == "generate_music"

    init = _rpc(
        fake_suno_mcp.url,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "pia", "version": "1.0.0"},
        },
    )
    assert init.status_code == 200
    assert init.headers.get("Mcp-Session-Id") == fake_suno_mcp.session_id
    result = init.json()["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "fake-suno-mcp"

    listed = _rpc(fake_suno_mcp.url, "tools/list", rpc_id=2)
    assert listed.status_code == 200
    assert listed.headers.get("Mcp-Session-Id") is None
    names = [tool["name"] for tool in listed.json()["result"]["tools"]]
    assert "generate_music" in names
    assert "get_credits" in names
    schema = next(
        tool["inputSchema"]
        for tool in listed.json()["result"]["tools"]
        if tool["name"] == "generate_music"
    )
    assert "prompt" in schema["properties"]
    assert "lyrics" in schema["properties"]


def test_generate_returns_two_clips_and_serves_fake_audio(fake_suno_mcp):
    response = _rpc(
        fake_suno_mcp.url,
        "tools/call",
        {
            "name": "generate_music",
            "arguments": {"prompt": "piano lo-fi", "duration": 30},
        },
        rpc_id=2,
    )
    assert response.status_code == 200
    clips = clips_from_result(response.json()["result"])
    assert len(clips) == CLIPS_PER_CALL == 2
    assert all(clip["status"] == "complete" for clip in clips)
    assert all(clip["audio_url"].startswith(fake_suno_mcp.base_url) for clip in clips)

    audio = requests.get(clips[0]["audio_url"], timeout=5)
    assert audio.status_code == 200
    assert audio.content == FAKE_AUDIO_BYTES
    assert "audio/mpeg" in audio.headers.get("Content-Type", "")

    recorded = fake_suno_mcp.generation_calls()
    assert len(recorded) == 1
    assert recorded[0].tool_arguments["prompt"] == "piano lo-fi"
    assert "tools/call" in fake_suno_mcp.rpc_methods()


def test_odd_n_uses_two_calls_and_discards_extra_clip(fake_suno_mcp):
    """N=3 → ceil(3/2)=2 chamadas, 4 clips, o excedente é descartado."""
    needed = 3
    batches = []
    for _ in range(math.ceil(needed / CLIPS_PER_CALL)):
        response = _rpc(
            fake_suno_mcp.url,
            "tools/call",
            {"name": "generate_music", "arguments": {"prompt": "jazz"}},
            rpc_id=2,
        )
        assert response.status_code == 200
        batches.append(clips_from_result(response.json()["result"]))

    assert [len(batch) for batch in batches] == [2, 2]
    selected = take_n_clips(batches, needed)
    discarded = [clip for batch in batches for clip in batch][needed:]
    assert len(selected) == 3
    assert len(discarded) == 1
    assert discarded[0]["id"] == batches[1][1]["id"]
    assert len(fake_suno_mcp.generation_calls()) == 2


def test_scenario_sequence_success_then_503(fake_suno_mcp):
    fake_suno_mcp.set_scenarios(["success", "503"])

    first = _rpc(
        fake_suno_mcp.url,
        "tools/call",
        {"name": "generate_music", "arguments": {"prompt": "a"}},
        rpc_id=2,
    )
    assert first.status_code == 200
    assert len(clips_from_result(first.json()["result"])) == 2

    second = _rpc(
        fake_suno_mcp.url,
        "tools/call",
        {"name": "generate_music", "arguments": {"prompt": "b"}},
        rpc_id=3,
    )
    assert second.status_code == 503
    assert second.json()["error"]["message"] == "Suno unavailable"
    assert [req.status for req in fake_suno_mcp.generation_calls()] == [200, 503]


def test_partial_then_failure_leaves_one_valid_clip(fake_suno_mcp):
    """Equivalente CA07 com 1 faixa válida: 1ª chamada parcial, 2ª falha."""
    fake_suno_mcp.set_scenarios(["partial", "401"])

    first = _rpc(
        fake_suno_mcp.url,
        "tools/call",
        {"name": "generate_music", "arguments": {"prompt": "parcial"}},
        rpc_id=2,
    )
    assert first.status_code == 200
    clips = clips_from_result(first.json()["result"])
    assert len(clips) == 2
    assert clips[0]["audio_url"]
    assert clips[1]["audio_url"] is None
    assert clips[1]["status"] == "error"

    audio_ok = requests.get(clips[0]["audio_url"], timeout=5)
    assert audio_ok.content == FAKE_AUDIO_BYTES
    missing_id = clips[1]["id"]
    audio_missing = requests.get(fake_suno_mcp.audio_url(missing_id), timeout=5)
    assert audio_missing.status_code == 404

    second = _rpc(
        fake_suno_mcp.url,
        "tools/call",
        {"name": "generate_music", "arguments": {"prompt": "falha"}},
        rpc_id=3,
    )
    assert second.status_code == 401
    valid = [clip for clip in clips if clip.get("audio_url")]
    assert len(valid) == 1


def test_forced_401_and_wrong_token(fake_suno_mcp):
    fake_suno_mcp.set_scenarios("401")
    denied = _rpc(
        fake_suno_mcp.url,
        "tools/call",
        {"name": "generate_music", "arguments": {"prompt": "x"}},
        rpc_id=2,
    )
    assert denied.status_code == 401
    assert denied.headers.get("WWW-Authenticate") == "Bearer"

    wrong = _rpc(
        fake_suno_mcp.url,
        "tools/list",
        token="token-errado",
        rpc_id=3,
    )
    assert wrong.status_code == 401
    assert wrong.headers.get("WWW-Authenticate") == "Bearer"


def test_timeout_scenario_exceeds_short_client_timeout():
    with FakeSunoMcpServer(scenarios="timeout", timeout_delay=1.0) as suno:
        with pytest.raises(requests.Timeout):
            _rpc(
                suno.url,
                "tools/call",
                {"name": "generate_music", "arguments": {"prompt": "lento"}},
                rpc_id=2,
                timeout=0.2,
            )
        deadline = time.time() + 2.0
        while time.time() < deadline and not suno.generation_calls():
            time.sleep(0.05)
        assert suno.generation_calls()


def test_context_manager_starts_and_stops_cleanly():
    with FakeSunoMcpServer() as suno:
        url = suno.url
        assert _rpc(url, "tools/list").status_code == 200
    with pytest.raises(requests.ConnectionError):
        _rpc(url, "tools/list", timeout=1)
    suno2 = FakeSunoMcpServer()
    suno2.start()
    try:
        assert _rpc(suno2.url, "tools/list").status_code == 200
    finally:
        suno2.stop()


def test_load_tools_list_prefers_t2_fixture(tmp_path):
    from tests.fixtures import fake_suno_mcp as mod

    fixture = tmp_path / "suno_mcp_tools_list.json"
    fixture.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "name": "create_song",
                        "description": "fixture T2",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"prompt": {"type": "string"}},
                            "required": ["prompt"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tools, source = mod.load_suno_tools_list(fixture)
    assert source == "t2-fixture"
    assert tools[0]["name"] == "create_song"
    assert mod.pick_generation_tool(tools) == "create_song"


def test_audio_behavior_http_errors_html_redirect_truncated_and_slow():
    with FakeSunoMcpServer() as suno:
        clips = _generate_clips(suno, "behaviors")
        first, second = clips[0]["id"], clips[1]["id"]

        suno.set_audio_behavior(first, "403")
        denied = requests.get(suno.audio_url(first), timeout=5)
        assert denied.status_code == 403

        suno.set_audio_behavior(first, "404")
        assert requests.get(suno.audio_url(first), timeout=5).status_code == 404

        suno.set_audio_behavior(first, "500")
        assert requests.get(suno.audio_url(first), timeout=5).status_code == 500

        suno.set_audio_behavior(first, "html")
        html = requests.get(suno.audio_url(first), timeout=5)
        assert html.status_code == 200
        assert "text/html" in html.headers.get("Content-Type", "")
        assert b"<html" in html.content

        suno.set_audio_behavior(first, "redirect")
        redirected = requests.get(
            suno.audio_url(first), timeout=5, allow_redirects=False
        )
        assert redirected.status_code == 302
        location = redirected.headers.get("Location")
        assert location == DEFAULT_REDIRECT_LOCATION
        assert location.startswith("http://")
        assert "127.0.0.1" not in location

        suno.set_audio_behavior(
            second, {"mode": "truncated", "content_length": 2048, "body": b"abc"}
        )
        truncated = requests.get(suno.audio_url(second), stream=True, timeout=5)
        declared = int(truncated.headers["Content-Length"])
        assert declared == 2048
        try:
            body = truncated.content
            assert len(body) < declared
        except requests.RequestException:
            pass

        suno.set_audio_behavior(second, {"mode": "slow", "delay": 1.0})
        with pytest.raises(requests.Timeout):
            requests.get(suno.audio_url(second), timeout=0.2)


def test_audio_large_streams_past_a_download_limit():
    """T3 vai monkeypatchar MAX_AUDIO_BYTES; o mock precisa ultrapassar o limite."""
    limit = 1024
    size = limit + 2048
    with FakeSunoMcpServer(audio_behavior={"mode": "large", "size": size}) as suno:
        clip = _generate_clips(suno, "grande")[0]
        with requests.get(clip["audio_url"], stream=True, timeout=10) as resp:
            assert resp.status_code == 200
            assert int(resp.headers["Content-Length"]) == size
            total = 0
            for chunk in resp.iter_content(chunk_size=512):
                total += len(chunk)
            assert total == size
            assert total > limit


def test_session_header_only_on_initialize_and_rotates():
    with FakeSunoMcpServer(require_session=True) as suno:
        first = _rpc(suno.url, "initialize")
        assert first.status_code == 200
        sid1 = first.headers.get("Mcp-Session-Id")
        assert sid1
        listed = _rpc(suno.url, "tools/list", rpc_id=2, session=sid1)
        assert listed.status_code == 200
        assert listed.headers.get("Mcp-Session-Id") is None

        second = _rpc(suno.url, "initialize")
        sid2 = second.headers.get("Mcp-Session-Id")
        assert sid2 and sid2 != sid1
        # a sessão anterior continua válida até expire/DELETE
        assert _rpc(suno.url, "tools/list", rpc_id=3, session=sid1).status_code == 200

        missing = _rpc(suno.url, "tools/list", rpc_id=4)
        assert missing.status_code == 404


def test_expire_sessions_and_delete_allow_rehandshake():
    with FakeSunoMcpServer(require_session=True) as suno:
        sid = _rpc(suno.url, "initialize").headers.get("Mcp-Session-Id")
        assert _rpc(suno.url, "tools/list", rpc_id=2, session=sid).status_code == 200

        suno.expire_sessions()
        denied = _rpc(suno.url, "tools/list", rpc_id=3, session=sid)
        assert denied.status_code == 404

        sid2 = _rpc(suno.url, "initialize").headers.get("Mcp-Session-Id")
        assert sid2 != sid
        assert _rpc(suno.url, "tools/list", rpc_id=4, session=sid2).status_code == 200

        deleted = requests.delete(
            suno.url,
            headers={
                "Authorization": f"Bearer {DEFAULT_TOKEN}",
                "Mcp-Session-Id": sid2,
            },
            timeout=5,
        )
        assert deleted.status_code == 204
        assert _rpc(suno.url, "tools/list", rpc_id=5, session=sid2).status_code == 404

        sid3 = _rpc(suno.url, "initialize").headers.get("Mcp-Session-Id")
        assert _rpc(suno.url, "tools/list", rpc_id=6, session=sid3).status_code == 200


def test_require_session_false_ignores_expiry(fake_suno_mcp):
    assert fake_suno_mcp.require_session is False
    _rpc(fake_suno_mcp.url, "initialize")
    fake_suno_mcp.expire_sessions()
    # sem sessão e com sessão expirada, tools/list segue 200
    assert _rpc(fake_suno_mcp.url, "tools/list", rpc_id=2).status_code == 200


def test_leaky_signs_audio_url_and_leaks_bearer_in_errors():
    with FakeSunoMcpServer(leaky=True, scenarios=["success", "401", "503"]) as suno:
        clips = _generate_clips(suno, "vazamento")
        url = clips[0]["audio_url"]
        assert "X-Amz-Signature=" in url
        assert f"token={DEFAULT_TOKEN}" in url
        assert requests.get(url, timeout=5).content == FAKE_AUDIO_BYTES

        denied = _rpc(
            suno.url,
            "tools/call",
            {"name": "generate_music", "arguments": {"prompt": "x"}},
            rpc_id=3,
        )
        assert denied.status_code == 401
        assert DEFAULT_TOKEN in denied.json()["error"]["message"]
        assert f"Bearer {DEFAULT_TOKEN}" in denied.json()["error"]["message"]

        unavailable = _rpc(
            suno.url,
            "tools/call",
            {"name": "generate_music", "arguments": {"prompt": "y"}},
            rpc_id=4,
        )
        assert unavailable.status_code == 503
        assert f"Bearer {DEFAULT_TOKEN}" in unavailable.json()["error"]["message"]


def test_initialize_requires_auth_and_sends_www_authenticate():
    with FakeSunoMcpServer(auth_on_initialize=True) as suno:
        denied = _rpc(suno.url, "initialize", token=None)
        assert denied.status_code == 401
        assert denied.headers.get("WWW-Authenticate") == "Bearer"
        assert denied.json()["error"]["message"] == "Unauthorized"

    with FakeSunoMcpServer(
        auth_on_initialize=False, required_token=DEFAULT_TOKEN
    ) as suno:
        allowed = _rpc(suno.url, "initialize", token=None)
        assert allowed.status_code == 200
        assert allowed.headers.get("Mcp-Session-Id")


def test_stop_interrupts_timeout_wait():
    suno = FakeSunoMcpServer(scenarios="timeout", timeout_delay=8)
    suno.start()
    errors: list[BaseException] = []

    def call() -> None:
        try:
            _rpc(
                suno.url,
                "tools/call",
                {"name": "generate_music", "arguments": {"prompt": "lento"}},
                rpc_id=2,
                timeout=10,
            )
        except BaseException as exc:  # noqa: BLE001 - o cliente pode cair
            errors.append(exc)

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and not suno.generation_calls():
        time.sleep(0.02)
    assert suno.generation_calls()
    started = time.monotonic()
    suno.stop()
    elapsed = time.monotonic() - started
    thread.join(timeout=2)
    # O que importa: stop() não espera os 8s do timeout_delay.
    # O cliente HTTP pode ainda estar encerrando a conexão.
    assert elapsed < 2


def test_exit_warns_instead_of_raising_and_does_not_mask_exception(monkeypatch):
    with pytest.warns(RuntimeWarning, match="não encerrou"):
        with pytest.raises(ValueError, match="falha do teste"):
            with FakeSunoMcpServer() as suno:
                thread = suno._thread
                assert thread is not None
                monkeypatch.setattr(thread, "join", lambda timeout=None: None)
                monkeypatch.setattr(thread, "is_alive", lambda: True)
                raise ValueError("falha do teste")

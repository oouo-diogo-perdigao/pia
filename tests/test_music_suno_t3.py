"""T3: generate()/generate_suno_batch via SunoMcpAdapter (mock fake_suno_mcp)."""

import json
import sys
import threading

import pytest
import requests

from Plugins.Apps.music import service
from Plugins.Apps.music import tools as music_tools
from src import mcp_connectors
from src.mcp_connectors import MCPRpcError, mask_url, safe_error
from tests.fixtures.fake_suno_mcp import FakeSunoMcpServer


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------
def _manager(tmp_path, monkeypatch):
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    mgr = mcp_connectors.MCPConnectorManager(
        store=WorkspaceStore(tmp_path / "ws.sqlite3"), vault=MemoryVault()
    )
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)
    return mgr


def _quiet_client_resets(server):
    """Our client aborts bad downloads by closing the socket (RST); the mock's
    keep-alive thread would print that ConnectionReset to stderr. Swallow only
    reset/broken-pipe in the mock's handle_error (the mock file is untouched)."""
    httpd = server._httpd
    original = httpd.handle_error

    def handle_error(request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return
        original(request, client_address)

    httpd.handle_error = handle_error


def _register(mgr, server):
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


_ENQUEUED: list = []


@pytest.fixture
def music_out(tmp_path, monkeypatch):
    out = tmp_path / "music"
    monkeypatch.setattr(service, "OUTPUT", out)
    # Short timeouts/polling: no test waits on a real 60 s read or 5 s poll.
    monkeypatch.setattr(service, "_AUDIO_TIMEOUT", (2, 0.5))
    monkeypatch.setattr(service, "_SUNO_SLEEP_SLICE", 0.01)
    monkeypatch.setattr(music_tools, "DEFAULT_POLL_INTERVAL", 0.01)
    _ENQUEUED.clear()
    from Plugins.Connectors.pia_server import media

    monkeypatch.setattr(media, "enqueue", _ENQUEUED.append)
    return out


@pytest.fixture
def suno(tmp_path, monkeypatch, fake_suno_mcp, music_out):
    monkeypatch.setattr(service, "settings", lambda: {"MUSIC_SUNO_TIMEOUT": 20})
    mgr = _manager(tmp_path, monkeypatch)
    _register(mgr, fake_suno_mcp)
    _quiet_client_resets(fake_suno_mcp)
    fake_suno_mcp.mgr = mgr
    fake_suno_mcp.out = music_out
    return fake_suno_mcp


@pytest.fixture
def loopback(monkeypatch):
    monkeypatch.setattr(service, "_ALLOW_LOOPBACK_HTTP_AUDIO", True)


def _files(out):
    return sorted(p.name for p in out.iterdir()) if out.exists() else []


def _audio_files(out):
    return [n for n in _files(out) if not n.endswith(".json")]


class _Resp:
    def __init__(self, status=200, headers=None, chunks=(), on_chunk=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = list(chunks)
        self._on_chunk = on_chunk
        self.closed = False

    def iter_content(self, size):
        for chunk in self._chunks:
            if self._on_chunk:
                self._on_chunk()
            yield chunk

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


# --------------------------------------------------------------------------
# 4 mandatory tests
# --------------------------------------------------------------------------
def test_http_loopback_audio_rejected_by_default(suno):
    assert service._ALLOW_LOOPBACK_HTTP_AUDIO is False
    with pytest.raises(service.SunoDownloadError) as err:
        service._validate_audio_url("http://127.0.0.1:9/audio/x.mp3")
    assert err.value.code == "download_failed"
    # End-to-end: the mock returns http://127.0.0.1 audio => rejected, no GET.
    with pytest.raises(service.SunoDownloadError) as err:
        service.generate("lofi", provider="suno_mcp")
    assert err.value.completed == 0 and err.value.total == 1
    assert not any(r.path.startswith("/audio/") for r in suno.requests)
    assert _files(suno.out) == []


def test_http_external_rejected_even_with_flag(loopback, monkeypatch):
    monkeypatch.setenv("_ALLOW_LOOPBACK_HTTP_AUDIO", "1")  # env is never read
    for url in (
        "http://exemplo.com/a.mp3",
        "http://example.com/a.mp3",
        "http://127.0.0.2/a.mp3",
        "ftp://127.0.0.1/a.mp3",
        "file:///etc/passwd",
        "",
    ):
        with pytest.raises(service.SunoDownloadError):
            service._validate_audio_url(url)
    for url in (
        "http://127.0.0.1:8/a.mp3",
        "http://localhost/a.mp3",
        "http://[::1]:8/a.mp3",
        "https://cdn.suno.test/a.mp3",
    ):
        assert service._validate_audio_url(url) == url
    session = _Session({})
    with pytest.raises(service.SunoDownloadError):
        service._download_audio(
            "http://exemplo.com/a.mp3", service.OUTPUT, session=session
        )
    assert session.calls == []


def test_redirect_to_http_rejected_with_flag_on(suno, loopback):
    suno.set_default_audio_behavior("redirect")  # 302 -> http://example.invalid
    with pytest.raises(service.SunoDownloadError):
        service.generate("lofi", provider="suno_mcp")
    assert _files(suno.out) == []


def test_redirect_to_http_rejected_with_flag_off(tmp_path):
    session = _Session(
        {
            "https://cdn.suno.test/a.mp3": _Resp(
                302, {"Location": "http://cdn.suno.test/a.mp3"}
            )
        }
    )
    with pytest.raises(service.SunoDownloadError):
        service._download_audio(
            "https://cdn.suno.test/a.mp3", tmp_path, session=session
        )
    assert [c[0] for c in session.calls] == ["https://cdn.suno.test/a.mp3"]
    assert all(c[1]["allow_redirects"] is False for c in session.calls)
    assert list(tmp_path.iterdir()) == []


def test_https_redirect_is_followed_and_revalidated(tmp_path):
    session = _Session(
        {
            "https://cdn.suno.test/a": _Resp(302, {"Location": "/b.mp3"}),
            "https://cdn.suno.test/b.mp3": _Resp(
                200, {"Content-Type": "audio/mpeg"}, [b"ID3abc"]
            ),
        }
    )
    path = service._download_audio("https://cdn.suno.test/a", tmp_path, session=session)
    assert path.read_bytes() == b"ID3abc" and path.suffix == ".mp3"
    assert "Authorization" not in str(session.calls)


def test_audio_above_limit_aborts_without_part_file(suno, loopback, monkeypatch):
    monkeypatch.setattr(service, "MAX_AUDIO_BYTES", 1000)
    suno.set_default_audio_behavior({"mode": "large", "size": 5000})
    with pytest.raises(service.SunoDownloadError):
        service.generate("lofi", provider="suno_mcp")
    assert _files(suno.out) == []  # no .part, no audio, no json


def test_streamed_audio_above_limit_without_content_length_leaves_no_part(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(service, "MAX_AUDIO_BYTES", 1000)
    seen_part = []
    resp = _Resp(
        200,
        {"Content-Type": "audio/mpeg"},
        [b"x" * 400] * 5,
        on_chunk=lambda: seen_part.extend(p.name for p in tmp_path.glob("*.part")),
    )
    session = _Session({"https://cdn.suno.test/a.mp3": resp})
    with pytest.raises(service.SunoDownloadError):
        service._download_audio(
            "https://cdn.suno.test/a.mp3", tmp_path, session=session
        )
    assert seen_part  # the stream really went through a .part file
    assert list(tmp_path.iterdir()) == []
    assert resp.closed


# --------------------------------------------------------------------------
# generate() / batch with the mock
# --------------------------------------------------------------------------
def test_generate_uses_adapter_and_saves_one_track(suno, loopback):
    item = service.generate(
        "lofi chill", lyrics="la la", provider="suno_mcp", duration=40
    )
    assert len(suno.generation_calls()) == 1
    assert item["provider"] == "suno_mcp"
    assert item["requested_duration"] == 40 and item["variant"] == 1
    assert item["remote_id"] and item["batch"]
    audio = suno.out / item["file"]
    assert audio.read_bytes().startswith(b"ID3")
    saved = json.loads((suno.out / (item["file"] + ".json")).read_text())
    assert saved == item
    assert "127.0.0.1" not in json.dumps(saved)  # remote URL not persisted
    assert _ENQUEUED == [audio]
    assert len(_audio_files(suno.out)) == 1  # 2nd clip discarded
    assert not service._generation_lock.locked()
    # The audio GET never carries the MCP bearer.
    audio_reqs = [r for r in suno.requests if r.path.startswith("/audio/")]
    assert audio_reqs and all(
        "authorization" not in {k.lower() for k in r.headers} for r in audio_reqs
    )


def test_batch_odd_count_makes_ceil_calls_and_ignores_surplus(suno, loopback):
    tracks = []
    items = service.generate_suno_batch(
        "lofi", count=3, on_track=lambda item, k, n: tracks.append((k, n))
    )
    assert len(suno.generation_calls()) == 2
    assert [i["variant"] for i in items] == [1, 2, 3]
    assert len({i["batch"] for i in items}) == 1
    assert tracks == [(1, 3), (2, 3), (3, 3)]
    assert len(_audio_files(suno.out)) == 3


def test_failed_surplus_clip_is_not_a_failure(suno, loopback):
    suno.set_scenarios(["success", "partial"])  # 2nd call: 2nd clip fails
    items = service.generate_suno_batch("lofi", count=3)
    assert len(items) == 3
    assert len(suno.generation_calls()) == 2


def test_q8_stops_at_first_failed_clip_keeping_previous(suno, loopback):
    suno.set_scenarios(["partial", "success"])
    with pytest.raises(service.SunoClipFailedError) as err:
        service.generate_suno_batch("lofi", count=4)
    assert err.value.completed == 1 and err.value.total == 4
    assert len(err.value.items) == 1
    assert len(suno.generation_calls()) == 1  # no extra call
    assert len(_audio_files(suno.out)) == 1
    assert not service._generation_lock.locked()


def test_q2_download_failure_is_download_failed_and_stops(suno, loopback):
    suno.set_default_audio_behavior(404)
    with pytest.raises(service.SunoDownloadError) as err:
        service.generate_suno_batch("lofi", count=4)
    assert err.value.code == "download_failed"
    assert str(err.value) == service.SunoDownloadError.default_message
    assert err.value.completed == 0
    assert len(suno.generation_calls()) == 1
    assert _files(suno.out) == []


@pytest.mark.parametrize("behavior", ["html", "truncated", 403, 500])
def test_bad_audio_responses_are_download_failed(suno, loopback, behavior):
    suno.set_default_audio_behavior(behavior)
    with pytest.raises(service.SunoDownloadError):
        service.generate("lofi", provider="suno_mcp")
    assert _files(suno.out) == []


def test_auth_error_marks_expired_and_blocks_next_generation(suno, loopback):
    suno.set_scenarios(["401"])
    with pytest.raises(service.SunoAuthError):
        service.generate("lofi", provider="suno_mcp")
    status = service.suno_status()
    assert status["available"] is False and status["credential_state"] == "expired"
    calls = len(suno.generation_calls())
    with pytest.raises(service.SunoAuthError):
        service.generate("lofi", provider="suno_mcp")
    assert len(suno.generation_calls()) == calls  # refused before calling


def test_unavailable_scenario_is_suno_unavailable(suno, loopback):
    suno.set_scenarios(["503"])
    with pytest.raises(service.SunoUnavailableError):
        service.generate("lofi", provider="suno_mcp")
    assert service.suno_status()["available"] is True  # 5xx does not expire


def test_not_configured_is_unavailable_without_calls(tmp_path, monkeypatch, music_out):
    monkeypatch.setattr(service, "settings", lambda: {})
    _manager(tmp_path, monkeypatch)
    with pytest.raises(service.SunoUnavailableError):
        service.generate("lofi", provider="suno_mcp")
    assert not service._generation_lock.locked()


def test_cancel_before_start_makes_no_call(suno, loopback):
    with pytest.raises(InterruptedError):
        service.generate("lofi", provider="suno_mcp", cancelled=lambda: True)
    assert suno.generation_calls() == []


def test_leaky_server_never_leaks_token_or_signed_url(tmp_path, monkeypatch, music_out):
    monkeypatch.setattr(service, "settings", lambda: {"MUSIC_SUNO_TIMEOUT": 20})
    monkeypatch.setattr(service, "_ALLOW_LOOPBACK_HTTP_AUDIO", True)
    with FakeSunoMcpServer(leaky=True, scenarios=["success", "503"]) as server:
        _quiet_client_resets(server)
        mgr = _manager(tmp_path, monkeypatch)
        _register(mgr, server)
        item = service.generate("lofi", provider="suno_mcp")
        dumped = (music_out / (item["file"] + ".json")).read_text()
        assert server.token not in dumped and "Signature" not in dumped
        with pytest.raises(service.SunoUnavailableError) as err:
            service.generate("lofi", provider="suno_mcp")
        assert server.token not in str(err.value)
        assert server.token not in json.dumps(service.suno_status())


# --------------------------------------------------------------------------
# Q1 / Q7 / partial clips (stub adapter)
# --------------------------------------------------------------------------
class _StubAdapter:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _b64_clip(cid):
    import base64

    return {
        "id": cid,
        "audio_base64": base64.b64encode(b"ID3" + cid.encode()).decode(),
        "state": "ready",
    }


def test_q1_fewer_clips_ends_batch_without_extra_call(music_out):
    stub = _StubAdapter([{"clips": [_b64_clip("a")]}, {"clips": [_b64_clip("b")]}])
    with pytest.raises(service.SunoIncompleteBatchError) as err:
        service.generate_suno_batch("lofi", count=4, adapter=stub)
    assert stub.calls == 1
    assert err.value.code == "incomplete_batch"
    assert err.value.completed == 1 and err.value.total == 4
    assert str(err.value) == "1 de 4 músicas prontas (geração interrompida)"
    assert len(err.value.items) == 1 and len(_audio_files(music_out)) == 1


def test_q1_incomplete_message_singular(music_out):
    stub = _StubAdapter([{"clips": []}])
    with pytest.raises(service.SunoIncompleteBatchError) as err:
        service.generate_suno_batch("lofi", count=1, adapter=stub)
    assert str(err.value) == "0 de 1 música pronta (geração interrompida)"
    assert (err.value.completed, err.value.total) == (0, 1)
    assert service.tracks_ready_text(1, 1) == "1 de 1 música pronta"
    assert service.tracks_ready_text(2, 3) == "2 de 3 músicas prontas"


def test_partial_clips_are_saved_when_adapter_times_out(music_out):
    exc = service.SunoTimeoutError()
    exc.partial_clips = [_b64_clip("a"), _b64_clip("b")]
    stub = _StubAdapter([exc])
    with pytest.raises(service.SunoTimeoutError) as err:
        service.generate_suno_batch("lofi", count=1, adapter=stub)
    assert err.value.completed == 1  # only up to N
    assert len(_audio_files(music_out)) == 1


class _CreditsManager:
    def __init__(self, error=None, result=None):
        self.error, self.result = error, result

    def select_account(self, server_id):
        return None

    def _find_raw(self, server_id):
        return {}

    def list_tools(self, server_id, **kwargs):
        return [
            {
                "name": "generate_music",
                "inputSchema": {"type": "object", "properties": {"prompt": {}}},
            }
        ]

    def call_tool(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.result


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} error", response=resp)


@pytest.mark.parametrize(
    "manager",
    [
        _CreditsManager(error=_http_error(402)),
        _CreditsManager(error=MCPRpcError("payment", 402)),
        _CreditsManager(error=MCPRpcError("Insufficient credits for this request")),
        _CreditsManager(
            result={
                "isError": True,
                "content": [
                    {"type": "text", "text": '{"error":"insufficient_credits"}'}
                ],
            }
        ),
    ],
)
def test_q7_no_credits_is_identified(manager, music_out, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: {})
    adapter = music_tools.SunoMcpAdapter(manager=manager, server_id="suno_mcp")
    with pytest.raises(service.SunoNoCreditsError) as err:
        service.generate_suno_batch("lofi", count=2, adapter=adapter)
    assert err.value.code == "suno_no_credits"
    assert str(err.value) == "Sem créditos no Suno. Verifique sua conta."


def test_tool_error_without_credit_signal_is_generic(monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: {})
    mgr = _CreditsManager(
        result={
            "isError": True,
            "content": [{"type": "text", "text": "secret-xyz boom"}],
        }
    )
    adapter = music_tools.SunoMcpAdapter(manager=mgr, server_id="suno_mcp")
    with pytest.raises(service.SunoProtocolError) as err:
        adapter.generate("lofi")
    assert "secret-xyz" not in str(err.value)


# --------------------------------------------------------------------------
# re-review extras (a)-(e)
# --------------------------------------------------------------------------
def test_a_auth_code_survives_timeout_until_success():
    target = {"last_error_code": "401", "last_error": "HTTP 401"}
    mgr_cls = mcp_connectors.MCPConnectorManager
    mgr_cls._record_outcome(target, requests.Timeout("slow"))
    assert target["last_error_code"] == "401"
    mgr_cls._record_outcome(target, _http_error(503))
    assert target["last_error_code"] == "401"
    mgr_cls._record_outcome(target, _http_error(403))
    assert target["last_error_code"] == "403"
    mgr_cls._record_outcome(target, None)
    assert target["last_error_code"] is None
    mgr_cls._record_outcome(target, requests.Timeout("slow"))
    assert target["last_error_code"] != "401"


def test_a_timeout_after_401_keeps_suno_expired(suno, loopback):
    suno.set_scenarios(["401"])
    with pytest.raises(service.SunoAuthError):
        service.generate("lofi", provider="suno_mcp")
    with pytest.raises(Exception):
        suno.mgr.call_tool("suno_mcp", "generate_music", {"prompt": "x"}, timeout=0.01)
    assert service.suno_status()["credential_state"] == "expired"
    # New credential clears it.
    _register(suno.mgr, suno)
    suno.mgr.save_server({"bearer_token": suno.token}, server_id="suno_mcp")
    assert service.suno_status()["credential_state"] == "configured"


def test_b_jsonrpc_auth_error_maps_to_401():
    assert safe_error(MCPRpcError("denied", -32001))[0] == "401"
    assert safe_error(MCPRpcError("Unauthorized: token expired", -32000))[0] == "401"
    assert safe_error(MCPRpcError("Payment required", 402))[0] == "402"
    assert safe_error(MCPRpcError("Suno unavailable", -32000))[0] != "401"
    assert isinstance(
        music_tools.translate_suno_error(MCPRpcError("denied", -32001)),
        service.SunoAuthError,
    )


def test_b_parse_rpc_response_keeps_jsonrpc_code(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    resp = requests.Response()
    resp.status_code = 200
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "nope"}}
    ).encode()
    with pytest.raises(MCPRpcError) as err:
        mgr._parse_rpc_response(resp, 1)
    assert err.value.rpc_code == -32001


def test_c_single_mask_url():
    assert service._mask_url is mcp_connectors.mask_url
    assert service._keep_if_masked is mcp_connectors.keep_if_masked
    import inspect

    assert "def _mask_url" not in inspect.getsource(service)


def test_d_runtime_fields_merge_into_fresh_store(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    mgr.save_server(
        {
            "id": "s1",
            "name": "S1",
            "transport": "http_streaming",
            "url": "https://x.test/mcp",
            "accounts": [{"id": "a1", "name": "A1", "bearer_token": "t1"}],
        },
        server_id="s1",
    )

    def slow_exec(server, account, method, params, timeout=None):
        # A concurrent change (e.g. OAuth/settings) lands during the call.
        mgr.save_server({"name": "Renamed"}, server_id="s1")
        return {"ok": True}

    monkeypatch.setattr(mgr, "_exec_single", slow_exec)
    mgr.call_tool("s1", "t", {}, retry_other_accounts=False)
    raw = mgr._find_raw("s1")
    assert raw["name"] == "Renamed"  # not clobbered by the stale snapshot
    assert raw["accounts"][0]["usage_count"] == 1


def test_d_concurrent_calls_do_not_lose_usage(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    mgr.save_server(
        {
            "id": "s1",
            "name": "S1",
            "transport": "http_streaming",
            "url": "https://x.test/mcp",
            "accounts": [{"id": "a1", "name": "A1", "bearer_token": "t1"}],
        },
        server_id="s1",
    )
    monkeypatch.setattr(mgr, "_exec_single", lambda *a, **k: {"ok": True})
    threads = [
        threading.Thread(
            target=mgr.call_tool, args=("s1", "t", {}), kwargs={"account_id": "a1"}
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert mgr._find_raw("s1")["accounts"][0]["usage_count"] == 8


def test_e_start_oauth_keeps_real_urls_when_masked(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    real_auth = "https://auth.suno.test/authorize?tenant=t-secret"
    real_token = "https://auth.suno.test/token?k=k-secret"
    mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "transport": "http_streaming",
            "url": "https://api.suno.com/mcp",
            "accounts": [
                {
                    "id": "default",
                    "name": "Suno OAuth",
                    "auth_type": "oauth",
                    "oauth": {
                        "client_id": "cid",
                        "auth_url": real_auth,
                        "token_url": real_token,
                    },
                }
            ],
        },
        server_id="suno_mcp",
    )
    mgr.start_oauth(
        "suno_mcp",
        account_id="default",
        payload={
            "client_id": "cid",
            "auth_url": mask_url(real_auth),
            "token_url": mask_url(real_token),
        },
    )
    oauth = mgr._find_raw("suno_mcp")["accounts"][0]["oauth"]
    assert oauth["auth_url"] == real_auth and oauth["token_url"] == real_token
    # A genuinely new URL still overwrites.
    mgr.start_oauth(
        "suno_mcp",
        account_id="default",
        payload={"auth_url": "https://auth2.suno.test/authorize"},
    )
    oauth = mgr._find_raw("suno_mcp")["accounts"][0]["oauth"]
    assert oauth["auth_url"] == "https://auth2.suno.test/authorize"


# --------------------------------------------------------------------------
# isError with authorization text -> last_error_code "401" (code only)
# --------------------------------------------------------------------------
def _tool_server(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "transport": "http_streaming",
            "url": "https://api.suno.com/mcp",
            "bearer_token": "tok-secret-1",
        },
        server_id="suno_mcp",
    )
    return mgr


def _is_error(text):
    return {"isError": True, "content": [{"type": "text", "text": text}]}


def test_is_error_auth_text_records_401_without_raw_text(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: {})
    mgr = _tool_server(tmp_path, monkeypatch)
    raw_text = "Unauthorized: access token expired (req-secret-77)"
    monkeypatch.setattr(mgr, "_exec_single", lambda *a, **k: _is_error(raw_text))
    adapter = music_tools.SunoMcpAdapter(
        manager=mgr, server_id="suno_mcp", tool_name="generate_music"
    )
    monkeypatch.setattr(
        adapter,
        "tools",
        lambda refresh=False: [
            {
                "name": "generate_music",
                "inputSchema": {"type": "object", "properties": {"prompt": {}}},
            }
        ],
    )
    with pytest.raises(service.SunoAuthError):
        adapter.generate("lofi")
    raw = mgr._find_raw("suno_mcp")
    assert raw["last_error_code"] == "401"
    assert "req-secret-77" not in json.dumps(raw)
    assert raw["last_error"] == mcp_connectors.TOOL_AUTH_ERROR_MESSAGE
    status = service.suno_status()
    assert status["available"] is False and status["credential_state"] == "expired"


@pytest.mark.parametrize(
    "text",
    [
        "Generation failed: prompt rejected",
        "Forbidden content in lyrics",
        "Token limit exceeded for prompt",
        "oauth scope note: generation queue full",
    ],
)
def test_common_is_error_does_not_mark_401(tmp_path, monkeypatch, text):
    monkeypatch.setattr(service, "settings", lambda: {})
    mgr = _tool_server(tmp_path, monkeypatch)
    monkeypatch.setattr(mgr, "_exec_single", lambda *a, **k: _is_error(text))
    result = mgr.call_tool(
        "suno_mcp", "generate_music", {"prompt": "x"}, retry_other_accounts=False
    )
    assert result["isError"] is True
    assert mgr._find_raw("suno_mcp").get("last_error_code") in (None, "")
    assert service.suno_status()["available"] is True
    assert not mcp_connectors.is_tool_auth_error(_is_error(text))


@pytest.mark.parametrize(
    "text",
    [
        "unauthorized",
        "Invalid token",
        "invalid_access_token",
        "token has expired",
        "Authentication required",
        "not authenticated",
    ],
)
def test_tool_auth_detection_positive_cases(text):
    assert mcp_connectors.is_tool_auth_error(_is_error(text))
    assert not mcp_connectors.is_tool_auth_error({"content": [{"text": text}]})


# --------------------------------------------------------------------------
# polling waits on an Event (no real sleep), honours cancel quickly
# --------------------------------------------------------------------------
class _PollingManager:
    def __init__(self, ready_after=2):
        self.ready_after = ready_after
        self.status_calls = 0

    def select_account(self, server_id):
        return None

    def _find_raw(self, server_id):
        return {}

    def list_tools(self, server_id, **kwargs):
        return [
            {
                "name": "generate_music",
                "inputSchema": {"type": "object", "properties": {"prompt": {}}},
            },
            {
                "name": "get_clip",
                "inputSchema": {"type": "object", "properties": {"id": {}}},
            },
        ]

    def call_tool(self, server_id, name, args, **kwargs):
        import base64

        audio = base64.b64encode(b"ID3poll").decode()
        if name == "generate_music":
            return {
                "structuredContent": {
                    "clips": [
                        {"id": "c1", "status": "queued"},
                        {"id": "c2", "status": "queued"},
                    ]
                }
            }
        self.status_calls += 1
        if self.status_calls >= self.ready_after:
            return {
                "structuredContent": {
                    "clips": [
                        {"id": args["id"], "status": "complete", "audio_base64": audio}
                    ]
                }
            }
        return {
            "structuredContent": {"clips": [{"id": args["id"], "status": "queued"}]}
        }


@pytest.fixture
def polling_env(monkeypatch, music_out):
    import time as time_mod

    mgr = _PollingManager()
    monkeypatch.setattr(service, "settings", lambda: {"MUSIC_SUNO_TIMEOUT": 20})
    monkeypatch.setattr(
        service, "suno_status", lambda: {"available": True, "server_id": "suno_mcp"}
    )
    monkeypatch.setattr(mcp_connectors, "get_mcp_manager", lambda: mgr)

    real_sleep = time_mod.sleep
    test_thread = threading.get_ident()

    def no_real_sleep(*args, **kwargs):
        # Only the batch/polling (this thread) is forbidden to sleep for real;
        # unrelated background threads of the app keep the real time.sleep.
        if threading.get_ident() == test_thread:
            raise AssertionError("time.sleep real não pode ser usado no polling")
        return real_sleep(*args, **kwargs)

    monkeypatch.setattr(time_mod, "sleep", no_real_sleep)
    return mgr


def test_batch_polls_with_event_and_short_interval(polling_env):
    import time

    start = time.monotonic()
    items = service.generate_suno_batch("lofi", count=1)
    assert len(items) == 1 and polling_env.status_calls >= 2
    assert time.monotonic() - start < 2


def test_cancel_during_poll_is_fast_even_with_long_interval(polling_env, monkeypatch):
    import time

    monkeypatch.setattr(music_tools, "DEFAULT_POLL_INTERVAL", 30)
    polling_env.ready_after = 10**6
    start = time.monotonic()
    flag = {"n": 0}

    def cancelled():
        flag["n"] += 1
        return time.monotonic() - start > 0.2

    with pytest.raises(InterruptedError) as err:
        service.generate_suno_batch("lofi", count=1, cancelled=cancelled)
    assert time.monotonic() - start < 3
    assert err.value.completed == 0

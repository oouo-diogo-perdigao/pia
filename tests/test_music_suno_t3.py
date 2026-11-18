"""T3: robustez do MCP genérico, mais (T6) o
cliente tipado da API de dispositivo da PIA Server e o download pelo proxy.

Os testes de generate()/generate_suno_batch via SunoMcpAdapter e do OAuth/DCR
local do Suno saíram na T8 (RN18). O fluxo Suno agora é remoto: os e2e estão
em test_music_suno_e2e.py e o histórico em test_music_history_t6.py; aqui
ficam o mapeamento de códigos do servidor e a segurança do download pelo proxy.
O download direto de links de áudio do Suno (``service._download_audio``) e
seus testes saíram na T9: o áudio só chega pelo proxy da PIA Server.
"""

import json
import threading

import pytest
import requests

from Plugins.Apps.music import service
from src import mcp_connectors
from src.mcp_connectors import MCPRpcError, mask_url, safe_error


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


# --------------------------------------------------------------------------
# HTTP error helper
# --------------------------------------------------------------------------


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} error", response=resp)


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


def test_b_jsonrpc_auth_error_maps_to_401():
    assert safe_error(MCPRpcError("denied", -32001))[0] == "401"
    assert safe_error(MCPRpcError("Unauthorized: token expired", -32000))[0] == "401"
    assert safe_error(MCPRpcError("Payment required", 402))[0] == "402"
    assert safe_error(MCPRpcError("Suno unavailable", -32000))[0] != "401"


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


# --- DEVE 3: a policy "forbidden" never becomes 401 -----------------------
def test_f3_policy_forbidden_is_not_401(tmp_path, monkeypatch):
    policy = MCPRpcError("Forbidden: lyrics violate content policy", -32000)
    assert safe_error(policy)[0] != "401"
    assert safe_error(MCPRpcError("Unauthorized: token expired", -32000))[0] == "401"
    assert safe_error(MCPRpcError("nope", -32001))[0] == "401"

    monkeypatch.setattr(service, "settings", lambda: {})
    mgr = _tool_server(tmp_path, monkeypatch)

    def raise_policy(*_a, **_k):
        raise policy

    monkeypatch.setattr(mgr, "_exec_single", raise_policy)
    with pytest.raises(MCPRpcError):
        mgr.call_tool("suno_mcp", "generate_music", {}, retry_other_accounts=False)
    assert mgr._find_raw("suno_mcp")["last_error_code"] != "401"


# --- S7: save_server/start_oauth/complete_oauth share _store_lock ---------
@pytest.mark.parametrize("method", ["save_server", "start_oauth", "complete_oauth"])
def test_s7_store_writers_take_the_store_lock(tmp_path, monkeypatch, method):
    mgr = _tool_server(tmp_path, monkeypatch)
    calls = {
        "save_server": lambda: mgr.save_server({"name": "X"}, server_id="suno_mcp"),
        "start_oauth": lambda: mgr.start_oauth(
            "suno_mcp", payload={"client_id": "c", "auth_url": "https://a.test/auth"}
        ),
        "complete_oauth": lambda: mgr.complete_oauth(
            "suno_mcp", {"state": "nope", "code": "x"}
        ),
    }
    done = threading.Event()

    def run():
        try:
            calls[method]()
        except Exception:
            pass
        finally:
            done.set()

    mgr._store_lock.acquire()
    worker = threading.Thread(target=run)
    try:
        worker.start()
        assert not done.wait(0.2)  # blocked on the lock
    finally:
        mgr._store_lock.release()
    worker.join(5)
    assert done.is_set() and not worker.is_alive()


# ==========================================================================
# T3 follow-up 2 (review 18:43)
# ==========================================================================
def _json_resp(data):
    resp = requests.Response()
    resp.status_code = 200
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(data).encode()
    return resp


def _blocking_post(monkeypatch, data, on_enter=None):
    """Fake OAuth endpoint that blocks on ``release`` (no real sleep).

    ``entered`` is set once the POST is in flight; the test checks concurrent
    work finished while ``release`` is still unset, then releases it.
    """
    state = {"entered": threading.Event(), "release": threading.Event(), "urls": []}

    def post(url, **_kwargs):
        state["urls"].append(url)
        if on_enter is not None:
            on_enter()
        state["entered"].set()
        state["release"].wait(10)
        return _json_resp(data)

    monkeypatch.setattr(mcp_connectors.requests, "post", post)
    return state


def _oauth_srv(mgr):
    mgr.save_server(
        {
            "id": "srv",
            "name": "Srv",
            "transport": "http_streaming",
            "url": "https://mcp.example.test/mcp",
            "accounts": [
                {
                    "id": "a1",
                    "name": "A1",
                    "auth_type": "oauth",
                    "oauth": {
                        "client_id": "cid",
                        "auth_url": "https://auth.example.test/authorize",
                        "token_url": "https://auth.example.test/token",
                    },
                }
            ],
        },
        server_id="srv",
    )


def _spawn(fn, threads):
    """Run ``fn`` in a daemon thread; result/error land in the returned box."""
    box: dict = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    threads.append(thread)
    thread.start()
    return thread, box


def _join_all(fake, threads):
    fake["release"].set()
    for thread in threads:
        thread.join(5)
    assert not any(t.is_alive() for t in threads)


def _drop_account(mgr, server_id, account_id):
    servers = mgr._raw_servers()
    for srv in servers:
        if srv.get("id") == server_id:
            srv["accounts"] = [
                a for a in srv.get("accounts") or [] if a.get("id") != account_id
            ]
    mgr._save_raw_servers(servers)


# --- 1: OAuth HTTP runs outside _store_lock ---------------------------------
def test_g1_complete_oauth_token_exchange_does_not_block_merge(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    state = mgr.start_oauth("srv", account_id="a1")["state"]
    fake = _blocking_post(monkeypatch, {"access_token": "tok-new"})
    threads: list = []
    try:
        _oauth_t, oauth_box = _spawn(
            lambda: mgr.complete_oauth("srv", {"state": state, "code": "c1"}), threads
        )
        assert fake["entered"].wait(5)
        merge_t, merge_box = _spawn(
            lambda: mgr._merge_runtime("srv", "a1", lambda t: t.update(usage_count=7)),
            threads,
        )
        cursor_t, cursor_box = _spawn(lambda: mgr._advance_cursor("srv", 1), threads)
        merge_t.join(5)
        cursor_t.join(5)
        # Finished while the token POST is still blocked => no lock held there.
        assert not fake["release"].is_set()
        assert not merge_t.is_alive() and not cursor_t.is_alive()
        assert "error" not in merge_box and "error" not in cursor_box
    finally:
        _join_all(fake, threads)
    assert "error" not in oauth_box
    acc = mgr._find_raw("srv")["accounts"][0]
    assert acc["usage_count"] == 7  # runtime merge survived the token merge
    assert acc["oauth"]["connected"] is True and acc["last_error_code"] is None
    assert fake["urls"] == ["https://auth.example.test/token"]


def test_g1_duplicate_callback_cannot_reuse_code(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    state = mgr.start_oauth("srv", account_id="a1")["state"]
    fake = _blocking_post(monkeypatch, {"access_token": "tok-new"})
    threads: list = []
    try:
        _first_t, first_box = _spawn(
            lambda: mgr.complete_oauth("srv", {"state": state, "code": "c1"}), threads
        )
        assert fake["entered"].wait(5)
        second_t, second_box = _spawn(
            lambda: mgr.complete_oauth("srv", {"state": state, "code": "c1"}), threads
        )
        second_t.join(5)
        assert not fake["release"].is_set()
        assert not second_t.is_alive()  # answered while the 1st POST is blocked
        assert isinstance(second_box.get("error"), ValueError)
        assert "já utilizado" in str(second_box["error"])
    finally:
        _join_all(fake, threads)
    assert "error" not in first_box
    assert len(fake["urls"]) == 1  # the code was exchanged only once
    assert mgr._find_raw("srv")["accounts"][0]["oauth"]["connected"] is True


# --- account removed during the OAuth HTTP ----------------------------------
def test_g1_complete_oauth_account_removed_drops_tokens(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    state = mgr.start_oauth("srv", account_id="a1")["state"]
    fake = _blocking_post(
        monkeypatch,
        {"access_token": "tok-orphan", "refresh_token": "ref-orphan"},
        on_enter=lambda: _drop_account(mgr, "srv", "a1"),
    )
    fake["release"].set()  # no concurrency needed here
    with pytest.raises(ValueError) as err:
        mgr.complete_oauth("srv", {"state": state, "code": "c1"})
    assert str(err.value) == mcp_connectors.OAUTH_ACCOUNT_REMOVED_MESSAGE
    assert not mgr._get_secret("srv", "a1", "oauth_access_token")
    assert not mgr._get_secret("srv", "a1", "oauth_refresh_token")
    assert mgr._find_raw("srv")["accounts"] == []


# ==========================================================================
# inspect_server / delete_server vs. the store lock (pre-existing bug)
# ==========================================================================
def _blocking_tools_list(monkeypatch, mgr):
    """tools/list blocks on ``release`` (no sleep); tools/call answers 401."""
    state = {"entered": threading.Event(), "release": threading.Event()}

    def exec_single(server, account, method, params, timeout=None):
        if method == "tools/list":
            state["entered"].set()
            state["release"].wait(10)
            return {"tools": [{"name": "fresh_tool", "description": "nova"}]}
        raise _http_error(401)

    monkeypatch.setattr(mgr, "_exec_single", exec_single)
    return state


def test_inspect_does_not_undo_oauth_connection_made_during_tools_list(
    tmp_path, monkeypatch
):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    fake = _blocking_tools_list(monkeypatch, mgr)
    threads: list = []
    try:
        _inspect_t, inspect_box = _spawn(lambda: mgr.inspect_server("srv"), threads)
        assert fake["entered"].wait(5)
        oauth_t, oauth_box = _spawn(
            lambda: mgr.complete_oauth(
                "srv", {"account_id": "a1", "access_token": "tok-during-inspect"}
            ),
            threads,
        )
        oauth_t.join(5)
        assert not fake["release"].is_set() and not oauth_t.is_alive()
        assert "error" not in oauth_box
    finally:
        _join_all(fake, threads)
    assert inspect_box["result"]["status"] == "online"
    raw = mgr._find_raw("srv")
    acc = raw["accounts"][0]
    assert acc["oauth"]["connected"] is True  # not undone by the inspect
    assert acc["oauth"]["token_masked"]
    assert raw["last_status"] == "online"
    assert [t["name"] for t in raw["cached_tools"]] == ["fresh_tool"]


def test_inspect_does_not_erase_401_recorded_during_tools_list(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    fake = _blocking_tools_list(monkeypatch, mgr)
    threads: list = []
    try:
        _inspect_t, inspect_box = _spawn(lambda: mgr.inspect_server("srv"), threads)
        assert fake["entered"].wait(5)
        call_t, call_box = _spawn(
            lambda: mgr.call_tool("srv", "generate", {}, account_id="a1"), threads
        )
        call_t.join(5)
        assert not fake["release"].is_set() and not call_t.is_alive()
        assert isinstance(call_box.get("error"), requests.HTTPError)
    finally:
        _join_all(fake, threads)
    assert "error" not in inspect_box
    acc = mgr._find_raw("srv")["accounts"][0]
    assert acc["last_error_code"] == "401"  # still expired after the inspect
    assert acc["usage_count"] == 0


def test_inspect_offline_keeps_cached_tools_and_records_status(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    mgr._merge_runtime("srv", None, lambda t: t.update(cached_tools=[{"name": "old"}]))

    def offline(*_a, **_k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(mgr, "_exec_single", offline)
    result = mgr.inspect_server("srv")
    assert result["status"] == "offline" and result["connection_error"]
    raw = mgr._find_raw("srv")
    assert raw["last_status"] == "offline" and raw["last_inspected_at"]
    assert raw["cached_tools"] == [{"name": "old"}]
    assert not raw.get("last_error_code")  # inspect does not persist errors


def test_delete_server_takes_the_store_lock(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _oauth_srv(mgr)
    threads: list = []
    done = threading.Event()
    mgr._store_lock.acquire()
    try:
        delete_t, delete_box = _spawn(
            lambda: (mgr.delete_server("srv"), done.set()), threads
        )
        assert not done.wait(0.2)  # blocked while the lock is held
        assert delete_t.is_alive()
    finally:
        mgr._store_lock.release()
    delete_t.join(5)
    assert not delete_t.is_alive() and done.is_set()
    assert "error" not in delete_box
    assert all(s.get("id") != "srv" for s in mgr._raw_servers())


# ==========================================================================
# T6: device API (pia-server) -> exceções tipadas; download pelo proxy
# ==========================================================================
from Plugins.Apps.music import remote_suno  # noqa: E402
from Plugins.Connectors.pia_server import remote as pia_device  # noqa: E402
from tests._suno_remote_support import remote_env  # noqa: E402,F401  (fixture)


class _Response:
    def __init__(self, status, body=None, headers=None, chunks=()):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self._chunks = chunks
        self.content = b"x" if body is not None else b""

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        pass


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (401, {"error": "Pareamento inválido."}, "pia_server_unpaired"),
        (401, {"error": "x", "code": "suno_credential_expired"}, "pia_server_unpaired"),
        (500, {"error": "x", "code": "internal_error"}, "pia_server_unreachable"),
        (503, ValueError("html"), "pia_server_unreachable"),
        (409, {"error": "x", "code": "suno_job_active"}, "suno_job_active"),
        (400, {"error": "x", "code": "suno_account_mismatch"}, "suno_account_mismatch"),
        (
            410,
            {"error": "x", "code": "suno_track_unavailable"},
            "suno_track_unavailable",
        ),
        (400, {"error": "x", "code": "Bad Code!"}, "pia_server_error"),
        (404, ValueError("no json"), "pia_server_error"),
    ],
)
def test_device_error_mapping(remote, monkeypatch, status, body, code):
    monkeypatch.setattr(requests, "request", lambda *a, **k: _Response(status, body))
    with pytest.raises(pia_device.DeviceApiError) as err:
        pia_device.device_call("GET", "suno/status")
    assert err.value.code == code and isinstance(err.value, ValueError)


def test_device_connection_error_is_unreachable(remote, monkeypatch):
    def boom(*_a, **_k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "request", boom)
    with pytest.raises(pia_device.DeviceApiError) as err:
        pia_device.device_call("GET", "account")
    assert err.value.code == "pia_server_unreachable"


def test_device_call_sends_protocol_header_and_no_redirects(remote, monkeypatch):
    seen = {}

    def fake(method, url, **kwargs):
        seen.update(kwargs, method=method, url=url)
        return _Response(200, {"ok": True})

    monkeypatch.setattr(requests, "request", fake)
    assert pia_device.device_call("GET", "account") == {"ok": True}
    assert seen["headers"]["X-PIA-Protocol"] == "1"
    assert seen["headers"]["Authorization"].startswith("Bearer ")
    assert seen["allow_redirects"] is False and seen["url"].endswith("/device/account")


def test_external_http_server_url_is_unpaired_even_with_loopback_flag(remote):
    remote.profile.save(
        "Connectors/pia_server", {"PIA_SERVER_URL": "http://example.com"}
    )
    assert pia_device.device_paired() is False


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Type": "audio/mpeg", "Content-Length": str(100 * 1024**2 + 1)},
        {"Content-Type": "audio/mpeg", "Content-Length": "999"},
        {"Content-Type": "audio/mpeg", "X-Content-SHA256": "0" * 64},
    ],
)
def test_proxy_download_rejections_leave_no_file(remote, monkeypatch, headers):
    monkeypatch.setattr(
        requests, "request", lambda *a, **k: _Response(200, None, headers, [b"ID3abc"])
    )
    with pytest.raises(service.SunoDownloadError):
        remote_suno.download_track("gen-1", 1)
    assert not remote.output.exists() or not list(remote.output.iterdir())


def test_proxy_download_streaming_above_limit_without_length(remote, monkeypatch):
    monkeypatch.setattr(service, "MAX_AUDIO_BYTES", 10)
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **k: _Response(
            200, None, {"Content-Type": "audio/mpeg"}, [b"x" * 6] * 3
        ),
    )
    with pytest.raises(service.SunoDownloadError):
        remote_suno.download_track("gen-1", 1)
    assert not list(remote.output.glob("*"))


def test_proxy_download_ok_checks_sha256(remote):
    gen = remote.fake.add_generation()
    path = remote_suno.download_track(gen["id"], 1)
    from tests.fixtures.fake_pia_server_suno import audio_bytes

    assert path.parent == remote.output and path.read_bytes() == audio_bytes(
        gen["id"], 1
    )
    assert not list(remote.output.glob("*.part"))


@pytest.mark.parametrize(
    ("code", "cls", "text"),
    [
        (
            "suno_credential_expired",
            service.SunoAuthError,
            "A autorização da conta Suno Pessoal expirou. Reconecte em Configurações → Música",
        ),
        (
            "suno_no_credits",
            service.SunoNoCreditsError,
            "A conta Suno Pessoal está sem créditos.",
        ),
        ("suno_unavailable", service.SunoUnavailableError, None),
        ("suno_timeout", service.SunoTimeoutError, None),
        (
            "download_failed",
            service.SunoDownloadError,
            remote_suno.DOWNLOAD_FAILED_MESSAGE,
        ),
        (
            "suno_track_unavailable",
            remote_suno.SunoTrackUnavailableError,
            "Esta música não está mais disponível no Suno.",
        ),
        ("incomplete_batch", service.SunoIncompleteBatchError, None),
    ],
)
def test_job_error_codes_are_typed(code, cls, text):
    exc = remote_suno.job_error(code, "Pessoal", 1, 3)
    assert isinstance(exc, cls) and exc.code == code
    if text:
        assert str(exc) == text


def test_job_error_rejects_weird_codes():
    assert remote_suno.job_error("<script>").code == "error"

"""T3: download seguro do áudio e robustez do MCP genérico.

Os testes de generate()/generate_suno_batch via SunoMcpAdapter e do OAuth/DCR
local do Suno saíram na T8 (RN18); a T6 reescreve o fluxo contra o fake da
pia-server.
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
    _ENQUEUED.clear()
    from Plugins.Connectors.pia_server import media

    monkeypatch.setattr(media, "enqueue", _ENQUEUED.append)
    return out


@pytest.fixture
def suno(tmp_path, monkeypatch, fake_suno_mcp, music_out):
    monkeypatch.setattr(service, "settings", lambda: {"MUSIC_SUNO_TIMEOUT": 20})
    mgr = _manager(tmp_path, monkeypatch)
    _register(mgr, fake_suno_mcp)
    fake_suno_mcp.mgr = mgr
    fake_suno_mcp.out = music_out
    return fake_suno_mcp


@pytest.fixture
def loopback(monkeypatch):
    monkeypatch.setattr(service, "_ALLOW_LOOPBACK_HTTP_AUDIO", True)


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


# --------------------------------------------------------------------------
# Q1 / Q7 / partial clips (stub adapter)
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


# --------------------------------------------------------------------------
# polling waits on an Event (no real sleep), honours cancel quickly
# --------------------------------------------------------------------------


# ==========================================================================
# T3 follow-up (review 18:35)
# ==========================================================================
def _ok_resp(chunks=(b"ID3abc",), on_chunk=None):
    return _Resp(200, {"Content-Type": "audio/mpeg"}, list(chunks), on_chunk=on_chunk)


# --- DEVE 1: OSError of mkdir/os.replace becomes download_failed ----------
def test_f1_os_replace_failure_is_download_failed_without_part(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(service.os, "replace", boom)
    session = _Session({"https://cdn.suno.test/a.mp3": _ok_resp()})
    with pytest.raises(service.SunoDownloadError) as err:
        service._download_audio(
            "https://cdn.suno.test/a.mp3", tmp_path, session=session
        )
    assert err.value.code == "download_failed"
    with pytest.raises(service.SunoDownloadError):
        service._write_audio_bytes(b"ID3abc", tmp_path, "mp3")
    assert list(tmp_path.iterdir()) == []


def test_f1_mkdir_failure_is_download_failed(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    session = _Session({"https://cdn.suno.test/a.mp3": _ok_resp()})
    with pytest.raises(service.SunoDownloadError):
        service._download_audio("https://cdn.suno.test/a.mp3", blocker, session=session)
    with pytest.raises(service.SunoDownloadError):
        service._write_audio_bytes(b"ID3abc", blocker / "sub", "mp3")
    assert [p.name for p in tmp_path.iterdir()] == ["not-a-dir"]


# --- DEVE 2: after cancel keep only what was saved; no new download -------


def test_f2_cancel_mid_download_leaves_no_part(tmp_path):
    state = {"n": 0}

    def on_chunk():
        state["n"] += 1

    resp = _ok_resp([b"x" * 100] * 5, on_chunk=on_chunk)
    session = _Session({"https://cdn.suno.test/a.mp3": resp})
    with pytest.raises(InterruptedError) as err:
        service._download_audio(
            "https://cdn.suno.test/a.mp3",
            tmp_path,
            session=session,
            cancelled=lambda: state["n"] >= 2,
        )
    assert str(err.value) == service.SUNO_CANCEL_MESSAGE
    assert list(tmp_path.iterdir()) == [] and resp.closed


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


# --- S1: block non-public IP literals (URL and redirects) -----------------
@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.1/a.mp3",
        "https://192.168.1.2/a.mp3",
        "https://172.16.0.9/a.mp3",
        "https://169.254.169.254/latest/meta-data",
        "https://127.0.0.1/a.mp3",
        "https://[::1]/a.mp3",
        "https://[fe80::1]/a.mp3",
        "https://[fd00::1]/a.mp3",
        "https://0.0.0.0/a.mp3",
        "https://localhost/a.mp3",
    ],
)
def test_s1_non_public_ip_literals_rejected(url):
    with pytest.raises(service.SunoDownloadError):
        service._validate_audio_url(url)


def test_s1_public_hosts_allowed_and_flag_only_opens_loopback(monkeypatch):
    assert service._validate_audio_url("https://8.8.8.8/a.mp3")
    assert service._validate_audio_url("https://cdn1.suno.ai/a.mp3")
    monkeypatch.setattr(service, "_ALLOW_LOOPBACK_HTTP_AUDIO", True)
    assert service._validate_audio_url("https://127.0.0.1:9/a.mp3")
    for url in ("https://10.0.0.1/a.mp3", "http://192.168.0.1/a.mp3"):
        with pytest.raises(service.SunoDownloadError):
            service._validate_audio_url(url)


def test_s1_redirect_to_private_ip_rejected(tmp_path):
    session = _Session(
        {
            "https://cdn.suno.test/a.mp3": _Resp(
                302, {"Location": "https://169.254.169.254/latest/meta-data"}
            )
        }
    )
    with pytest.raises(service.SunoDownloadError):
        service._download_audio(
            "https://cdn.suno.test/a.mp3", tmp_path, session=session
        )
    assert len(session.calls) == 1 and list(tmp_path.iterdir()) == []


# --- S2: RN08 cancel texts ------------------------------------------------


# --- S3: base64 size checked before decoding ------------------------------


# --- S4: no orphan audio when save_json fails -----------------------------


# --- S5: AUTH_ERROR_CODES imported, not duplicated ------------------------


# --- S6: redirect loop above the limit ------------------------------------
def test_s6_redirect_loop_above_limit_is_rejected(tmp_path):
    responses = {
        f"https://cdn.suno.test/{i}": _Resp(302, {"Location": f"/{i + 1}"})
        for i in range(10)
    }
    session = _Session(responses)
    with pytest.raises(service.SunoDownloadError):
        service._download_audio("https://cdn.suno.test/0", tmp_path, session=session)
    assert len(session.calls) == service._AUDIO_MAX_REDIRECTS + 1 == 4
    assert all(r.closed for r in list(responses.values())[:4])
    assert list(tmp_path.iterdir()) == []


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


# --- S8: download read timeout 30 s ---------------------------------------
def test_s8_download_read_timeout_is_30s(tmp_path):
    assert service._AUDIO_TIMEOUT == (10, 30)
    session = _Session({"https://cdn.suno.test/a.mp3": _ok_resp()})
    service._download_audio("https://cdn.suno.test/a.mp3", tmp_path, session=session)
    assert session.calls[0][1]["timeout"] == (10, 30)


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


# --- 2: short / numeric / hex IPv4 hosts ------------------------------------
@pytest.mark.parametrize(
    "host",
    [
        "127.1",
        "127.0.1",
        "2130706433",
        "0x7f000001",
        "0x7f.0.0.1",
        "0177.0.0.1",
        "017700000001",
        "10.1",
        "127.0.0.1.",
        "1.2.3",
        "[::ffff:127.0.0.1]",
        "[::ffff:a00:1]",
    ],
)
def test_g2_non_canonical_ipv4_hosts_rejected(host):
    with pytest.raises(service.SunoDownloadError):
        service._validate_audio_url(f"https://{host}/a.mp3")


def test_g2_regular_hostnames_still_allowed():
    for url in (
        "https://cdn1.suno.ai/a.mp3",
        "https://a1.b2.example/a.mp3",
        "https://8.8.8.8/a.mp3",
        "https://0x.example.com/a.mp3",
    ):
        assert service._validate_audio_url(url) == url


# --- 3: cancel before the 1st call uses the before-send message -------------


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

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_connectors import ACCOUNT_MODES, MCPConnectorManager, _MemoryVault  # noqa: E402
from src.plugins_catalog import PluginsCatalog  # noqa: E402
from src.skills_catalog import SkillsCatalog  # noqa: E402
from src.workspace_store import WorkspaceStore  # noqa: E402


def _make_manager(tmp_path):
    store = WorkspaceStore(tmp_path / "ws.sqlite3")
    vault = _MemoryVault()
    return MCPConnectorManager(store=store, vault=vault), store, vault


def test_mcp_crud_http_streaming_and_stdio(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    monkeypatch.setenv("MCP_BEARER_TOKEN", "env-secret-999")
    monkeypatch.setenv("X_ORG_ENV", "org-42")

    # Create HTTP Streaming server
    http_srv = mgr.save_server(
        {
            "name": "Documentos",
            "type": "http_streaming",
            "url": "https://mcp.example.com/mcp",
            "bearer_token_env": "MCP_BEARER_TOKEN",
            "bearer_token": "direct-secret-1234",
            "headers": [{"key": "X-Custom", "value": "abc"}],
            "env_headers": [{"key": "X-Org", "value": "X_ORG_ENV"}],
        }
    )
    assert http_srv["transport"] == "http_streaming"
    assert http_srv["has_bearer_token"] is True
    assert http_srv["bearer_token_masked"] == "••••1234"
    assert "direct-secret-1234" not in json.dumps(http_srv)

    headers, _ = mgr._resolve_credentials(http_srv)
    assert headers["Authorization"] == "Bearer direct-secret-1234"
    assert headers["X-Custom"] == "abc"
    assert headers["X-Org"] == "org-42"

    # Create STDIO server
    stdio_srv = mgr.save_server(
        {
            "name": "Local FS",
            "transport": "stdio",
            "command": "npx",
            "args": "-y @modelcontextprotocol/server-filesystem /tmp",
            "cwd": str(tmp_path),
            "env": [{"key": "NODE_ENV", "value": "production"}],
        }
    )
    assert stdio_srv["transport"] == "stdio"
    assert stdio_srv["args"] == [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/tmp",
    ]

    listed = mgr.list_servers()
    assert len(listed) == 2

    deleted = mgr.delete_server(stdio_srv["id"])
    assert deleted["ok"] is True
    assert len(mgr.list_servers()) == 1


def test_mcp_multi_account_distributed_round_robin_and_fallback(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = mgr.save_server(
        {
            "id": "suno",
            "name": "Suno",
            "transport": "http_streaming",
            "url": "https://suno.example.com/mcp",
            "account_mode": "distributed",
            "accounts": [
                {
                    "id": "acc1",
                    "name": "Suno Conta 1",
                    "bearer_token": "tok-1",
                    "enabled": True,
                },
                {
                    "id": "acc2",
                    "name": "Suno Conta 2",
                    "bearer_token": "tok-2",
                    "enabled": True,
                },
            ],
        }
    )

    used_tokens = []

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        tok = headers.get("Authorization", "")
        used_tokens.append(tok)
        if tok == "Bearer tok-1" and len(used_tokens) == 3:
            raise RuntimeError("Sem créditos na Conta 1")
        return {"ok": True, "used": tok}

    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)

    r1 = mgr.call_tool(srv["id"], "generate_music", {"prompt": "rock"})
    r2 = mgr.call_tool(srv["id"], "generate_music", {"prompt": "jazz"})
    assert r1["used"] == "Bearer tok-1"
    assert r2["used"] == "Bearer tok-2"

    # 3rd call starts on tok-1, fails, and automatically falls back to tok-2
    r3 = mgr.call_tool(srv["id"], "generate_music", {"prompt": "lo-fi"})
    assert r3["used"] == "Bearer tok-2"


def test_mcp_multi_account_incremental_aggregates_all(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = mgr.save_server(
        {
            "id": "dropbox",
            "name": "Dropbox",
            "transport": "http_streaming",
            "url": "https://dropbox.example.com/mcp",
            "account_mode": "incremental",
            "accounts": [
                {
                    "id": "pessoal",
                    "name": "Dropbox Pessoal",
                    "context": "pessoal",
                    "bearer_token": "db-p",
                },
                {
                    "id": "trabalho",
                    "name": "Dropbox Trabalho",
                    "context": "trabalho",
                    "bearer_token": "db-t",
                },
            ],
        }
    )

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        tok = headers.get("Authorization")
        return {"files": ["foto.png"] if tok == "Bearer db-p" else ["contrato.pdf"]}

    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)
    res = mgr.call_tool(srv["id"], "list_files", {"path": "/"})
    assert res["mode"] == "incremental"
    assert len(res["results"]) == 2
    assert res["results"][0]["account_name"] == "Dropbox Pessoal"
    assert res["results"][0]["result"]["files"] == ["foto.png"]
    assert res["results"][1]["account_name"] == "Dropbox Trabalho"
    assert res["results"][1]["result"]["files"] == ["contrato.pdf"]


def test_mcp_multi_account_alternating_context(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = mgr.save_server(
        {
            "id": "drive_mcp",
            "name": "Drive MCP",
            "transport": "http_streaming",
            "url": "https://drive.example.com/mcp",
            "account_mode": "alternating",
            "active_context": "trabalho",
            "accounts": [
                {
                    "id": "a_pessoal",
                    "name": "Pessoal",
                    "context": "pessoal",
                    "bearer_token": "tok-p",
                },
                {
                    "id": "a_trabalho",
                    "name": "Trabalho",
                    "context": "trabalho",
                    "bearer_token": "tok-t",
                },
            ],
        }
    )

    seen = []

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        seen.append(headers.get("Authorization"))
        return {"ok": True}

    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)
    mgr.call_tool(srv["id"], "list_files", {})
    mgr.call_tool(srv["id"], "list_files", {"_account_context": "pessoal"})
    assert seen == ["Bearer tok-t", "Bearer tok-p"]


def test_mcp_oauth_and_inspect_tools(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = mgr.save_server(
        {
            "id": "dropbox_oauth",
            "name": "Dropbox",
            "transport": "http_streaming",
            "url": "https://dropbox.example.com/mcp",
            "accounts": [{"id": "acc1", "name": "Conta Principal"}],
        }
    )
    start = mgr.start_oauth(
        srv["id"],
        account_id="acc1",
        payload={
            "client_id": "cid-123",
            "auth_url": "https://www.dropbox.com/oauth2/authorize",
            "redirect_uri": "http://127.0.0.1:8762/oauth/cb",
        },
    )
    assert start["ok"] is True
    assert "client_id=cid-123" in start["auth_url"]

    cb = mgr.complete_oauth(
        srv["id"],
        payload={"state": start["state"], "access_token": "oauth-secret-5678"},
    )
    assert cb["ok"] is True
    assert cb["account"]["oauth"]["connected"] is True
    assert cb["account"]["oauth"]["token_masked"] == "••••5678"

    # Offline inspect falls back to known tools catalog for Dropbox
    monkeypatch.setattr(
        mgr,
        "_rpc_http",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("timeout")),
    )
    inspected = mgr.inspect_server(srv["id"])
    assert inspected["status"] == "offline"
    assert inspected["connection_error"] == "timeout"
    assert any(t["name"] == "list_files" for t in inspected["tools"])


def test_plugins_and_skills_catalog_and_dispatch(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "ws.sqlite3")
    plugins_cat = PluginsCatalog(root=ROOT / "Plugins", store=store)
    plugins = plugins_cat.list_plugins()
    assert any(p["id"] == "music" for p in plugins)

    toggled = plugins_cat.toggle_plugin("music", False)
    assert toggled["plugin"]["enabled"] is False
    assert (
        next(p for p in plugins_cat.list_plugins() if p["id"] == "music")["enabled"]
        is False
    )

    skills_cat = SkillsCatalog(root=ROOT / "Plugins" / "Skills", store=store)
    skills = skills_cat.list_skills()
    notepad = next(s for s in skills if s["id"] == "abrir_bloco_de_notas")
    assert notepad["name"] == "Iniciar Bloco de Notas"
    assert notepad["command"] == "notepad.exe"
    assert "iniciar bloco de notas" in notepad["triggers"]

    launched = []
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda args: launched.append(args) or SimpleNamespace(pid=123),
    )
    exec_res = skills_cat.execute_skill("abrir_bloco_de_notas")
    assert exec_res["ok"] is True
    assert launched == [["notepad.exe"]]

    created = skills_cat.create_skill(
        {
            "name": "Abrir Terminal",
            "description": "Abre o PowerShell",
            "triggers": ["abrir terminal"],
            "action_type": "command",
            "command": "pwsh.exe",
        }
    )
    assert created["builtin"] is False
    updated = skills_cat.update_skill(
        created["id"], {"description": "Abre PowerShell 7"}
    )
    assert updated["description"] == "Abre PowerShell 7"
    assert skills_cat.delete_skill(created["id"])["ok"] is True
    assert len(ACCOUNT_MODES) == 3


def test_suno_mcp_oauth_persistence_and_usage(tmp_path, monkeypatch):
    from Plugins.Apps.music import service as music_service
    from Plugins.Apps.music.tools import call_suno_mcp
    from src import mcp_connectors, settings_store
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    db_path = tmp_path / "settings.sqlite3"
    sstore = settings_store.SettingsStore(path=db_path)
    monkeypatch.setattr(settings_store, "_store", sstore)

    vault = MemoryVault()
    wstore = WorkspaceStore(tmp_path / "ws.sqlite3")
    mgr = mcp_connectors.MCPConnectorManager(store=wstore, vault=vault)
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)

    cat = music_service.select_provider(
        provider="suno_mcp",
        suno_mcp_url="https://suno.example.com/mcp",
        suno_mcp_auth_type="oauth",
        suno_mcp_client_id="suno-cid",
        suno_mcp_client_secret="suno-csecret",
        suno_mcp_auth_url="https://suno.example.com/oauth/authorize",
        suno_mcp_token_url="https://suno.example.com/oauth/token",
        suno_mcp_scopes="music.generate",
    )
    assert cat["selection"]["provider"] == "suno_mcp"
    assert cat["selection"]["suno_mcp_auth_type"] == "oauth"
    assert cat["selection"]["suno_mcp_oauth_client_id"] == "suno-cid"

    start = music_service.suno_oauth_start(
        {"redirect_uri": "http://127.0.0.1:8762/oauth/cb"}
    )
    assert start["ok"] is True
    assert "client_id=suno-cid" in start["auth_url"]

    seen_token_post = {}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
            self.content = b"{}"
            self.headers = {"Content-Type": "application/json"}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        if url == "https://suno.example.com/oauth/token":
            seen_token_post["url"] = url
            seen_token_post["data"] = kwargs.get("data")
            return FakeResp(
                {
                    "access_token": "suno-oauth-access-9999",
                    "refresh_token": "suno-oauth-refresh-1111",
                }
            )
        seen_token_post["mcp_headers"] = kwargs.get("headers")
        return FakeResp(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"audio_url": "https://cdn.example.com/a.mp3"},
            }
        )

    monkeypatch.setattr("requests.post", fake_post)

    cb = music_service.suno_oauth_callback(
        {"state": start["state"], "code": "auth-code-xyz"}
    )
    assert cb["ok"] is True
    assert cb["account"]["oauth"]["connected"] is True
    assert seen_token_post["data"]["grant_type"] == "authorization_code"
    assert seen_token_post["data"]["code"] == "auth-code-xyz"
    assert seen_token_post["data"]["client_secret"] == "suno-csecret"

    # Stored in UnifiedVault and exposed in catalog
    assert (
        vault.get("mcp:connector:suno_mcp:default:oauth_access_token")
        == "suno-oauth-access-9999"
    )
    cat2 = music_service.providers_catalog()
    assert cat2["selection"]["suno_mcp_oauth_connected"] is True
    assert cat2["selection"]["suno_mcp_token_configured"] is True

    # call_suno_mcp automatically resolves OAuth token from UnifiedVault
    res = call_suno_mcp("Lo-fi chill beat", suno_url="https://suno.example.com/mcp")
    assert res["audio_url"] == "https://cdn.example.com/a.mp3"
    assert (
        seen_token_post["mcp_headers"]["Authorization"]
        == "Bearer suno-oauth-access-9999"
    )

    # Preserves secondary accounts when updating Suno OAuth
    mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno (MCP)",
            "transport": "http_streaming",
            "url": "https://suno.example.com/mcp",
            "accounts": [
                mgr.get_server("suno_mcp")["accounts"][0],
                {"id": "secondary", "name": "Conta Extra", "auth_type": "bearer"},
            ],
        },
        server_id="suno_mcp",
    )
    music_service.select_provider(suno_mcp_scopes="music.generate music.read")
    srv_after = mgr.get_server("suno_mcp")
    assert [a["id"] for a in srv_after["accounts"]] == ["default", "secondary"]

    # Empty access_token response from token_url must fail and not mark connected=True
    music_service.suno_oauth_disconnect()
    assert (
        music_service.providers_catalog()["selection"]["suno_mcp_oauth_connected"]
        is False
    )
    monkeypatch.setattr("requests.post", lambda url, **kw: FakeResp({}))
    start_bad = music_service.suno_oauth_start({"account_id": "default"})
    with pytest.raises(ValueError, match="access_token"):
        music_service.suno_oauth_callback(
            {"state": start_bad["state"], "account_id": "default", "code": "bad-code"}
        )
    assert (
        music_service.providers_catalog()["selection"]["suno_mcp_oauth_connected"]
        is False
    )

    # Unknown explicit account_id in _ensure_suno_mcp_server must fail without modifying existing accounts
    with pytest.raises(ValueError, match="missing"):
        music_service._ensure_suno_mcp_server(
            oauth_payload={"account_id": "missing", "client_id": "new"}
        )
    srv_unchanged = mgr.get_server("suno_mcp")
    assert srv_unchanged["accounts"][0]["oauth"]["client_id"] == "suno-cid"
    assert [a["id"] for a in srv_unchanged["accounts"]] == ["default", "secondary"]

    # complete_oauth with code and no token_url must reject without marking connected=True
    mgr.save_server(
        {
            "id": "no_token_url_srv",
            "name": "No Token URL",
            "transport": "http_streaming",
            "url": "https://notoken.example.com/mcp",
            "accounts": [{"id": "acc1", "name": "Acc 1", "auth_type": "oauth"}],
        }
    )
    start_notok = mgr.start_oauth("no_token_url_srv", account_id="acc1")
    with pytest.raises(ValueError, match="token_url"):
        mgr.complete_oauth(
            "no_token_url_srv",
            payload={
                "state": start_notok["state"],
                "account_id": "acc1",
                "code": "synthetic-code",
            },
        )
    no_tok_acc = mgr.get_server("no_token_url_srv")["accounts"][0]
    assert no_tok_acc["oauth"]["connected"] is False
    assert vault.get("mcp:connector:no_token_url_srv:acc1:oauth_access_token") is None


def test_suno_mcp_dcr_pkce_and_no_false_positive_token(tmp_path, monkeypatch):
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlsplit
    from Plugins.Apps.music import service as music_service
    from src import mcp_connectors, settings_store
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    vault = MemoryVault()
    sstore = settings_store.SettingsStore(
        path=tmp_path / "settings.sqlite3", vault=vault
    )
    monkeypatch.setattr(settings_store, "_store", sstore)
    wstore = WorkspaceStore(tmp_path / "ws.sqlite3")
    mgr = mcp_connectors.MCPConnectorManager(store=wstore, vault=vault)
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)

    # Selecting Suno URL without token or OAuth must NOT report connected/token_configured
    cat0 = music_service.select_provider(
        provider="suno_mcp",
        suno_mcp_url="https://api.suno.com/mcp",
        suno_mcp_token="",
    )
    suno_item = next(p for p in cat0["providers"] if p["id"] == "suno_mcp")
    assert suno_item["token_configured"] is False
    assert suno_item["credential_state"] == "missing"
    assert cat0["selection"]["suno_mcp_token_configured"] is False
    assert cat0["selection"]["suno_mcp_oauth_connected"] is False

    # Stale connected=True without vault secret must not cause false positive
    raw_servers = mgr._raw_servers()
    raw_servers[0]["accounts"] = [
        {"id": "default", "name": "Suno", "oauth": {"connected": True}}
    ]
    mgr._save_raw_servers(raw_servers)
    assert mgr.get_server("suno_mcp")["accounts"][0]["oauth"]["connected"] is False
    assert (
        music_service.providers_catalog()["selection"]["suno_mcp_oauth_connected"]
        is False
    )

    # DCR + PKCE S256 in suno_oauth_start when client_id is empty
    seen = {}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
            self.content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        if url == mcp_connectors.SUNO_OAUTH_DEFAULTS["register_url"]:
            seen["dcr_json"] = kwargs.get("json")
            return FakeResp({"client_id": "dcr--official-test-id"})
        if url == mcp_connectors.SUNO_OAUTH_DEFAULTS["token_url"]:
            seen["token_data"] = kwargs.get("data")
            return FakeResp(
                {"access_token": "suno-pkce-token-42", "refresh_token": "ref-42"}
            )
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr("requests.post", fake_post)

    start = music_service.suno_oauth_start({})
    assert start["ok"] is True
    assert seen["dcr_json"] == {
        "client_name": "pia.travelrpg.com",
        "redirect_uris": ["https://pia.travelrpg.com/oauth/callback"],
    }
    parsed = urlsplit(start["auth_url"])
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == "https://studio-api-prod.suno.com/api/v2/external/oauth/authorize/"
    )
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["dcr--official-test-id"]
    assert qs["redirect_uri"] == ["https://pia.travelrpg.com/oauth/callback"]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["scope"] == [mcp_connectors.SUNO_OAUTH_DEFAULTS["scopes"]]
    challenge = qs["code_challenge"][0]

    # Callback exchanges code + code_verifier + redirect_uri and persists token in vault
    cb = music_service.suno_oauth_callback(
        {"state": start["state"], "code": "suno-auth-code-1"}
    )
    assert cb["ok"] is True
    assert cb["account"]["oauth"]["connected"] is True
    assert seen["token_data"]["grant_type"] == "authorization_code"
    assert seen["token_data"]["code"] == "suno-auth-code-1"
    assert seen["token_data"]["client_id"] == "dcr--official-test-id"
    assert (
        seen["token_data"]["redirect_uri"] == "https://pia.travelrpg.com/oauth/callback"
    )
    verifier = seen["token_data"]["code_verifier"]
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert expected_challenge == challenge
    assert (
        vault.get("mcp:connector:suno_mcp:default:oauth_access_token")
        == "suno-pkce-token-42"
    )

    # Security checks: _is_suno_server restricts to exact ID or api.suno.com hostname
    assert (
        mcp_connectors._is_suno_server("suno_mcp", {"url": "https://other.test"})
        is True
    )
    assert (
        mcp_connectors._is_suno_server("custom", {"url": "https://api.suno.com/mcp"})
        is True
    )
    assert (
        mcp_connectors._is_suno_server(
            "my-suno-clone",
            {"name": "Suno Clone", "url": "https://evil.example.com/mcp"},
        )
        is False
    )

    # Reusing the same state (single-use) or missing/invalid/expired/mismatched state must fail
    with pytest.raises(ValueError, match="State OAuth"):
        music_service.suno_oauth_callback({"state": start["state"], "code": "replay"})
    with pytest.raises(ValueError, match="State OAuth"):
        music_service.suno_oauth_callback({"code": "missing-state"})

    start2 = music_service.suno_oauth_start({"account_id": "default"})
    with pytest.raises(ValueError, match="servidor"):
        mgr.complete_oauth("other_srv", payload={"state": start2["state"], "code": "c"})

    start3 = music_service.suno_oauth_start({"account_id": "default"})
    with pytest.raises(ValueError, match="conta"):
        mgr.complete_oauth(
            "suno_mcp",
            payload={"state": start3["state"], "account_id": "wrong_acc", "code": "c"},
        )

    # Expired state is rejected
    start4 = music_service.suno_oauth_start({"account_id": "default"})
    states_map = wstore.get(mcp_connectors.OAUTH_STATE_KEY, {})
    states_map[start4["state"]]["created_at"] = "2020-01-01T00:00:00+00:00"
    wstore.set(mcp_connectors.OAUTH_STATE_KEY, states_map)
    with pytest.raises(ValueError, match="expirado"):
        music_service.suno_oauth_callback({"state": start4["state"], "code": "c"})

    # Attacker-supplied code_verifier in payload must NOT override state's stored code_verifier
    start5 = music_service.suno_oauth_start({"account_id": "default"})
    cb5 = music_service.suno_oauth_callback(
        {
            "state": start5["state"],
            "code": "suno-auth-code-5",
            "code_verifier": "attacker-verifier-override",
        }
    )
    assert cb5["ok"] is True
    assert seen["token_data"]["code_verifier"] != "attacker-verifier-override"


# --- T2: handshake Streamable HTTP, timeout configurável e fallback de contas ---


class _HandshakeResp:
    def __init__(self, status=200, payload=None, headers=None):
        import requests

        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = requests.structures.CaseInsensitiveDict(
            {"Content-Type": "application/json", **(headers or {})}
        )
        self.text = json.dumps(self._payload)
        self.content = self.text.encode()

    def json(self):
        return self._payload

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


def _fake_mcp_server(monkeypatch, *, session_id="sess-1", init_status=200, plan=None):
    """Fake Streamable HTTP server. ``plan`` maps method -> list of statuses."""
    calls = []
    plan = {k: list(v) for k, v in (plan or {}).items()}
    counter = {"init": 0}

    def fake_post(url, **kwargs):
        body = kwargs.get("json") or {}
        method = body.get("method")
        calls.append(
            {
                "method": method,
                "headers": dict(kwargs.get("headers") or {}),
                "timeout": kwargs.get("timeout"),
            }
        )
        if method == "initialize":
            counter["init"] += 1
            sid = f"{session_id}-{counter['init']}" if session_id else ""
            return _HandshakeResp(
                init_status,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"protocolVersion": "2025-11-25"},
                },
                {"Mcp-Session-Id": sid} if sid else {},
            )
        if method == "notifications/initialized":
            return _HandshakeResp(202, {})
        statuses = plan.get(method) or [200]
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        plan[method] = statuses
        return _HandshakeResp(
            status,
            {"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}},
        )

    monkeypatch.setattr("requests.post", fake_post)
    return calls


def _http_server(mgr, **extra):
    return mgr.save_server(
        {
            "id": "hs",
            "name": "HS",
            "transport": "http_streaming",
            "url": "https://mcp.example.com/mcp",
            "bearer_token": "hs-secret-token",
            **extra,
        }
    )


def test_http_handshake_initialize_and_session_header(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = _http_server(mgr)
    calls = _fake_mcp_server(monkeypatch)
    assert mgr.call_tool(srv["id"], "do", {"a": 1}) == {"ok": True}
    assert [c["method"] for c in calls] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert "Mcp-Session-Id" not in calls[0]["headers"]
    for call in calls[1:]:
        assert call["headers"]["Mcp-Session-Id"] == "sess-1-1"
        assert call["headers"]["MCP-Protocol-Version"] == "2025-11-25"
        assert call["headers"]["Authorization"] == "Bearer hs-secret-token"
    # Sessão reaproveitada na próxima chamada (sem novo initialize)
    mgr.call_tool(srv["id"], "do", {})
    assert [c["method"] for c in calls[3:]] == ["tools/call"]
    assert calls[3]["headers"]["Mcp-Session-Id"] == "sess-1-1"
    # Segredo nunca entra na chave do cache de sessão
    assert "hs-secret-token" not in json.dumps(list(mgr._http_sessions))


def test_http_handshake_reinitializes_once_on_expired_session(tmp_path, monkeypatch):
    import requests

    mgr, _, _ = _make_manager(tmp_path)
    srv = _http_server(mgr)
    calls = _fake_mcp_server(monkeypatch, plan={"tools/call": [404, 200]})
    assert mgr.call_tool(srv["id"], "do", {}) == {"ok": True}
    methods = [c["method"] for c in calls]
    assert methods.count("initialize") == 2
    assert methods.count("tools/call") == 2
    assert calls[-1]["headers"]["Mcp-Session-Id"] == "sess-1-2"

    calls.clear()
    mgr2, _, _ = _make_manager(tmp_path / "b")
    srv2 = _http_server(mgr2)
    calls = _fake_mcp_server(monkeypatch, plan={"tools/call": [404, 404, 404]})
    with pytest.raises(requests.HTTPError):
        mgr2.call_tool(srv2["id"], "do", {})
    assert [c["method"] for c in calls].count("tools/call") == 2  # só 1 retry


def test_http_handshake_stateless_servers(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = _http_server(mgr)
    # Servidor que responde initialize sem Mcp-Session-Id
    calls = _fake_mcp_server(monkeypatch, session_id="")
    mgr.call_tool(srv["id"], "do", {})
    assert "Mcp-Session-Id" not in calls[-1]["headers"]
    assert calls[-1]["method"] == "tools/call"

    # Servidor legado que rejeita initialize com 405: segue sem sessão
    mgr2, _, _ = _make_manager(tmp_path / "b")
    srv2 = _http_server(mgr2)
    calls2 = _fake_mcp_server(monkeypatch, init_status=405)
    assert mgr2.call_tool(srv2["id"], "do", {}) == {"ok": True}
    assert [c["method"] for c in calls2] == ["initialize", "tools/call"]
    assert "Mcp-Session-Id" not in calls2[-1]["headers"]


def test_http_handshake_auth_error_propagates(tmp_path, monkeypatch):
    import requests

    mgr, _, _ = _make_manager(tmp_path)
    srv = _http_server(mgr)
    calls = _fake_mcp_server(monkeypatch, init_status=401)
    with pytest.raises(requests.HTTPError):
        mgr.call_tool(srv["id"], "do", {})
    assert [c["method"] for c in calls] == ["initialize"]


def test_call_tool_timeout_is_configurable(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = _http_server(mgr)
    calls = _fake_mcp_server(monkeypatch)
    mgr.call_tool(srv["id"], "do", {}, timeout=420)
    assert calls[0]["timeout"] == 30  # handshake limitado a 30 s
    assert calls[-1]["timeout"] == 420
    mgr.call_tool(srv["id"], "do", {})
    assert calls[-1]["timeout"] == 30  # padrão preservado

    seen = []

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        seen.append(timeout)
        return {"ok": True}

    srv_acc = mgr.save_server(
        {
            "id": "acc-srv",
            "name": "Acc",
            "url": "https://mcp.example.com/mcp",
            "account_mode": "alternating",
            "accounts": [{"id": "x", "name": "X", "bearer_token": "t"}],
        }
    )
    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)
    mgr.call_tool(srv_acc["id"], "do", {}, timeout=99)
    assert seen == [99]


def test_call_tool_can_disable_account_fallback(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = mgr.save_server(
        {
            "id": "multi",
            "name": "Multi",
            "url": "https://mcp.example.com/mcp",
            "account_mode": "distributed",
            "accounts": [
                {"id": "acc1", "name": "1", "bearer_token": "tok-1"},
                {"id": "acc2", "name": "2", "bearer_token": "tok-2"},
            ],
        }
    )
    used = []

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        used.append(headers.get("Authorization"))
        raise RuntimeError("falhou")

    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)
    with pytest.raises(RuntimeError):
        mgr.call_tool(srv["id"], "paid", {}, retry_other_accounts=False)
    assert used == ["Bearer tok-1"]


def test_list_tools_caches_and_raises(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = _http_server(mgr)

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        assert method == "tools/list"
        return {"tools": [{"name": "make_song", "inputSchema": {"type": "object"}}]}

    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)
    tools = mgr.list_tools(srv["id"], timeout=12)
    assert [t["name"] for t in tools] == ["make_song"]
    assert mgr._find_raw(srv["id"])["cached_tools"][0]["name"] == "make_song"

    def broken(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(mgr, "_rpc_http", broken)
    with pytest.raises(RuntimeError):
        mgr.list_tools(srv["id"])


# --- Review T1/T2: itens 3, 4, 5, 6 e 11 ---


def _http_401(token):
    import requests

    resp = requests.Response()
    resp.status_code = 401
    return requests.HTTPError(
        f"401 Client Error: Unauthorized for url: "
        f"https://api.suno.com/mcp?access_token={token}&x=1 Bearer {token}",
        response=resp,
    )


def test_safe_error_masks_urls_and_secrets():
    from src.mcp_connectors import redact_error_text, safe_error

    code, msg = safe_error(_http_401("seg-123"))
    assert code == "401"
    assert "seg-123" not in msg
    assert "https://api.suno.com/mcp" in msg
    assert "?" not in msg
    assert "token=••••" in redact_error_text("falhou token=abc&sig=def")
    assert "abc" not in redact_error_text("falhou token=abc&sig=def")
    import requests

    assert safe_error(requests.Timeout("t"))[0] == "timeout"
    assert safe_error(requests.ConnectionError("c"))[0] == "connection"
    assert safe_error(RuntimeError("x"))[0] == "RuntimeError"


def test_call_tool_records_safe_last_error_code(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    srv = mgr.save_server(
        {
            "id": "s",
            "name": "S",
            "url": "https://api.suno.com/mcp",
            "accounts": [{"id": "a1", "name": "A1", "bearer_token": "tok"}],
        }
    )

    def boom(*args, **kwargs):
        raise _http_401("vazou-999")

    monkeypatch.setattr(mgr, "_rpc_http", boom)
    with pytest.raises(Exception):
        mgr.call_tool(srv["id"], "x", {})
    acc = mgr._find_raw("s")["accounts"][0]
    assert acc["last_error_code"] == "401"
    assert "vazou-999" not in json.dumps(mgr._raw_servers())

    # Sem contas: o erro fica no servidor, também sem segredo
    mgr.save_server(
        {"id": "s2", "name": "S2", "url": "https://x.test/mcp", "bearer_token": "b"}
    )
    with pytest.raises(Exception):
        mgr.call_tool("s2", "x", {})
    raw = mgr._find_raw("s2")
    assert raw["last_error_code"] == "401"
    assert "vazou-999" not in raw["last_error"]

    # Incremental devolve o erro limpo
    mgr.save_server(
        {
            "id": "inc",
            "name": "Inc",
            "url": "https://x.test/mcp",
            "account_mode": "incremental",
            "accounts": [{"id": "a", "name": "A", "bearer_token": "t"}],
        }
    )
    res = mgr.call_tool("inc", "x", {})
    assert "vazou-999" not in json.dumps(res)


def test_save_server_preserves_last_error_until_new_credential(tmp_path):
    mgr, _, _ = _make_manager(tmp_path)
    mgr.save_server(
        {"id": "s", "name": "S", "url": "https://x.test", "bearer_token": "b1"}
    )
    servers = mgr._raw_servers()
    servers[0]["last_error"] = "401 Error"
    servers[0]["last_error_code"] = "401"
    mgr._save_raw_servers(servers)
    mgr.save_server({"id": "s", "name": "S renomeado"}, server_id="s")
    assert mgr._find_raw("s")["last_error_code"] == "401"
    mgr.save_server({"id": "s", "bearer_token": "b2"}, server_id="s")
    assert mgr._find_raw("s")["last_error_code"] is None

    # Conta: idem
    mgr.save_server(
        {
            "id": "c",
            "name": "C",
            "url": "https://x.test",
            "accounts": [{"id": "a", "name": "A", "bearer_token": "t1"}],
        }
    )
    servers = mgr._raw_servers()
    acc = next(s for s in servers if s["id"] == "c")["accounts"][0]
    acc["last_error_code"] = "401"
    mgr._save_raw_servers(servers)
    mgr.save_server({"id": "c", "accounts": [{"id": "a", "name": "A"}]}, server_id="c")
    assert mgr._find_raw("c")["accounts"][0]["last_error_code"] == "401"
    mgr.save_server(
        {"id": "c", "accounts": [{"id": "a", "name": "A", "bearer_token": "t2"}]},
        server_id="c",
    )
    assert mgr._find_raw("c")["accounts"][0]["last_error_code"] is None


def test_list_tools_records_and_clears_errors(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    mgr.save_server(
        {
            "id": "s",
            "name": "S",
            "url": "https://x.test",
            "accounts": [{"id": "a", "name": "A", "bearer_token": "t"}],
        }
    )

    def boom(*args, **kwargs):
        raise _http_401("tk")

    monkeypatch.setattr(mgr, "_rpc_http", boom)
    with pytest.raises(Exception):
        mgr.list_tools("s")
    assert mgr._find_raw("s")["accounts"][0]["last_error_code"] == "401"
    monkeypatch.setattr(mgr, "_rpc_http", lambda *a, **k: {"tools": []})
    assert mgr.list_tools("s") == []
    assert mgr._find_raw("s")["accounts"][0]["last_error_code"] is None


def _two_account_server(mgr, mode):
    return mgr.save_server(
        {
            "id": mode,
            "name": mode,
            "url": "https://x.test/mcp",
            "account_mode": mode,
            "accounts": [
                {"id": "acc1", "name": "1", "bearer_token": "tok-1"},
                {"id": "acc2", "name": "2", "bearer_token": "tok-2"},
            ],
        }
    )


def test_single_account_in_any_mode_and_pinning(tmp_path, monkeypatch):
    mgr, _, _ = _make_manager(tmp_path)
    used = []

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        used.append(headers.get("Authorization"))
        return {"ok": True}

    monkeypatch.setattr(mgr, "_rpc_http", fake_rpc)

    _two_account_server(mgr, "incremental")
    res = mgr.call_tool("incremental", "paid", {}, retry_other_accounts=False)
    assert res == {"ok": True}
    assert used == ["Bearer tok-1"]  # sem fan-out

    used.clear()
    _two_account_server(mgr, "distributed")
    chosen = mgr.select_account("distributed")
    assert chosen == "acc1"
    cursor = mgr._find_raw("distributed")["rr_cursor"]
    for _ in range(3):  # geração + polling na mesma conta, sem girar o cursor
        mgr.call_tool("distributed", "x", {}, account_id=chosen)
    assert used == ["Bearer tok-1"] * 3
    assert mgr._find_raw("distributed")["rr_cursor"] == cursor
    assert mgr.select_account("distributed") == "acc2"

    used.clear()
    mgr.list_tools("distributed", account_id="acc2")
    assert used == ["Bearer tok-2"]
    with pytest.raises(KeyError):
        mgr.call_tool("distributed", "x", {}, account_id="nao-existe")

    _two_account_server(mgr, "alternating")
    assert mgr.select_account("alternating") == "acc1"


def test_select_account_without_accounts_returns_none(tmp_path):
    mgr, _, _ = _make_manager(tmp_path)
    mgr.save_server(
        {"id": "s", "name": "S", "url": "https://x.test", "bearer_token": "b"}
    )
    assert mgr.select_account("s") is None


def test_stateless_initialize_logs_debug_without_secret(tmp_path, monkeypatch, caplog):
    import logging

    mgr, _, _ = _make_manager(tmp_path)
    mgr.save_server(
        {
            "id": "hs",
            "name": "HS",
            "url": "https://mcp.example.com/mcp?api_key=segredo-77",
            "bearer_token": "hs-secret-token",
        }
    )
    _fake_mcp_server(monkeypatch, init_status=400)
    with caplog.at_level(logging.DEBUG, logger="src.mcp_connectors"):
        mgr.call_tool("hs", "do", {})
    text = caplog.text
    assert "HTTP 400" in text
    assert "https://mcp.example.com/mcp" in text
    assert "segredo-77" not in text
    assert "hs-secret-token" not in text

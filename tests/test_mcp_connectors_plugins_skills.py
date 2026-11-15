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

    sstore = settings_store.SettingsStore(path=tmp_path / "settings.sqlite3")
    monkeypatch.setattr(settings_store, "_store", sstore)
    vault = MemoryVault()
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

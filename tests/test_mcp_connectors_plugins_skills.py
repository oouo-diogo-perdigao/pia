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

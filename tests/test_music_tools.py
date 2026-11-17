import json
from types import SimpleNamespace
import pytest
from Plugins.Apps.music import service
from src import tool_registry


def test_music_rejects_invalid_inputs_before_network():
    for data in (
        {"prompt": ""},
        {"prompt": "song", "duration": True},
        {"prompt": "song", "provider": "flow"},
        {"prompt": "song", "duration": 181},
    ):
        with pytest.raises(ValueError):
            service.generate(**data)


def test_music_only_loopback(monkeypatch):
    for url in (
        "https://example.com",
        "http://127.0.0.1/other",
        "http://user@localhost",
    ):
        monkeypatch.setattr(service, "settings", lambda: {"MUSIC_LOCAL_URL": url})
        with pytest.raises(ValueError):
            service.base_url()


def test_local_music_polls_and_saves(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "settings", lambda: {})

    class Response:
        status_code = 200
        content = b"fake mp3 bytes"

        def __init__(self, data=None):
            self.data = data

        def json(self):
            return self.data

        def close(self):
            pass

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            if url.endswith("/release_task"):
                assert kwargs["json"]["audio_duration"] == 30
                return Response({"data": {"task_id": "one"}})
            return Response(
                {
                    "data": [
                        {
                            "status": 1,
                            "result": json.dumps([{"file": "/v1/audio?path=test.mp3"}]),
                        }
                    ]
                }
            )

        def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(service, "OUTPUT", tmp_path)
    monkeypatch.setattr(service.requests, "Session", Session)
    monkeypatch.setattr(service, "engine", lambda *args: ("http://127.0.0.1:8015", {}))
    result = service.generate("piano")
    assert service.audio_file(result["file"]).read_bytes() == b"fake mp3 bytes"
    assert result["requested_duration"] == 30
    assert json.loads((tmp_path / (result["file"] + ".json")).read_text()) == result


def test_music_cancellation_releases_lock():
    with pytest.raises(InterruptedError):
        service.generate("piano", cancelled=lambda: True)
    assert not service._generation_lock.locked()


def test_registry_rejects_extra_arguments():
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        tool_registry.call("pia_camera", {"shell": "bad"})


def test_tool_loop_uses_results_and_allowlist(monkeypatch):
    class Message:
        content = "Finished"
        tool_calls = None

        def model_dump(self, **kwargs):
            return {"role": "assistant", "tool_calls": []}

    first = Message()
    first.tool_calls = [
        SimpleNamespace(
            id="t", function=SimpleNamespace(name="pia_accounts", arguments="{}")
        )
    ]
    responses = iter([first, Message()])

    class Agent:
        def complete(self, history, **kwargs):
            if len(history) > 1:
                assert history[-1]["role"] == "tool"
            return SimpleNamespace(choices=[SimpleNamespace(message=next(responses))])

    monkeypatch.setattr(tool_registry, "call", lambda *args: [{"id": "account"}])
    assert (
        tool_registry.complete_with_tools(
            Agent(), [{"role": "user", "content": "accounts"}], allowed=["pia_accounts"]
        )
        == "Finished"
    )
    responses = iter([first])
    with pytest.raises(ValueError):
        tool_registry.complete_with_tools(Agent(), [], allowed=["pia_music"])


# --- T1: suno_status() / disponibilidade única do Suno (RN01, CA01, CA02, CA10) ---

PLANTED_SECRETS = (
    "planted-oauth-access-XYZ",
    "planted-bearer-ABC",
    "planted-settings-token-123",
    "planted-env-secret-777",
    "planted-client-secret-000",
)


@pytest.fixture
def suno_env(tmp_path, monkeypatch):
    from src import mcp_connectors
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    vault = MemoryVault()
    mgr = mcp_connectors.MCPConnectorManager(
        store=WorkspaceStore(tmp_path / "ws.sqlite3"), vault=vault
    )
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)
    cfg = {}
    monkeypatch.setattr(service, "settings", lambda: dict(cfg))

    def connect_oauth(server_id, acc_id="default", token=PLANTED_SECRETS[0]):
        servers = mgr._raw_servers()
        for srv in servers:
            if srv["id"] == server_id:
                for acc in srv.get("accounts") or []:
                    if acc["id"] == acc_id:
                        acc.setdefault("oauth", {})["connected"] = True
        mgr._save_raw_servers(servers)
        mgr._set_secret(server_id, acc_id, "oauth_access_token", token)

    return SimpleNamespace(mgr=mgr, vault=vault, cfg=cfg, connect_oauth=connect_oauth)


def _suno_item(catalog):
    return next(p for p in catalog["providers"] if p["id"] == "suno_mcp")


def _oauth_server(mgr, server_id="suno_mcp", url="https://api.suno.com/mcp", **extra):
    return mgr.save_server(
        {
            "id": server_id,
            "name": "Suno",
            "transport": "http_streaming",
            "url": url,
            "accounts": [
                {
                    "id": "default",
                    "name": "Suno OAuth",
                    "auth_type": "oauth",
                    "oauth": {
                        "client_id": "cid",
                        "client_secret": PLANTED_SECRETS[4],
                        "auth_url": "https://studio-api-prod.suno.com/oauth/authorize/",
                        "token_url": "https://studio-api-prod.suno.com/oauth/token/",
                    },
                }
            ],
            **extra,
        },
        server_id=server_id if server_id == "suno_mcp" else None,
    )


def test_suno_status_url_and_oauth_connected_is_available(suno_env):
    # (a) CA01: URL + OAuth conectado
    suno_env.cfg["MUSIC_SUNO_MCP_URL"] = "https://api.suno.com/mcp"
    _oauth_server(suno_env.mgr)
    assert service.suno_status()["available"] is False  # OAuth ainda não concluído
    suno_env.connect_oauth("suno_mcp")
    status = service.suno_status()
    assert status["available"] is True
    assert status["oauth_connected"] is True
    assert status["credential_state"] == "configured"
    assert status["server_id"] == "suno_mcp"
    item = _suno_item(service.providers_catalog())
    assert item["available"] is True
    assert item["label"] == "Suno"
    assert item["endpoint_configured"] is True
    assert item["settings_route"] == {"view": "settings", "section": "Apps/music"}


def test_suno_status_only_url_is_unavailable(suno_env):
    # (b) CA02: só URL (settings) e servidor sem credencial
    suno_env.cfg["MUSIC_SUNO_MCP_URL"] = "https://api.suno.com/mcp"
    item = _suno_item(service.providers_catalog())
    assert item["available"] is False
    assert item["endpoint_configured"] is True
    assert item["credential_state"] == "missing"
    suno_env.mgr.save_server(
        {"id": "suno_mcp", "name": "Suno", "url": "https://api.suno.com/mcp"},
        server_id="suno_mcp",
    )
    item = _suno_item(service.providers_catalog())
    assert item["available"] is False
    assert item["credential_state"] == "missing"


def test_suno_status_only_token_without_endpoint_is_unavailable(suno_env):
    # (c) só token, sem endpoint
    suno_env.cfg["MUSIC_SUNO_MCP_TOKEN"] = PLANTED_SECRETS[2]
    status = service.suno_status()
    assert status["available"] is False
    assert status["endpoint_configured"] is False
    assert status["credential_state"] == "configured"


@pytest.mark.parametrize("server_id", ["suno-oficial", "my_music", "x1"])
def test_suno_status_api_suno_host_any_id_with_bearer(suno_env, server_id):
    # (d) + decisão CEO nº 5: host api.suno.com com qualquer id e credencial válida
    srv = suno_env.mgr.save_server(
        {
            "id": server_id,
            "name": "Suno oficial",
            "url": "https://api.suno.com/mcp",
            "bearer_token": PLANTED_SECRETS[1],
        }
    )
    status = service.suno_status()
    assert status["available"] is True
    assert status["server_id"] == srv["id"]
    assert status["auth_type"] == "bearer"
    assert _suno_item(service.providers_catalog())["server_id"] == srv["id"]


@pytest.mark.parametrize("server_id", ["suno-oficial", "outro"])
def test_suno_status_api_suno_host_any_id_without_credential(suno_env, server_id):
    suno_env.mgr.save_server(
        {"id": server_id, "name": "Suno", "url": "https://api.suno.com/mcp"}
    )
    status = service.suno_status()
    assert status["available"] is False
    assert status["endpoint_configured"] is True
    assert status["credential_state"] == "missing"


def test_suno_status_api_suno_host_any_id_with_oauth(suno_env):
    srv = _oauth_server(suno_env.mgr, server_id="suno-conta-oauth")
    assert service.suno_status()["available"] is False
    suno_env.connect_oauth(srv["id"])
    status = service.suno_status()
    assert status["available"] is True
    assert status["server_id"] == srv["id"]
    assert status["oauth_connected"] is True


def test_suno_status_other_host_is_not_suno(suno_env):
    suno_env.mgr.save_server(
        {
            "id": "musica-x",
            "name": "Outro MCP",
            "url": "https://api.suno.com.evil.test/mcp",
            "bearer_token": PLANTED_SECRETS[1],
        }
    )
    suno_env.mgr.save_server(
        {
            "id": "outro",
            "name": "Outro MCP",
            "url": "https://mcp.example.com/suno",
            "bearer_token": PLANTED_SECRETS[1],
        }
    )
    status = service.suno_status()
    assert status["available"] is False
    assert status["source"] == "none"


def test_suno_status_stdio_command_with_token(suno_env):
    # (e) comando stdio + token
    suno_env.cfg["MUSIC_SUNO_MCP_COMMAND"] = "suno-mcp --stdio"
    suno_env.cfg["MUSIC_SUNO_MCP_TOKEN"] = PLANTED_SECRETS[2]
    status = service.suno_status()
    assert status["available"] is True
    assert status["transport"] == "stdio"
    # Servidor stdio registrado com env var secreta também conta
    suno_env.cfg.clear()
    suno_env.mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "transport": "stdio",
            "command": "suno-mcp",
            "env": [{"key": "SUNO_API_TOKEN", "value": PLANTED_SECRETS[3]}],
        },
        server_id="suno_mcp",
    )
    assert service.suno_status()["available"] is True


def test_suno_status_stdio_env_without_secret_is_not_credential(suno_env):
    suno_env.mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "transport": "stdio",
            "command": "suno-mcp",
            "env": [{"key": "NODE_ENV", "value": "production"}],
        },
        server_id="suno_mcp",
    )
    assert service.suno_status()["available"] is False


def test_suno_status_disabled_server_is_unavailable(suno_env):
    # (f) servidor desabilitado
    suno_env.mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "url": "https://api.suno.com/mcp",
            "bearer_token": PLANTED_SECRETS[1],
            "enabled": False,
        },
        server_id="suno_mcp",
    )
    suno_env.cfg["MUSIC_SUNO_MCP_URL"] = "https://api.suno.com/mcp"
    suno_env.cfg["MUSIC_SUNO_MCP_TOKEN"] = PLANTED_SECRETS[2]
    status = service.suno_status()
    assert status["available"] is False
    assert status["server_enabled"] is False


def test_suno_status_prefers_ready_server(suno_env):
    # suno_mcp sem credencial + outro id em api.suno.com com bearer → usa o pronto
    suno_env.mgr.save_server(
        {"id": "suno_mcp", "name": "Suno", "url": "https://api.suno.com/mcp"},
        server_id="suno_mcp",
    )
    srv = suno_env.mgr.save_server(
        {
            "id": "suno-2",
            "name": "Suno 2",
            "url": "https://api.suno.com/mcp",
            "bearer_token": PLANTED_SECRETS[1],
        }
    )
    status = service.suno_status()
    assert status["available"] is True
    assert status["server_id"] == srv["id"]


def _set_last_error(mgr, server_id, code, acc_index=0):
    servers = mgr._raw_servers()
    srv = next(x for x in servers if x["id"] == server_id)
    target = srv if acc_index is None else srv["accounts"][acc_index]
    target["last_error_code"] = code
    target["last_error"] = f"{code} Error"
    mgr._save_raw_servers(servers)


def _bearer_account_server(mgr, server_id="suno_mcp", accounts=None):
    return mgr.save_server(
        {
            "id": server_id,
            "name": "Suno",
            "url": "https://api.suno.com/mcp",
            "accounts": accounts
            or [{"id": "a1", "name": "A1", "bearer_token": PLANTED_SECRETS[1]}],
        },
        server_id=server_id if server_id == "suno_mcp" else None,
    )


@pytest.mark.parametrize("error", ["401", "403"])
def test_suno_status_expired_credential_is_unavailable(suno_env, error):
    # Decisão TechLead: 401/expirado => available=false + credential_state=expired
    _bearer_account_server(suno_env.mgr)
    assert service.suno_status()["available"] is True
    _set_last_error(suno_env.mgr, "suno_mcp", error)
    status = service.suno_status()
    assert status["credential_state"] == "expired"
    assert status["available"] is False
    item = _suno_item(service.providers_catalog())
    assert item["available"] is False
    assert item["credential_state"] == "expired"


def test_suno_status_non_auth_error_keeps_available(suno_env):
    _bearer_account_server(suno_env.mgr)
    _set_last_error(suno_env.mgr, "suno_mcp", "503")
    status = service.suno_status()
    assert status["available"] is True
    assert status["credential_state"] == "configured"


def test_suno_status_expired_oauth_then_reconnect(suno_env):
    _oauth_server(suno_env.mgr)
    suno_env.connect_oauth("suno_mcp")
    _set_last_error(suno_env.mgr, "suno_mcp", "401")
    assert service.suno_status()["available"] is False
    # Reconectar (novo access_token) limpa o last_error
    suno_env.mgr.start_oauth(
        "suno_mcp", account_id="default", payload={"access_token": "novo-token-1"}
    )
    status = service.suno_status()
    assert status["available"] is True
    assert status["credential_state"] == "configured"


def test_suno_status_expired_bearer_then_new_token(suno_env):
    _bearer_account_server(suno_env.mgr)
    _set_last_error(suno_env.mgr, "suno_mcp", "401")
    assert service.suno_status()["available"] is False
    # Salvar sem token novo mantém expirado; com token novo volta
    _bearer_account_server(suno_env.mgr, accounts=[{"id": "a1", "name": "A1"}])
    assert service.suno_status()["credential_state"] == "expired"
    _bearer_account_server(
        suno_env.mgr,
        accounts=[{"id": "a1", "name": "A1", "bearer_token": "novo-bearer-2"}],
    )
    assert service.suno_status()["available"] is True


def test_suno_status_one_expired_account_other_ok(suno_env):
    _bearer_account_server(
        suno_env.mgr,
        accounts=[
            {"id": "a1", "name": "A1", "bearer_token": PLANTED_SECRETS[1]},
            {"id": "a2", "name": "A2", "bearer_token": "outro-bearer"},
        ],
    )
    _set_last_error(suno_env.mgr, "suno_mcp", "401", 0)
    status = service.suno_status()
    assert status["available"] is True
    assert status["credential_state"] == "configured"
    url, _cmd, token = service._resolve_suno_mcp_credentials()
    assert token == "outro-bearer"


def test_suno_status_expired_falls_back_to_other_ready_server(suno_env):
    _bearer_account_server(suno_env.mgr)
    _set_last_error(suno_env.mgr, "suno_mcp", "401")
    other = _bearer_account_server(
        suno_env.mgr,
        server_id="suno-2",
        accounts=[{"id": "b1", "name": "B1", "bearer_token": "bearer-b1"}],
    )
    status = service.suno_status()
    assert status["available"] is True
    assert status["server_id"] == other["id"]


def test_suno_status_server_level_401_from_call_tool(suno_env, monkeypatch):
    import requests

    suno_env.mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno",
            "url": "https://api.suno.com/mcp",
            "bearer_token": PLANTED_SECRETS[1],
        },
        server_id="suno_mcp",
    )
    assert service.suno_status()["available"] is True

    def fake_rpc(url, method, params, headers, *, req_id=1, timeout=15):
        resp = requests.Response()
        resp.status_code = 401
        raise requests.HTTPError("401 Client Error: Unauthorized", response=resp)

    monkeypatch.setattr(suno_env.mgr, "_rpc_http", fake_rpc)
    with pytest.raises(requests.HTTPError):
        suno_env.mgr.call_tool("suno_mcp", "generate_music", {"prompt": "x"})
    status = service.suno_status()
    assert status["credential_state"] == "expired"
    assert status["available"] is False


def test_suno_catalog_never_leaks_secrets_and_masks_url(suno_env, monkeypatch):
    # (g) CA10: nenhum token/segredo plantado aparece no catálogo
    monkeypatch.setenv("SUNO_ENV_BEARER", PLANTED_SECRETS[3])
    suno_env.cfg["MUSIC_SUNO_MCP_URL"] = (
        "https://user:pass@api.suno.com/mcp?token=" + PLANTED_SECRETS[2] + "#frag"
    )
    suno_env.cfg["MUSIC_SUNO_MCP_TOKEN"] = PLANTED_SECRETS[2]
    _oauth_server(
        suno_env.mgr,
        url="https://user:pass@api.suno.com/mcp?access_token=" + PLANTED_SECRETS[0],
        bearer_token_env="SUNO_ENV_BEARER",
    )
    suno_env.connect_oauth("suno_mcp")
    suno_env.mgr._set_secret("suno_mcp", "_server", "bearer_token", PLANTED_SECRETS[1])
    catalog = service.providers_catalog()
    dumped = json.dumps(catalog) + json.dumps(service.suno_status())
    for secret in PLANTED_SECRETS + ("user:pass", "pass@"):
        assert secret not in dumped
    item = _suno_item(catalog)
    assert item["available"] is True
    assert item["url"] == "https://api.suno.com/mcp"
    assert catalog["selection"]["suno_mcp_url"] == "https://api.suno.com/mcp"


def test_resolve_suno_credentials_uses_single_source(suno_env):
    srv = suno_env.mgr.save_server(
        {
            "id": "suno-oficial",
            "name": "Suno",
            "url": "https://api.suno.com/mcp",
            "bearer_token": PLANTED_SECRETS[1],
        }
    )
    assert srv["id"] == "suno-oficial"
    url, cmd, token = service._resolve_suno_mcp_credentials()
    assert (url, cmd, token) == ("https://api.suno.com/mcp", "", PLANTED_SECRETS[1])


def test_mask_url():
    assert service._mask_url("https://u:p@api.suno.com:8443/mcp?sig=1#x") == (
        "https://api.suno.com:8443/mcp"
    )
    assert service._mask_url("") == ""
    assert service._mask_url("not a url") == ""


# --- T2 (offline): SunoMcpAdapter — descoberta, argumentos, erros tipados, polling ---

from Plugins.Apps.music import tools as music_tools  # noqa: E402

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "lyrics": {"type": "string"},
        "instrumental": {"type": "boolean"},
    },
    "required": ["prompt"],
}
STATUS_TOOL = {
    "name": "get_clip",
    "inputSchema": {"type": "object", "properties": {"clip_id": {"type": "string"}}},
}


class FakeSunoManager:
    """Fake MCPConnectorManager: records account pinning, timeouts and calls."""

    def __init__(self, tools, responses=None, cached=None, account="acc-1"):
        self._tools = tools
        self.responses = list(responses or [])
        self.calls = []
        self.list_calls = []
        self.cached = cached
        self.account = account
        self.select_calls = 0

    def _find_raw(self, server_id):
        return {"id": server_id, "cached_tools": self.cached}

    def select_account(self, server_id):
        self.select_calls += 1
        return self.account

    def list_tools(self, server_id, *, timeout=None, account_id=None):
        self.list_calls.append({"timeout": timeout, "account_id": account_id})
        tools = self._tools
        if callable(tools):
            tools = tools(len(self.list_calls))
        if isinstance(tools, Exception):
            raise tools
        return tools

    def call_tool(
        self,
        server_id,
        name,
        args,
        *,
        timeout=None,
        retry_other_accounts=True,
        account_id=None,
    ):
        self.calls.append(
            {
                "server_id": server_id,
                "name": name,
                "args": args,
                "timeout": timeout,
                "retry": retry_other_accounts,
                "account_id": account_id,
            }
        )
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _text_result(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _clip(cid, audio=True, status="complete"):
    clip = {"id": cid, "status": status}
    clip["audio_url"] = f"https://cdn.suno.test/{cid}.mp3" if audio else None
    return clip


def _adapter(manager, **kw):
    kw.setdefault("server_id", "suno_mcp")
    kw.setdefault("tool_name", "")
    kw.setdefault("timeout", 600)
    return music_tools.SunoMcpAdapter(manager=manager, **kw)


def test_discovery_prefers_known_names_and_heuristics():
    d = music_tools.discover_generation_tool
    tools = [
        {"name": "get_credits"},
        {"name": "create_song"},
        {"name": "generate_music"},
    ]
    assert d(tools)["name"] == "generate_music"
    assert d([{"name": "x"}, {"name": "suno_generate_custom_music"}])["name"] == (
        "suno_generate_custom_music"
    )
    assert d([{"name": "get_credits"}, {"name": "song_create_v2"}])["name"] == (
        "song_create_v2"
    )
    assert d(tools, configured="create_song")["name"] == "create_song"
    with pytest.raises(service.SunoProtocolError):
        d(tools, configured="nao_existe")
    with pytest.raises(service.SunoProtocolError):
        d([{"name": "get_credits"}, {"name": "get_clip"}])
    assert music_tools.discover_status_tool([STATUS_TOOL])["name"] == "get_clip"
    assert music_tools.discover_status_tool([{"name": "generate_music"}]) is None


def test_discovery_with_mock_default_tools():
    from tests.fixtures.fake_suno_mcp import DEFAULT_TOOLS

    tool = music_tools.discover_generation_tool(DEFAULT_TOOLS)
    assert tool["name"] == "generate_music"
    args = music_tools.map_generation_arguments(tool, "lofi", lyrics="", duration=40)
    assert args == {"prompt": "lofi", "instrumental": True, "duration": 40}


def test_argument_mapping_follows_schema():
    m = music_tools.map_generation_arguments
    tool = {"name": "g", "inputSchema": GEN_SCHEMA}
    assert m(tool, "lofi", lyrics="", duration=30) == {
        "prompt": "lofi",
        "instrumental": True,
    }
    assert m(tool, "lofi", lyrics="la la", duration=30) == {
        "prompt": "lofi",
        "lyrics": "la la",
        "instrumental": False,
    }
    styled = {
        "name": "g",
        "inputSchema": {
            "type": "object",
            "properties": {"style": {}, "lyric": {}, "duration": {}},
        },
    }
    assert m(styled, "rock", lyrics="oh", duration=45) == {
        "style": "rock",
        "lyric": "oh",
        "duration": 45,
    }
    with pytest.raises(service.SunoProtocolError):
        m({"name": "g", "inputSchema": {"properties": {"title": {}}}}, "x")
    with pytest.raises(service.SunoProtocolError):
        m(
            {
                "name": "g",
                "inputSchema": {
                    "properties": {"prompt": {}, "model": {}},
                    "required": ["prompt", "model"],
                },
            },
            "x",
        )


def test_clip_helpers():
    assert music_tools.clip_state(_clip("a")) == "ready"
    assert music_tools.clip_state({"id": "a", "audio_base64": "QUJD"}) == "ready"
    assert music_tools.clip_state(_clip("a", audio=False, status="error")) == "failed"
    assert music_tools.clip_state({"id": "a", "error": "x"}) == "failed"
    assert music_tools.clip_state({"status": "queued"}) == "failed"  # sem id
    assert music_tools.clip_state({"id": "a", "status": "queued"}) == "pending"
    assert music_tools.extract_clips({"clips": [_clip("a"), _clip("b")]}) == [
        _clip("a"),
        _clip("b"),
    ]
    assert music_tools.extract_clips({"id": "x", "status": "queued"}) == [
        {"id": "x", "status": "queued"}
    ]
    assert music_tools.extract_clips({"message": "ok"}) == []


# Item 7: todos os clips da chamada
def test_adapter_returns_all_clips_of_the_call():
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}],
        [_text_result({"clips": [_clip("c1"), _clip("c2")]})],
    )
    result = _adapter(mgr, timeout=420).generate("lofi", lyrics="", duration=30)
    assert [c["id"] for c in result["clips"]] == ["c1", "c2"]
    assert [c["state"] for c in result["clips"]] == ["ready", "ready"]
    assert result["remote_ids"] == ["c1", "c2"]
    call = mgr.calls[0]
    assert call["name"] == "generate_music"
    assert call["args"] == {"prompt": "lofi", "instrumental": True}
    assert call["retry"] is False
    assert 0 < call["timeout"] <= 420  # timeout total cobre a geração (item 8)


def test_adapter_partial_clip_from_mock_scenario_is_failed():
    # Cenário "partial" do mock: 2º clip sem áudio e status error
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}, STATUS_TOOL],
        [
            _text_result(
                {
                    "clips": [
                        _clip("c1"),
                        {**_clip("c2", audio=False, status="error"), "error": "x"},
                    ]
                }
            )
        ],
    )
    result = _adapter(mgr).generate("lofi")
    assert [c["state"] for c in result["clips"]] == ["ready", "failed"]
    assert len(mgr.calls) == 1  # nada de polling para clip já falho


# Item 6: uma conta só, fixada em tools/list, geração e polling
def test_adapter_pins_one_account_for_list_generation_and_polling():
    mgr, adapter, _clock = _polling(
        [
            _text_result({"clips": [{"id": "c1", "status": "queued"}]}),
            _text_result({"clips": [_clip("c1")]}),
        ],
        account="conta-B",
    )
    adapter.generate("lofi")
    assert mgr.select_calls == 1
    assert mgr.list_calls[0]["account_id"] == "conta-B"
    assert [c["account_id"] for c in mgr.calls] == ["conta-B", "conta-B"]
    assert all(c["retry"] is False for c in mgr.calls)


def test_adapter_uses_cached_tools_before_tools_list():
    mgr = FakeSunoManager(
        RuntimeError("não deveria chamar"),
        cached=[{"name": "create_song", "inputSchema": GEN_SCHEMA}],
    )
    assert _adapter(mgr).generation_tool()["name"] == "create_song"
    assert mgr.list_calls == []


# Item 9: SunoProtocolError com cache => refaz tools/list uma vez
def test_adapter_refreshes_stale_cache_once():
    mgr = FakeSunoManager(
        [{"name": "create_song", "inputSchema": GEN_SCHEMA}],
        [_text_result({"clips": [_clip("c1"), _clip("c2")]})],
        cached=[{"name": "get_credits"}],
    )
    result = _adapter(mgr).generate("lofi")
    assert len(mgr.list_calls) == 1
    assert mgr.calls[0]["name"] == "create_song"
    assert len(result["clips"]) == 2


def test_adapter_does_not_refresh_twice_or_without_cache():
    mgr = FakeSunoManager([{"name": "get_credits"}], [], cached=[{"name": "x"}])
    with pytest.raises(service.SunoProtocolError):
        _adapter(mgr).generate("lofi")
    assert len(mgr.list_calls) == 1
    assert mgr.calls == []
    mgr2 = FakeSunoManager([{"name": "get_credits"}], [])
    with pytest.raises(service.SunoProtocolError):
        _adapter(mgr2).generate("lofi")
    assert len(mgr2.list_calls) == 1


def test_adapter_reads_settings_defaults(monkeypatch):
    monkeypatch.setattr(
        service,
        "settings",
        lambda: {"MUSIC_SUNO_MCP_TOOL": "create_song", "MUSIC_SUNO_TIMEOUT": "123"},
    )
    adapter = music_tools.SunoMcpAdapter(manager=FakeSunoManager([]), server_id="s")
    assert adapter.tool_name == "create_song"
    assert adapter.timeout == 123


def _polling(responses, timeout=600, account="acc-1", status_tool=STATUS_TOOL):
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}, status_tool],
        responses,
        account=account,
    )
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    adapter = _adapter(
        mgr,
        timeout=timeout,
        poll_interval=5,
        sleep=sleep,
        clock=lambda: clock["t"],
    )
    return mgr, adapter, clock


def test_adapter_polls_until_all_clips_terminal():
    mgr, adapter, clock = _polling(
        [
            _text_result(
                {
                    "clips": [
                        {"id": "c1", "status": "queued"},
                        {"id": "c2", "status": "queued"},
                    ]
                }
            ),
            _text_result({"clips": [_clip("c1")]}),  # c1 pronto
            _text_result({"clips": [{"id": "c2", "status": "streaming"}]}),
            _text_result({"clips": [_clip("c2")]}),  # c2 pronto
        ]
    )
    result = adapter.generate("lofi")
    assert [c["state"] for c in result["clips"]] == ["ready", "ready"]
    assert [c["args"] for c in mgr.calls[1:]] == [
        {"clip_id": "c1"},
        {"clip_id": "c2"},
        {"clip_id": "c2"},
    ]
    assert clock["t"] == 10


def test_adapter_polls_with_batch_ids_field():
    batch_status = {
        "name": "get_clips",
        "inputSchema": {"type": "object", "properties": {"ids": {"type": "array"}}},
    }
    batch_status["name"] = "get_song"
    mgr, adapter, _ = _polling(
        [
            _text_result(
                {
                    "clips": [
                        {"id": "c1", "status": "queued"},
                        {"id": "c2", "status": "queued"},
                    ]
                }
            ),
            _text_result({"clips": [_clip("c1"), _clip("c2", False, "failed")]}),
        ],
        status_tool=batch_status,
    )
    result = adapter.generate("lofi")
    assert mgr.calls[1]["args"] == {"ids": ["c1", "c2"]}
    assert [c["state"] for c in result["clips"]] == ["ready", "failed"]


def test_adapter_polling_cancel_keeps_ready_clips():
    mgr, adapter, _ = _polling(
        [
            _text_result({"clips": [_clip("c1"), {"id": "c2", "status": "queued"}]}),
        ]
        + [_text_result({"clips": [{"id": "c2", "status": "queued"}]})] * 5
    )
    state = {"n": 0}

    def cancelled():
        state["n"] += 1
        return state["n"] > 3

    with pytest.raises(InterruptedError) as exc:
        adapter.generate("lofi", cancelled=cancelled)
    assert "créditos" in str(exc.value)
    assert [c["id"] for c in exc.value.partial_clips] == ["c1"]


def test_adapter_cancel_event_wait_is_used():
    import threading

    event = threading.Event()
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}, STATUS_TOOL],
        [_text_result({"clips": [{"id": "c1", "status": "queued"}]})],
    )
    waits = []

    class Ev:
        def wait(self, seconds):
            waits.append(seconds)
            event.set()
            return True

        def is_set(self):
            return event.is_set()

    adapter = _adapter(mgr, poll_interval=5, cancel_event=Ev())
    with pytest.raises(InterruptedError):
        adapter.generate("lofi")
    assert waits == [5]


def test_adapter_cancel_before_send_makes_no_call():
    mgr, adapter, _ = _polling([])
    with pytest.raises(InterruptedError):
        adapter.generate("lofi", cancelled=lambda: True)
    assert mgr.calls == []


def test_adapter_polling_total_timeout_keeps_ready_clips():
    mgr, adapter, clock = _polling(
        [_text_result({"clips": [_clip("c1"), {"id": "c2", "status": "queued"}]})]
        + [_text_result({"clips": [{"id": "c2", "status": "queued"}]})] * 50,
        timeout=20,
    )
    with pytest.raises(service.SunoTimeoutError) as exc:
        adapter.generate("lofi")
    assert clock["t"] <= 20
    assert [c["id"] for c in exc.value.partial_clips] == ["c1"]


# Item 8: tolera até 2 falhas seguidas no status; a 3ª desiste
def test_adapter_polling_tolerates_transient_status_failures():
    import requests

    mgr, adapter, _ = _polling(
        [
            _text_result({"clips": [{"id": "c1", "status": "queued"}]}),
            requests.ConnectionError("blip"),
            _http_error(503, "x"),
            _text_result({"clips": [_clip("c1")]}),
        ]
    )
    result = adapter.generate("lofi")
    assert result["clips"][0]["state"] == "ready"


def test_adapter_polling_gives_up_after_three_failures_and_keeps_partial():
    import requests

    mgr, adapter, _ = _polling(
        [
            _text_result({"clips": [_clip("c1"), {"id": "c2", "status": "queued"}]}),
            requests.ConnectionError("1"),
            requests.ConnectionError("2"),
            requests.ConnectionError("3"),
            _text_result({"clips": [_clip("c2")]}),
        ]
    )
    with pytest.raises(service.SunoUnavailableError) as exc:
        adapter.generate("lofi")
    assert [c["id"] for c in exc.value.partial_clips] == ["c1"]
    assert len(mgr.calls) == 4


def test_adapter_polling_auth_error_stops_immediately():
    mgr, adapter, _ = _polling(
        [
            _text_result({"clips": [{"id": "c1", "status": "queued"}]}),
            _http_error(401, "x"),
            _text_result({"clips": [_clip("c1")]}),
        ]
    )
    with pytest.raises(service.SunoAuthError) as exc:
        adapter.generate("lofi")
    assert exc.value.partial_clips == []
    assert len(mgr.calls) == 2


def test_adapter_pending_without_status_tool_is_failed():
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}],
        [_text_result({"clips": [_clip("c1"), {"id": "c2", "status": "queued"}]})],
    )
    result = _adapter(mgr).generate("lofi")
    assert [c["state"] for c in result["clips"]] == ["ready", "failed"]


def test_adapter_missing_audio_without_clips():
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}],
        [_text_result({"message": "ok"})],
    )
    with pytest.raises(service.SunoProtocolError):
        _adapter(mgr).generate("lofi")


# Item 10: regex de erro de autenticação
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Unauthorized", service.SunoAuthError),
        ("OAuth token rejected", service.SunoAuthError),
        ("token expired", service.SunoAuthError),
        ("Token invalid for this scope", service.SunoAuthError),
        ("HTTP 403 forbidden", service.SunoAuthError),
        ("author not found", service.SunoProtocolError),
        ("authoring tool busy", service.SunoProtocolError),
        ("bad prompt", service.SunoProtocolError),
    ],
)
def test_translate_auth_message_regex(message, expected):
    assert isinstance(music_tools.translate_suno_error(RuntimeError(message)), expected)


def _http_error(status, token):
    import requests

    resp = requests.Response()
    resp.status_code = status
    resp.url = f"https://api.suno.com/mcp?access_token={token}"
    return requests.HTTPError(
        f"{status} Error for url: https://api.suno.com/mcp?access_token={token} "
        f"Bearer {token}",
        response=resp,
    )


@pytest.mark.parametrize(
    ("exc_factory", "expected", "code"),
    [
        (lambda t: _http_error(401, t), service.SunoAuthError, "suno_auth"),
        (lambda t: _http_error(403, t), service.SunoAuthError, "suno_auth"),
        (
            lambda t: _http_error(500, t),
            service.SunoUnavailableError,
            "suno_unavailable",
        ),
        (
            lambda t: _http_error(503, t),
            service.SunoUnavailableError,
            "suno_unavailable",
        ),
        (
            lambda t: __import__("requests").ConnectionError(f"conn refused {t}"),
            service.SunoUnavailableError,
            "suno_unavailable",
        ),
        (
            lambda t: __import__("requests").Timeout(f"read timeout {t}"),
            service.SunoTimeoutError,
            "suno_timeout",
        ),
        (
            lambda t: RuntimeError(f"Unauthorized: token {t} invalid"),
            service.SunoAuthError,
            "suno_auth",
        ),
        (
            lambda t: RuntimeError(f"Erro MCP interno {t}"),
            service.SunoProtocolError,
            "error",
        ),
    ],
)
def test_adapter_translates_errors_without_leaking_token(exc_factory, expected, code):
    token = "planted-secret-token-T2"
    mgr = FakeSunoManager(
        [{"name": "generate_music", "inputSchema": GEN_SCHEMA}], [exc_factory(token)]
    )
    with pytest.raises(expected) as exc:
        _adapter(mgr).generate("lofi")
    assert exc.value.code == code
    assert isinstance(exc.value, service.MusicProviderError)
    assert token not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True
    assert len(mgr.calls) == 1  # sem retry automático


def test_adapter_tools_list_errors_are_typed():
    token = "planted-secret-token-T2"
    mgr = FakeSunoManager(_http_error(401, token))
    with pytest.raises(service.SunoAuthError) as exc:
        _adapter(mgr).generation_tool()
    assert token not in str(exc.value)


def test_friendly_messages_match_rn06():
    assert str(service.SunoAuthError()) == (
        "Autorização do Suno expirou. Reconecte em Configurações → Música"
    )
    assert str(service.SunoUnavailableError()) == (
        "Suno indisponível no momento, tente de novo ou use outro gerador"
    )
    assert str(service.SunoTimeoutError()) == (
        "O Suno não respondeu a tempo; a geração pode ter sido concluída lá"
    )


# --- Review T1/T2: itens 1 e 2 (ida e volta de valores mascarados) ---


@pytest.fixture
def suno_store_env(tmp_path, monkeypatch):
    from src import mcp_connectors, settings_store
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    vault = MemoryVault()
    sstore = settings_store.SettingsStore(
        path=tmp_path / "settings.sqlite3", vault=vault
    )
    monkeypatch.setattr(settings_store, "_store", sstore)
    mgr = mcp_connectors.MCPConnectorManager(
        store=WorkspaceStore(tmp_path / "ws.sqlite3"), vault=vault
    )
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)
    return SimpleNamespace(mgr=mgr, store=sstore)


REAL_URL = "https://user:pw@api.suno.com/mcp?access_token=url-secret-1"
REAL_CMD = "SUNO_API_TOKEN=env-secret-2 suno-mcp --token tok-secret-3 --api-key=key-secret-4 --verbose"


def test_masked_url_round_trip_keeps_real_value(suno_store_env):
    service.select_provider(provider="suno_mcp", suno_mcp_url=REAL_URL)
    catalog = service.providers_catalog()
    masked = catalog["selection"]["suno_mcp_url"]
    assert masked == "https://api.suno.com/mcp"
    # O MusicSettingsPanel reenvia o valor mascarado sem mudanças
    service.select_provider(provider="suno_mcp", suno_mcp_url=masked)
    assert service.settings()["MUSIC_SUNO_MCP_URL"] == REAL_URL
    assert suno_store_env.mgr._find_raw("suno_mcp")["url"] == REAL_URL
    # Valor diferente sobrescreve normalmente
    service.select_provider(suno_mcp_url="https://api.suno.com/mcp/v2")
    assert service.settings()["MUSIC_SUNO_MCP_URL"] == "https://api.suno.com/mcp/v2"


def test_masked_oauth_urls_round_trip(suno_store_env):
    real_auth = "https://auth.suno.test/authorize?tenant=t-secret"
    real_token = "https://auth.suno.test/token?k=k-secret"
    service.select_provider(
        suno_mcp_url="https://api.suno.com/mcp",
        suno_mcp_auth_type="oauth",
        suno_mcp_client_id="cid",
        suno_mcp_auth_url=real_auth,
        suno_mcp_token_url=real_token,
    )
    sel = service.providers_catalog()["selection"]
    assert sel["suno_mcp_oauth_auth_url"] == "https://auth.suno.test/authorize"
    service.select_provider(
        suno_mcp_auth_url=sel["suno_mcp_oauth_auth_url"],
        suno_mcp_token_url=sel["suno_mcp_oauth_token_url"],
    )
    oauth = suno_store_env.mgr._find_raw("suno_mcp")["accounts"][0]["oauth"]
    assert oauth["auth_url"] == real_auth
    assert oauth["token_url"] == real_token


def test_command_is_masked_and_round_trips(suno_store_env):
    service.select_provider(
        provider="suno_mcp", suno_mcp_command=REAL_CMD, suno_mcp_token="tk-5"
    )
    catalog = service.providers_catalog()
    dumped = json.dumps(catalog)
    for secret in ("env-secret-2", "tok-secret-3", "key-secret-4", "tk-5"):
        assert secret not in dumped
    masked = catalog["selection"]["suno_mcp_command"]
    assert masked == (
        "SUNO_API_TOKEN=•••• suno-mcp --token •••• --api-key=•••• --verbose"
    )
    assert _suno_item(catalog)["command"] == masked
    service.select_provider(suno_mcp_command=masked)
    assert service.settings()["MUSIC_SUNO_MCP_COMMAND"] == REAL_CMD
    assert suno_store_env.mgr._find_raw("suno_mcp")["command"] == REAL_CMD


def test_mask_command_rules():
    m = service._mask_command
    assert m("") == ""
    assert m("suno-mcp --verbose NODE_ENV=prod") == "suno-mcp --verbose NODE_ENV=prod"
    assert m('run --secret "a b" --key=x') == "run --secret •••• --key=••••"
    assert m("MY_PASSWORD=p cmd") == "MY_PASSWORD=•••• cmd"

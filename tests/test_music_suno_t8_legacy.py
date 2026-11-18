"""T8: local Suno mode removed (RN18) and old credentials migration (RN17/CA15).

Only fakes: no Suno call, no real keyring. Secret values are planted strings
that must never appear in a response.
"""

import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from Plugins.Apps.music import service
from src import mcp_connectors

SUNO_ACCESS = "planted-suno-access-1111"
SUNO_REFRESH = "planted-suno-refresh-2222"
SUNO_BEARER = "planted-suno-bearer-3333"
SUNO_SETTING = "planted-suno-setting-4444"
GENERIC_ACCESS = "planted-generic-access-5555"
PLANTED = (SUNO_ACCESS, SUNO_REFRESH, SUNO_BEARER, SUNO_SETTING, GENERIC_ACCESS)


class SharedVault:
    """Like KeyringVault: the profile vault plus vault_entries registration.

    ``reads`` records every ``get`` so a test can prove no value is read.
    """

    def __init__(self, settings):
        self.settings = settings
        self.reads = []

    def get(self, name):
        self.reads.append(name)
        return self.settings.vault.get(name)

    def set(self, name, value):
        self.settings.vault.set(name, value)
        self.settings.register_secret(name)

    def delete(self, name):
        self.settings.vault.delete(name)


@pytest.fixture
def legacy(isolated_profile, monkeypatch):
    from src.workspace_store import WorkspaceStore

    vault = SharedVault(isolated_profile)
    mgr = mcp_connectors.MCPConnectorManager(
        store=WorkspaceStore(isolated_profile.path), vault=vault
    )
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)
    # Old local Suno: MCP server + vault tokens + settings token.
    mgr.save_server(
        {
            "id": "suno_mcp",
            "name": "Suno (MCP)",
            "transport": "http_streaming",
            "url": "https://api.suno.com/mcp",
            "accounts": [{"id": "default", "name": "Suno OAuth", "auth_type": "oauth"}],
        },
        server_id="suno_mcp",
    )
    mgr._set_secret("suno_mcp", "default", "oauth_access_token", SUNO_ACCESS)
    mgr._set_secret("suno_mcp", "default", "oauth_refresh_token", SUNO_REFRESH)
    mgr._set_secret("suno_mcp", "_server", "bearer_token", SUNO_BEARER)
    isolated_profile.save(
        "Apps/music",
        {
            "MUSIC_PROVIDER": "suno_mcp",
            "MUSIC_SUNO_MCP_URL": "https://api.suno.com/mcp",
        },
    )
    isolated_profile.save(
        "Apps/music",
        {"MUSIC_SUNO_MCP_TOKEN": SUNO_SETTING},
        {"MUSIC_SUNO_MCP_TOKEN": "secret"},
    )
    # A generic MCP server with OAuth must survive everything.
    mgr.save_server(
        {
            "id": "notes",
            "name": "Notes",
            "transport": "http_streaming",
            "url": "https://notes.example.com/mcp",
            "accounts": [{"id": "acc1", "name": "Conta", "auth_type": "oauth"}],
        },
        server_id="notes",
    )
    mgr._set_secret("notes", "acc1", "oauth_access_token", GENERIC_ACCESS)
    vault.reads.clear()
    return SimpleNamespace(settings=isolated_profile, mgr=mgr, vault=vault)


def _suno_vault_names(settings):
    return sorted(
        row[0]
        for row in settings.rows("vault_entries")
        if row[0].startswith("mcp:connector:suno_mcp:")
        or row[0] == "setting:Apps/music:MUSIC_SUNO_MCP_TOKEN"
    )


def _all_present(env):
    s = env.settings
    assert (
        s.vault.get("mcp:connector:suno_mcp:default:oauth_access_token") == SUNO_ACCESS
    )
    assert (
        s.vault.get("mcp:connector:suno_mcp:default:oauth_refresh_token")
        == SUNO_REFRESH
    )
    assert s.vault.get("mcp:connector:suno_mcp:_server:bearer_token") == SUNO_BEARER
    assert s.vault.get("setting:Apps/music:MUSIC_SUNO_MCP_TOKEN") == SUNO_SETTING
    assert len(_suno_vault_names(s)) == 4
    assert any(r[1] == "MUSIC_SUNO_MCP_TOKEN" for r in s.rows("settings"))
    assert env.mgr._find_raw("suno_mcp")
    assert s.vault.get("mcp:connector:notes:acc1:oauth_access_token") == GENERIC_ACCESS


def _no_planted_values(blob):
    text = json.dumps(blob, ensure_ascii=False)
    for value in PLANTED:
        assert value not in text, value


# --------------------------------------------------------------------------
# catalog / provider boundary
# --------------------------------------------------------------------------
def test_catalog_keeps_suno_mcp_id_without_local_mode_fields(legacy):
    catalog = service.providers_catalog()
    suno = next(p for p in catalog["providers"] if p["id"] == "suno_mcp")
    assert suno["label"] == "Suno"
    assert suno["available"] is False
    assert suno["reason"] == "pia_server_unsupported"
    assert suno["hint"]["text"].startswith("Não foi possível falar com a PIA Server")
    assert suno["legacy_credentials"] == {"present": True, "prompt": True}
    for gone in (
        "url",
        "command",
        "token_configured",
        "auth_type",
        "oauth_connected",
        "oauth_client_id",
        "oauth_auth_url",
        "oauth_token_url",
        "server_id",
        "endpoint_configured",
    ):
        assert gone not in suno, gone
    assert catalog["selection"] == {"provider": "suno_mcp", "gemini_model": "lyria-3.5"}
    _no_planted_values(catalog)
    # Old credentials are never read to build the status (RN18).
    assert not any("suno" in name.lower() for name in legacy.vault.reads)


def test_select_provider_accepts_suno_mcp_and_ignores_old_fields(legacy):
    with pytest.raises(TypeError):
        service.select_provider(provider="suno_mcp", suno_mcp_token="x")
    catalog = service.select_provider(provider="suno_mcp")
    assert catalog["selection"]["provider"] == "suno_mcp"
    assert service.MUSIC_PROVIDERS == ("local", "gemini", "suno_mcp")


def test_remote_status_seam_drives_catalog_and_refusal(legacy, monkeypatch):
    monkeypatch.setattr(
        service,
        "_remote_suno_status",
        lambda: {"available": False, "reason": "pia_server_unpaired"},
    )
    status = service.suno_status()
    assert status["hint"] == {
        "text": "Para usar o Suno, entre na PIA Server em Configurações → PIA Server.",
        "route": "settings/pia_server",
    }
    assert service.suno_job_refusal().code == "pia_server_unpaired"
    monkeypatch.setattr(
        service, "_remote_suno_status", lambda: {"available": False, "reason": "weird"}
    )
    assert service.suno_status()["reason"] == "pia_server_unreachable"
    monkeypatch.setattr(
        service, "_remote_suno_status", lambda: {"available": True, "connected": True}
    )
    status = service.suno_status()
    assert status["available"] is True and status["reason"] is None
    assert status["hint"] is None


def test_batch_without_server_client_never_calls_the_suno(legacy, monkeypatch):
    def no_network(*_a, **_k):
        raise AssertionError("no network call expected")

    monkeypatch.setattr("requests.post", no_network)
    monkeypatch.setattr("requests.Session.request", no_network)
    with pytest.raises(service.SunoUnavailableError) as err:
        service.generate_suno_batch("piano", "", 30, 1)
    assert err.value.code == "suno_unavailable"
    assert (err.value.completed, err.value.total) == (0, 1)
    assert not hasattr(service, "suno_oauth_start")
    assert not hasattr(service, "_ensure_suno_mcp_server")
    assert not hasattr(service, "_resolve_suno_mcp_credentials")
    from Plugins.Apps.music import tools

    assert not hasattr(tools, "SunoMcpAdapter")
    assert not hasattr(tools, "call_suno_mcp")


# --------------------------------------------------------------------------
# migration endpoints
# --------------------------------------------------------------------------
def test_legacy_state_lists_labels_only_without_reading_values(legacy):
    from Plugins.Apps.music import suno_legacy

    state = suno_legacy.legacy_state()
    assert state["present"] is True and state["prompt"] is True
    kinds = [item["kind"] for item in state["items"]]
    assert kinds.count("vault") == 3
    assert kinds.count("setting") == 2  # token + URL
    assert kinds.count("mcp_server") == 1
    assert all(set(item) == {"kind", "label"} for item in state["items"])
    _no_planted_values(state)
    assert legacy.vault.reads == []
    _all_present(legacy)


def test_remove_without_confirm_is_refused_and_deletes_nothing(legacy):
    from Plugins.Apps.music import suno_legacy

    for payload in (None, {}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
        with pytest.raises(suno_legacy.LegacyConfirmationRequired) as err:
            suno_legacy.remove_legacy(payload)
        assert isinstance(err.value, ValueError)
        assert err.value.code == "confirmation_required"
    _all_present(legacy)
    assert suno_legacy.legacy_state()["prompt"] is True


def test_remove_with_confirm_deletes_only_old_suno_entries(legacy):
    from Plugins.Apps.music import suno_legacy

    result = suno_legacy.remove_legacy({"confirm": True})
    assert result["ok"] is True
    assert result["present"] is False and result["prompt"] is False
    assert len(result["removed"]) == 6
    _no_planted_values(result)
    s = legacy.settings
    for name in (
        "mcp:connector:suno_mcp:default:oauth_access_token",
        "mcp:connector:suno_mcp:default:oauth_refresh_token",
        "mcp:connector:suno_mcp:_server:bearer_token",
        "setting:Apps/music:MUSIC_SUNO_MCP_TOKEN",
    ):
        assert s.vault.get(name) is None, name
    assert _suno_vault_names(s) == []
    assert not any(r[1].startswith("MUSIC_SUNO_") for r in s.rows("settings"))
    with pytest.raises(KeyError):
        legacy.mgr._find_raw("suno_mcp")
    # Everything else stays: generic MCP OAuth and the saved provider id.
    assert s.vault.get("mcp:connector:notes:acc1:oauth_access_token") == GENERIC_ACCESS
    assert legacy.mgr.get_server("notes")["accounts"][0]["id"] == "acc1"
    assert service.settings()["MUSIC_PROVIDER"] == "suno_mcp"
    assert suno_legacy.legacy_state() == {
        "present": False,
        "prompt": False,
        "items": [],
    }


def test_dismiss_deletes_nothing_and_turns_the_question_off(legacy):
    from Plugins.Apps.music import suno_legacy

    result = suno_legacy.dismiss_legacy()
    assert result["ok"] is True and result["prompt"] is False
    assert result["present"] is True
    _no_planted_values(result)
    _all_present(legacy)
    assert suno_legacy.legacy_state()["prompt"] is False
    catalog = service.providers_catalog()
    suno = next(p for p in catalog["providers"] if p["id"] == "suno_mcp")
    assert suno["legacy_credentials"] == {"present": True, "prompt": False}
    # The Settings button still works after "Agora não", with confirmation.
    suno_legacy.remove_legacy({"confirm": True})
    assert suno_legacy.legacy_state()["present"] is False


def test_startup_catalog_and_profile_import_never_delete(legacy):
    from Plugins.Apps.music import suno_legacy
    from src.config_transfer import export_config, import_config
    from src.integrations.plugins.host import PluginHost
    from src.profile_migration import initialize_profile

    host = PluginHost(Path(__file__).resolve().parents[1] / "Plugins")
    assert host.load_tools_module("music") is not None
    initialize_profile()
    service.providers_catalog()
    service.suno_status()
    suno_legacy.legacy_state()
    legacy.mgr.list_servers()
    import_config(export_config("")["data"], "")
    _all_present(legacy)


# --------------------------------------------------------------------------
# HTTP: 400 {code} and secret-free responses through src/pia/http.py
# --------------------------------------------------------------------------
class _Handler:
    def __init__(self, path, method="POST", body=b"{}"):
        self.path = path
        self.command = method
        self.client_address = ("127.0.0.1", 50000)
        self.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
        self.headers = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Cookie": "pia_session=t8-test-session",
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


def _call(monkeypatch, path, method="POST", payload=None):
    from src.pia import http as pia_http
    from src.pia.service import WorkspaceService

    workspace = WorkspaceService(backend=SimpleNamespace(store=None))
    monkeypatch.setitem(pia_http._sessions, "t8-test-session", time.time() + 60)
    monkeypatch.setattr(pia_http, "get_service", lambda: workspace)
    body = json.dumps(payload or {}).encode()
    handler = _Handler("/api/pia" + path, method, body if method == "POST" else b"")
    assert pia_http.route(handler) is True
    return handler


def test_http_legacy_routes(legacy, monkeypatch):
    got = _call(monkeypatch, "/music/suno/legacy-credentials", "GET")
    assert got.status == 200 and got.json()["present"] is True
    _no_planted_values(got.json())

    refused = _call(monkeypatch, "/music/suno/legacy-credentials/remove", payload={})
    assert refused.status == 400
    assert refused.json()["code"] == "confirmation_required"
    _all_present(legacy)

    dismissed = _call(monkeypatch, "/music/suno/legacy-credentials/dismiss")
    assert dismissed.status == 200 and dismissed.json()["prompt"] is False
    _all_present(legacy)

    removed = _call(
        monkeypatch,
        "/music/suno/legacy-credentials/remove",
        payload={"confirm": True},
    )
    assert removed.status == 200 and removed.json()["ok"] is True
    _no_planted_values(removed.json())
    assert _suno_vault_names(legacy.settings) == []

    providers = _call(monkeypatch, "/music/providers", "GET")
    assert providers.status == 200
    _no_planted_values(providers.json())
    for old in ("/music/suno/oauth/start", "/music/suno/oauth/callback"):
        assert _call(monkeypatch, old).status in (400, 404)

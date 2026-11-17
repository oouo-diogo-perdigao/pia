from src.settings_store import get as setting

"""Music providers. Local ACE-Step is isolated from PIA's Torch environment."""
import atexit
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import uuid
import requests
from src.config_paths import BASE_DIR
from src.settings_store import values as section_values, document, save_document
from src.resource_plugins import save_json

ROOT = Path(__file__).resolve().parent
CACHE = BASE_DIR / "cache/Apps/music"


def default_music_folder():
    home = Path.home()
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                return (
                    Path(os.path.expandvars(winreg.QueryValueEx(key, "My Music")[0]))
                    / "PIA"
                )
        except OSError:
            pass
    else:
        file = (
            Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "user-dirs.dirs"
        )
        if file.is_file():
            match = re.search(
                r'^XDG_MUSIC_DIR="([^"]+)"', file.read_text(encoding="utf-8"), re.M
            )
            if match:
                return Path(match.group(1).replace("$HOME", str(home))) / "PIA"
    return home / "Music/PIA"


from src.user_paths import user_path

OUTPUT = user_path("music")
LEGACY_OUTPUT = OUTPUT
REVISION = "ca1e85fe9430179831e6bc6be790c332190a3866"
_engine = None
_token = secrets.token_urlsafe(40)
_lock = threading.Lock()
_generation_lock = threading.Lock()


def settings():
    return section_values("Apps/music")


MUSIC_PROVIDERS = ("local", "gemini", "suno_mcp")
_SUNO_MCP_SERVER_ID = "suno_mcp"


class MusicProviderError(RuntimeError):
    """Provider error with a friendly, secret-free message and a stable ``code``."""

    code = "error"
    default_message = "Falha ao gerar a música."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.default_message)


class SunoAuthError(MusicProviderError):
    code = "suno_auth"
    default_message = "Autorização do Suno expirou. Reconecte em Configurações → Música"


class SunoUnavailableError(MusicProviderError):
    code = "suno_unavailable"
    default_message = "Suno indisponível no momento, tente de novo ou use outro gerador"


class SunoTimeoutError(MusicProviderError):
    code = "suno_timeout"
    default_message = (
        "O Suno não respondeu a tempo; a geração pode ter sido concluída lá"
    )


class SunoProtocolError(MusicProviderError):
    """Unexpected/incompatible answer from the Suno MCP (code ``error``)."""

    default_message = "O Suno recusou ou não entendeu a solicitação; nenhuma nova tentativa foi feita."


SUNO_SETTINGS_ROUTE = {"view": "settings", "section": "Apps/music"}
_SECRET_ENV_KEY = re.compile(r"(TOKEN|SECRET|KEY|PASSWORD|AUTH|BEARER|COOKIE)", re.I)
_AUTH_ERROR_CODES = ("401", "403")
_CMD_SECRET_FLAG = re.compile(
    r"(?i)(--?(?:token|access[-_]?token|api[-_]?key|key|secret|password|bearer)(?:=|\s+))"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)
_CMD_ENV_ASSIGN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)")


def _mask_url(url: str) -> str:
    """Remove userinfo, query and fragment so the URL never carries secrets."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if not parts.scheme or not parts.hostname:
        return ""
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    return f"{parts.scheme}://{netloc}{parts.path}"


def _mask_command(cmd: str) -> str:
    """Hide values of --token/--api-key/--key=… and secret-looking VAR=value."""
    raw = str(cmd or "").strip()
    if not raw:
        return ""
    out = _CMD_SECRET_FLAG.sub(lambda m: m.group(1) + "••••", raw)
    return _CMD_ENV_ASSIGN.sub(
        lambda m: (m.group(1) + "=••••")
        if _SECRET_ENV_KEY.search(m.group(1))
        else m.group(0),
        out,
    )


def _keep_if_masked(received: Any, currents: list[str], masker: Any) -> Any:
    """Round-trip guard: the UI sends back the masked value it received.

    If ``received`` equals the masked form of a current (real) value, keep the
    real value instead of overwriting it with the masked one.
    """
    if received is None:
        return None
    value = str(received).strip()
    for current in currents:
        current = str(current or "").strip()
        if current and value != current and value == masker(current):
            return current
    return received


def _suno_server_evaluation(
    mgr: Any, raw: dict[str, Any], cfg: dict[str, Any], *, include_secrets: bool
) -> dict[str, Any]:
    """Evaluate one registered Suno MCP server (endpoint + credential, no I/O)."""
    sid = str(raw.get("id") or "")
    is_primary = sid == _SUNO_MCP_SERVER_ID
    transport = str(raw.get("transport") or "http_streaming")
    url = str(raw.get("url") or "").strip()
    cmd = str(raw.get("command") or "").strip()
    if is_primary:
        # Legacy mirror: settings Apps/music only complement the server with id suno_mcp.
        url = url or str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
        cmd = cmd or str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
    if transport == "stdio":
        endpoint = bool(cmd)
    else:
        endpoint = bool(url) or (is_primary and bool(cmd))

    accounts = [a for a in (raw.get("accounts") or []) if a.get("enabled", True)]
    oauth_connected = False
    oauth_meta: dict[str, Any] = {}
    bearer = False
    expired = False
    token = ""
    acc_auth_type = ""
    ready: list[tuple[bool, bool, str, dict[str, Any]]] = []
    for acc in accounts or [None]:
        try:
            headers, env_vars = mgr._resolve_credentials(raw, acc)
        except Exception:
            headers, env_vars = {}, {}
        acc_oauth = (acc or {}).get("oauth") or {}
        acc_id = str((acc or {}).get("id") or "")
        vault_oauth = (
            mgr._get_secret(sid, acc_id, "oauth_access_token").strip() if acc else ""
        )
        acc_oauth_ok = bool(acc_oauth.get("connected") and vault_oauth)
        auth_header = str(headers.get("Authorization") or "").strip()
        acc_bearer = bool(auth_header)
        if acc and vault_oauth and not acc_oauth_ok:
            # OAuth token left in the vault without connected=True does not count.
            acc_bearer = bool(
                mgr._get_secret(sid, acc_id, "bearer_token").strip()
                or mgr._get_secret(sid, "_server", "bearer_token").strip()
            )
        if transport == "stdio" and any(
            str(v).strip() and _SECRET_ENV_KEY.search(str(k))
            for k, v in (env_vars or {}).items()
        ):
            acc_bearer = True
        if acc and not oauth_meta:
            oauth_meta = acc_oauth
            acc_auth_type = str(acc.get("auth_type") or "")
        if not (acc_oauth_ok or acc_bearer):
            continue
        # Last call answered 401/403 => this credential is considered expired.
        # Uses the recorded code (HTTP status), not the free-text message.
        error_code = (acc or {}).get("last_error_code") if acc else None
        if not acc:
            error_code = raw.get("last_error_code")
        acc_expired = str(error_code or "") in _AUTH_ERROR_CODES
        ready.append((acc_oauth_ok, acc_expired, auth_header, acc or {}))
    if ready:
        # Prefer non-expired credentials, then OAuth over bearer.
        ready.sort(key=lambda item: (item[1], not item[0]))
        best_oauth, best_expired, best_header, best_acc = ready[0]
        oauth_connected = any(item[0] for item in ready)
        bearer = any(not item[0] for item in ready)
        expired = best_expired  # every credentialed account is expired
        if best_acc:
            if best_oauth:
                oauth_meta = best_acc.get("oauth") or {}
            acc_auth_type = str(best_acc.get("auth_type") or acc_auth_type)
        if include_secrets and best_header.startswith("Bearer "):
            token = best_header[len("Bearer ") :].strip()
    settings_token = (
        str(cfg.get("MUSIC_SUNO_MCP_TOKEN") or "").strip() if is_primary else ""
    )
    if settings_token and not ready:
        # Legacy MUSIC_SUNO_MCP_TOKEN only fills in when the server has none.
        bearer = True
        expired = str(raw.get("last_error_code") or "") in _AUTH_ERROR_CODES
        if include_secrets:
            token = settings_token
    credential = oauth_connected or bearer
    auth_type = acc_auth_type or (
        "oauth"
        if oauth_meta.get("client_id") or oauth_connected
        else ("bearer" if bearer else "none")
    )
    out = {
        "server_id": sid,
        "server_enabled": bool(raw.get("enabled", True)),
        "transport": transport,
        "url": url,
        "command": cmd,
        "endpoint_configured": endpoint,
        "has_credential": credential,
        "oauth_connected": oauth_connected,
        "has_token": credential,
        "expired": expired,
        "auth_type": auth_type,
        "oauth": oauth_meta,
    }
    if include_secrets:
        out["token"] = token
    return out


def _suno_resolve(*, include_secrets: bool = False) -> dict[str, Any]:
    """Single source of truth for the Suno provider (RN01, D1).

    available = endpoint (URL or command) AND credential (OAuth connected or
    bearer/env secret). Registered MCP servers (id ``suno_mcp`` or host
    ``api.suno.com``) are the primary source; settings ``Apps/music`` are only a
    legacy mirror/fallback. No network calls (RN06: no health check).
    """
    cfg = settings()
    servers: list[dict[str, Any]] = []
    mgr = None
    try:
        from src.mcp_connectors import get_mcp_manager

        mgr = get_mcp_manager()
        servers = mgr.find_suno_servers()
    except Exception:
        servers = []

    chosen: dict[str, Any] | None = None
    source = "none"
    if servers and mgr is not None:
        enabled = [s for s in servers if s.get("enabled", True)]
        evaluations = [
            _suno_server_evaluation(mgr, s, cfg, include_secrets=include_secrets)
            for s in enabled
        ]
        ready = [
            e
            for e in evaluations
            if e["endpoint_configured"] and e["has_credential"] and not e["expired"]
        ]
        primary_first = lambda items: sorted(  # noqa: E731
            items, key=lambda e: e["server_id"] != _SUNO_MCP_SERVER_ID
        )
        if ready:
            chosen = primary_first(ready)[0]
        elif evaluations:
            chosen = primary_first(evaluations)[0]
        else:
            # Only disabled Suno servers: report them as unavailable.
            raw = sorted(servers, key=lambda s: s.get("id") != _SUNO_MCP_SERVER_ID)[0]
            chosen = _suno_server_evaluation(
                mgr, raw, cfg, include_secrets=include_secrets
            )
            chosen["endpoint_configured"] = False
            chosen["has_credential"] = False
            chosen["has_token"] = False
            chosen["oauth_connected"] = False
            chosen["expired"] = False
            if include_secrets:
                chosen["token"] = ""
        source = "mcp_server"
    if chosen is None:
        url = str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
        cmd = str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
        tok = str(cfg.get("MUSIC_SUNO_MCP_TOKEN") or "").strip()
        chosen = {
            "server_id": _SUNO_MCP_SERVER_ID,
            "server_enabled": True,
            "transport": "stdio" if (cmd and not url) else "http_streaming",
            "url": url,
            "command": cmd,
            "endpoint_configured": bool(url or cmd),
            "has_credential": bool(tok),
            "oauth_connected": False,
            "has_token": bool(tok),
            "expired": False,
            "auth_type": "bearer" if tok else "none",
            "oauth": {},
        }
        if include_secrets:
            chosen["token"] = tok
        source = "settings" if (url or cmd or tok) else "none"

    oauth = chosen.pop("oauth", {}) or {}
    # Expired credential (last call answered 401/403) => unavailable until the
    # user reconnects (new credential clears last_error in mcp_connectors).
    available = bool(
        chosen["server_enabled"]
        and chosen["endpoint_configured"]
        and chosen["has_credential"]
        and not chosen["expired"]
    )
    if not chosen["has_credential"]:
        credential_state = "missing"
    elif chosen["expired"]:
        credential_state = "expired"
    else:
        credential_state = "configured"
    status = {
        **chosen,
        "id": "suno_mcp",
        "label": "Suno",
        "available": available,
        "credential_state": credential_state,
        "source": source,
        "url_masked": _mask_url(chosen["url"]),
        "settings_route": dict(SUNO_SETTINGS_ROUTE),
        "oauth_client_id": str(oauth.get("client_id") or ""),
        "oauth_auth_url": _mask_url(str(oauth.get("auth_url") or "")),
        "oauth_token_url": _mask_url(str(oauth.get("token_url") or "")),
        "oauth_scopes": str(oauth.get("scopes") or ""),
    }
    status.pop("expired", None)
    status.pop("has_credential", None)
    return status


def suno_status() -> dict[str, Any]:
    """Public, secret-free Suno status used by catalog, generate() and tools."""
    status = _suno_resolve(include_secrets=False)
    status["url"] = status["url_masked"]
    status["command"] = _mask_command(status["command"])
    return status


def _ensure_suno_mcp_server(
    *,
    suno_url: str | None = None,
    suno_cmd: str | None = None,
    suno_token: str | None = None,
    oauth_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.mcp_connectors import get_mcp_manager

    cfg = settings()
    url = (
        str(suno_url).strip()
        if suno_url is not None
        else str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
    )
    cmd = (
        str(suno_cmd).strip()
        if suno_cmd is not None
        else str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
    )
    mgr = get_mcp_manager()
    try:
        existing = mgr.get_server(_SUNO_MCP_SERVER_ID)
    except KeyError:
        existing = None

    transport = "stdio" if (cmd and not url) else "http_streaming"
    payload: dict[str, Any] = {
        "id": _SUNO_MCP_SERVER_ID,
        "name": "Suno (MCP)",
        "transport": transport,
        "url": url,
        "command": cmd,
        "enabled": True,
    }
    if suno_token is not None and str(suno_token).strip():
        payload["bearer_token"] = str(suno_token).strip()

    if oauth_payload:
        existing_accounts = [dict(a) for a in ((existing or {}).get("accounts") or [])]
        target_acc_id = str(oauth_payload.get("account_id") or "").strip()
        target_idx = 0
        if target_acc_id and existing_accounts:
            matched_idx = next(
                (
                    idx
                    for idx, item in enumerate(existing_accounts)
                    if item.get("id") == target_acc_id
                ),
                None,
            )
            if matched_idx is None:
                raise ValueError(
                    f"Conta '{target_acc_id}' não encontrada no servidor '{_SUNO_MCP_SERVER_ID}'."
                )
            target_idx = matched_idx
        acc = (
            dict(existing_accounts[target_idx])
            if existing_accounts
            else {"id": target_acc_id or "default", "name": "Suno OAuth"}
        )
        oauth = dict(acc.get("oauth") or {})
        for key in ("client_id", "auth_url", "token_url", "scopes", "redirect_uri"):
            if key in oauth_payload and oauth_payload[key] is not None:
                value = str(oauth_payload[key]).strip()
                if key in ("auth_url", "token_url"):
                    # Catalog exposes these masked; don't overwrite the real URL.
                    value = str(
                        _keep_if_masked(value, [oauth.get(key) or ""], _mask_url)
                    ).strip()
                oauth[key] = value
        if oauth_payload.get("client_secret"):
            oauth["client_secret"] = str(oauth_payload["client_secret"]).strip()
        acc["oauth"] = oauth
        if oauth_payload.get("auth_type"):
            acc["auth_type"] = str(oauth_payload["auth_type"]).strip()
        elif oauth.get("client_id") or oauth.get("auth_url"):
            acc["auth_type"] = "oauth"
        if existing_accounts:
            existing_accounts[target_idx] = acc
            payload["accounts"] = existing_accounts
        else:
            payload["accounts"] = [acc]

    return mgr.save_server(payload, server_id=_SUNO_MCP_SERVER_ID)


def _resolve_suno_mcp_credentials(
    cfg: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """(url, command, token) for the Suno MCP, read through the single source.

    ``cfg`` is accepted for backwards compatibility and ignored: the settings are
    read inside ``_suno_resolve``.
    """
    status = _suno_resolve(include_secrets=True)
    return status["url"], status["command"], status.get("token", "")


def suno_oauth_start(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    from src.mcp_connectors import SUNO_OAUTH_DEFAULTS, get_mcp_manager

    cfg = settings()
    suno_url = str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
    suno_cmd = str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
    if not suno_url and not suno_cmd:
        suno_url = SUNO_OAUTH_DEFAULTS["mcp_url"]
        from src.settings_store import get_store

        get_store().save("Apps/music", {"MUSIC_SUNO_MCP_URL": suno_url})

    _ensure_suno_mcp_server(suno_url=suno_url, oauth_payload=data)
    mgr = get_mcp_manager()
    return mgr.start_oauth(
        _SUNO_MCP_SERVER_ID,
        account_id=data.get("account_id"),
        payload=data,
    )


def suno_oauth_callback(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    from src.mcp_connectors import get_mcp_manager

    _ensure_suno_mcp_server()
    mgr = get_mcp_manager()
    return mgr.complete_oauth(_SUNO_MCP_SERVER_ID, payload=data)


def suno_oauth_disconnect() -> dict[str, Any]:
    from src.mcp_connectors import get_mcp_manager

    mgr = get_mcp_manager()
    try:
        servers = mgr._raw_servers()
        srv = next((s for s in servers if s.get("id") == _SUNO_MCP_SERVER_ID), None)
        if srv:
            for acc in srv.get("accounts") or []:
                mgr._set_secret(
                    _SUNO_MCP_SERVER_ID, acc["id"], "oauth_access_token", ""
                )
                mgr._set_secret(
                    _SUNO_MCP_SERVER_ID, acc["id"], "oauth_refresh_token", ""
                )
                oauth = acc.setdefault("oauth", {})
                oauth["connected"] = False
                oauth["token_masked"] = ""
            mgr._save_raw_servers(servers)
    except Exception:
        pass
    return {"ok": True, **providers_catalog()}


def providers_catalog():
    cfg = settings()
    selected = str(cfg.get("MUSIC_PROVIDER") or "local").strip().lower()
    if selected not in MUSIC_PROVIDERS:
        selected = "local"
    local_installed = (CACHE / "ace-step/.venv").is_dir()
    from src.config import STT_GEMINI_API_KEY, setting

    gemini_key = bool(
        setting("GEMINI_API_KEY") or setting("AGE_GEMINI_API_KEY") or STT_GEMINI_API_KEY
    )
    suno = suno_status()
    suno_url = suno["url_masked"]
    suno_cmd = suno["command"]
    suno_token = suno["has_token"]
    return {
        "providers": [
            {
                "id": "local",
                "name": "Criador de músicas local",
                "kind": "local",
                "description": "ACE-Step local offline",
                "installed": local_installed,
                "available": True,
            },
            {
                "id": "gemini",
                "name": "Gemini",
                "kind": "remote",
                "description": "Geração de música via Gemini (Lyria)",
                "model": str(cfg.get("MUSIC_GEMINI_MODEL") or "lyria-3.5"),
                "credential_state": "configured" if gemini_key else "missing",
                "available": gemini_key,
            },
            {
                "id": "suno_mcp",
                "label": "Suno",
                "name": "Suno (MCP)",
                "kind": "mcp",
                "description": "Conexão com servidor MCP do Suno",
                "url": suno_url,
                "command": suno_cmd,
                "endpoint_configured": suno["endpoint_configured"],
                "credential_state": suno["credential_state"],
                "token_configured": suno_token,
                "auth_type": suno["auth_type"],
                "oauth_connected": suno["oauth_connected"],
                "oauth_client_id": suno["oauth_client_id"],
                "oauth_auth_url": suno["oauth_auth_url"],
                "oauth_token_url": suno["oauth_token_url"],
                "oauth_scopes": suno["oauth_scopes"],
                "server_id": suno["server_id"],
                "settings_route": suno["settings_route"],
                "available": suno["available"],
            },
        ],
        "selection": {
            "provider": selected,
            "gemini_model": str(cfg.get("MUSIC_GEMINI_MODEL") or "lyria-3.5"),
            "suno_mcp_url": suno_url,
            "suno_mcp_command": suno_cmd,
            "suno_mcp_token_configured": suno_token,
            "suno_mcp_auth_type": suno["auth_type"],
            "suno_mcp_oauth_connected": suno["oauth_connected"],
            "suno_mcp_oauth_client_id": suno["oauth_client_id"],
            "suno_mcp_oauth_auth_url": suno["oauth_auth_url"],
            "suno_mcp_oauth_token_url": suno["oauth_token_url"],
            "suno_mcp_oauth_scopes": suno["oauth_scopes"],
        },
    }


def select_provider(
    *,
    provider: str | None = None,
    gemini_model: str | None = None,
    suno_mcp_url: str | None = None,
    suno_mcp_command: str | None = None,
    suno_mcp_token: str | None = None,
    suno_mcp_auth_type: str | None = None,
    suno_mcp_client_id: str | None = None,
    suno_mcp_client_secret: str | None = None,
    suno_mcp_auth_url: str | None = None,
    suno_mcp_token_url: str | None = None,
    suno_mcp_scopes: str | None = None,
    suno_mcp_redirect_uri: str | None = None,
):
    from src.settings_store import get_store

    if suno_mcp_url is not None or suno_mcp_command is not None:
        # The catalog exposes masked URL/command; keep the real ones when the
        # UI sends the masked value back unchanged (review item 1/2).
        current = _suno_resolve(include_secrets=False)
        cfg_now = settings()
        url_candidates = [str(cfg_now.get("MUSIC_SUNO_MCP_URL") or ""), current["url"]]
        cmd_candidates = [
            str(cfg_now.get("MUSIC_SUNO_MCP_COMMAND") or ""),
            current["command"],
        ]
        try:
            from src.mcp_connectors import get_mcp_manager

            primary = get_mcp_manager()._find_raw(_SUNO_MCP_SERVER_ID)
            url_candidates.append(str(primary.get("url") or ""))
            cmd_candidates.append(str(primary.get("command") or ""))
        except Exception:
            pass
        suno_mcp_url = _keep_if_masked(suno_mcp_url, url_candidates, _mask_url)
        suno_mcp_command = _keep_if_masked(
            suno_mcp_command, cmd_candidates, _mask_command
        )

    updates = {}
    if provider is not None:
        norm = str(provider).strip().lower()
        if norm not in MUSIC_PROVIDERS:
            raise ValueError(
                "Provedor de música inválido. Escolha local, gemini ou suno_mcp."
            )
        updates["MUSIC_PROVIDER"] = norm
    if gemini_model is not None and str(gemini_model).strip():
        updates["MUSIC_GEMINI_MODEL"] = str(gemini_model).strip()
    if suno_mcp_url is not None:
        raw_url = str(suno_mcp_url).strip()
        if raw_url:
            parsed = urlsplit(raw_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("URL do Suno MCP deve usar http:// ou https://.")
        updates["MUSIC_SUNO_MCP_URL"] = raw_url
    if suno_mcp_command is not None:
        updates["MUSIC_SUNO_MCP_COMMAND"] = str(suno_mcp_command).strip()
    if suno_mcp_token is not None:
        updates["MUSIC_SUNO_MCP_TOKEN"] = str(suno_mcp_token).strip()
    if updates:
        get_store().save("Apps/music", updates)

    oauth_fields = {
        k: v
        for k, v in {
            "auth_type": suno_mcp_auth_type,
            "client_id": suno_mcp_client_id,
            "client_secret": suno_mcp_client_secret,
            "auth_url": suno_mcp_auth_url,
            "token_url": suno_mcp_token_url,
            "scopes": suno_mcp_scopes,
            "redirect_uri": suno_mcp_redirect_uri,
        }.items()
        if v is not None
    }
    if (
        suno_mcp_url is not None
        or suno_mcp_command is not None
        or suno_mcp_token is not None
        or oauth_fields
    ):
        _ensure_suno_mcp_server(
            suno_url=suno_mcp_url,
            suno_cmd=suno_mcp_command,
            suno_token=suno_mcp_token,
            oauth_payload=oauth_fields or None,
        )
    return providers_catalog()


def output_directory():
    return OUTPUT


def base_url():
    url = settings().get("MUSIC_LOCAL_URL") or "http://127.0.0.1:8015"
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "ACE-Step deve usar uma URL HTTP de loopback sem caminho ou credenciais."
        )
    return url.rstrip("/")


def prepare(report=lambda text: None):
    uv = shutil.which("uv")
    git = shutil.which("git")
    if not uv or not git:
        raise RuntimeError("Instale uv e Git para preparar o motor local.")
    CACHE.mkdir(parents=True, exist_ok=True)
    repo = CACHE / "ace-step"
    flags = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if sys.platform == "win32"
        else {}
    )
    with _lock:
        if not (repo / ".git").exists():
            report("Baixando código oficial do ACE-Step para um ambiente separado…")
            subprocess.run(
                [
                    git,
                    "clone",
                    "--filter=blob:none",
                    "https://github.com/ace-step/ACE-Step-1.5.git",
                    str(repo),
                ],
                check=True,
                capture_output=True,
                timeout=300,
                **flags,
            )
        subprocess.run(
            [git, "-C", str(repo), "checkout", "--detach", REVISION],
            check=True,
            capture_output=True,
            timeout=120,
            **flags,
        )
        report(
            "Instalando dependências do motor local. O download pode ocupar vários GB."
        )
        subprocess.run(
            [uv, "sync", "--project", str(repo), "--python", "3.12"],
            check=True,
            capture_output=True,
            timeout=3600,
            **flags,
        )
    report("Motor instalado. Os pesos serão baixados pelo ACE-Step no primeiro início.")
    return {"installed": True}


def _json(response):
    try:
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"O provedor musical retornou HTTP {response.status_code}. Confira acesso, cotas e credenciais."
            )
        return response.json()
    finally:
        response.close()


def engine(session, progress, cancelled):
    global _engine
    url = base_url()
    key = (
        _token
        if _engine is not None and _engine.poll() is None
        else settings().get("MUSIC_LOCAL_KEY", "")
    )
    headers = {"Authorization": "Bearer " + key} if key else {}
    try:
        health = _json(
            session.get(
                url + "/health", headers=headers, timeout=2, allow_redirects=False
            )
        )
        if health.get("data", {}).get("service") != "ACE-Step API":
            raise RuntimeError("O endereço local não é um motor ACE-Step.")
        return url, headers
    except requests.ConnectionError:
        pass
    with _lock:
        repo = CACHE / "ace-step"
        uv = shutil.which("uv")
        if not uv or not (repo / ".venv").is_dir():
            raise RuntimeError(
                "Prepare o motor local pelo botão Instalar motor local no app Música."
            )
        if _engine is None or _engine.poll() is not None:
            env = os.environ.copy()
            env.update(
                ACESTEP_API_HOST="127.0.0.1",
                ACESTEP_API_PORT=str(urlsplit(url).port or 80),
                ACESTEP_API_KEY=_token,
                ACESTEP_LM_BACKEND="pt",
                ACESTEP_OFFLOAD_TO_CPU="true",
                ACESTEP_USE_FLASH_ATTENTION="false",
                HF_HOME=str(CACHE / "models"),
            )
            log = BASE_DIR / "logs/plugins/Apps/music-engine.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("ab") as stream:
                python = repo / (
                    ".venv/Scripts/python.exe"
                    if sys.platform == "win32"
                    else ".venv/bin/python"
                )
                _engine = subprocess.Popen(
                    [str(python), "-c", "from acestep.api_server import main; main()"],
                    cwd=repo,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if sys.platform == "win32"
                        else {}
                    ),
                )
    headers = {"Authorization": "Bearer " + _token}
    progress("Iniciando ACE-Step e carregando modelos…")
    for _ in range(600):
        if cancelled():
            raise InterruptedError("Geração musical cancelada.")
        if _engine.poll() is not None:
            raise RuntimeError(
                "O motor local encerrou. Consulte o log music-engine.log."
            )
        try:
            _json(
                session.get(
                    url + "/health", headers=headers, timeout=2, allow_redirects=False
                )
            )
            return url, headers
        except (requests.RequestException, RuntimeError):
            time.sleep(2)
    raise RuntimeError("O motor não ficou pronto em 20 minutos. Consulte seus logs.")


def stop_engine():
    global _engine
    with _lock:
        process = _engine
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        _engine = None


atexit.register(stop_engine)


def audio_file(name):
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp3|wav|flac)", name):
        raise ValueError("Áudio inválido.")
    for root in (output_directory(), LEGACY_OUTPUT):
        path = root / name
        if path.is_file() and not path.is_symlink():
            return path
    raise ValueError("Áudio não encontrado.")


def library():
    items = {}
    for root in (LEGACY_OUTPUT, output_directory()):
        if not root.is_dir():
            continue
        for path in root.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{32}\.(mp3|wav|flac)\.json", path.name):
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("file") != path.name[:-5]:
                    continue
                if (root / item["file"]).is_file():
                    items[item["file"]] = {**item, "modified": path.stat().st_mtime}
            except (ValueError, KeyError, OSError):
                continue
    return sorted(items.values(), key=lambda item: item["modified"], reverse=True)[:100]


def generate(
    prompt,
    lyrics="",
    provider=None,
    duration=30,
    progress=lambda text: None,
    cancelled=lambda: False,
):
    if provider is None:
        provider = str(settings().get("MUSIC_PROVIDER") or "local").strip().lower()
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
        raise ValueError("Descrição obrigatória (até 8000 caracteres).")
    if not isinstance(lyrics, str) or len(lyrics) > 16000:
        raise ValueError("Letra inválida.")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int)
        or not 10 <= duration <= 180
    ):
        raise ValueError("Duração deve estar entre 10 e 180 segundos.")
    if provider not in MUSIC_PROVIDERS:
        raise ValueError(
            "Escolha local, gemini ou suno_mcp. Flow Music é usado na interface oficial."
        )
    if not _generation_lock.acquire(blocking=False):
        raise RuntimeError("Já existe uma geração musical em andamento.")
    try:
        if cancelled():
            raise InterruptedError("Geração musical cancelada antes de iniciar.")
        with requests.Session() as session:
            session.trust_env = False
            if provider == "local":
                url, headers = engine(session, progress, cancelled)
                result = _json(
                    session.post(
                        url + "/release_task",
                        headers=headers,
                        json={
                            "prompt": prompt,
                            "lyrics": lyrics or "[Instrumental]",
                            "audio_duration": duration,
                            "batch_size": 1,
                            "audio_format": "mp3",
                            "thinking": False,
                        },
                        timeout=30,
                        allow_redirects=False,
                    )
                )
                identity = result["data"]["task_id"]
                progress("Gerando música localmente…")
                for _ in range(900):
                    if cancelled():
                        raise InterruptedError(
                            "A espera foi cancelada. O motor ACE-Step pode continuar sua tarefa em segundo plano."
                        )
                    response = _json(
                        session.post(
                            url + "/query_result",
                            headers=headers,
                            json={"task_id_list": [identity]},
                            timeout=10,
                            allow_redirects=False,
                        )
                    )
                    rows = response.get("data", [])
                    if rows and rows[0]["status"] == 2:
                        raise RuntimeError(
                            "ACE-Step não conseguiu gerar a música. Consulte o log do motor."
                        )
                    if rows and rows[0]["status"] == 1:
                        result = rows[0]["result"]
                        entries = (
                            json.loads(result) if isinstance(result, str) else result
                        )
                        resource = entries[0]["file"]
                        parsed = urlsplit(resource)
                        if parsed.scheme or parsed.netloc or parsed.path != "/v1/audio":
                            raise RuntimeError(
                                "O motor retornou um endereço de áudio inválido."
                            )
                        response = session.get(
                            url + resource,
                            headers=headers,
                            timeout=60,
                            allow_redirects=False,
                        )
                        try:
                            if response.status_code != 200:
                                raise RuntimeError(
                                    "Não foi possível obter o áudio do motor."
                                )
                            raw = response.content
                        finally:
                            response.close()
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError("O motor musical excedeu 30 minutos.")
                extension = "mp3"
            elif provider == "suno_mcp":
                from src.mcp_chat_tools import call_suno_mcp

                suno_url, suno_cmd, suno_tok = _resolve_suno_mcp_credentials()
                progress("Gerando música via Suno (MCP)…")
                data = call_suno_mcp(
                    prompt,
                    lyrics=lyrics,
                    duration=duration,
                    suno_url=suno_url,
                    suno_cmd=suno_cmd,
                    suno_token=suno_tok,
                )
                if isinstance(data.get("content"), list):
                    for part in data["content"]:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            try:
                                parsed = json.loads(part["text"])
                                if isinstance(parsed, dict):
                                    data = parsed
                                    break
                            except Exception:
                                pass
                if isinstance(data.get("audio_base64"), str):
                    raw = base64.b64decode(data["audio_base64"], validate=True)
                    extension = "wav" if data.get("format") == "wav" else "mp3"
                elif isinstance(data.get("audio_url"), str) and data[
                    "audio_url"
                ].startswith(("http://", "https://")):
                    raw = session.get(
                        data["audio_url"], timeout=120, allow_redirects=False
                    ).content
                    extension = "wav" if data["audio_url"].endswith(".wav") else "mp3"
                else:
                    raise RuntimeError(
                        "Resposta do servidor Suno (MCP) não trouxe áudio."
                    )
            else:
                from src.config import STT_GEMINI_API_KEY

                key = (
                    setting("GEMINI_API_KEY")
                    or setting("AGE_GEMINI_API_KEY")
                    or STT_GEMINI_API_KEY
                )
                if not key:
                    raise RuntimeError(
                        "Configure a chave Gemini da PIA. A autorização Gmail/Drive não concede acesso à API Lyria."
                    )
                progress("Gerando música com Lyria pela API Gemini…")
                data = _json(
                    session.post(
                        "https://generativelanguage.googleapis.com/v1beta/interactions",
                        headers={"x-goog-api-key": key},
                        json={
                            "model": settings().get("MUSIC_GEMINI_MODEL")
                            or "lyria-3.5",
                            "input": f"{prompt}\nTarget duration: {duration} seconds.\n"
                            + (
                                "Lyrics:\n" + lyrics
                                if lyrics
                                else "Instrumental only. No vocals."
                            ),
                        },
                        timeout=600,
                    )
                )
                audios = [
                    content
                    for step in data.get("steps", [])
                    if step.get("type") == "model_output"
                    for content in step.get("content", [])
                    if content.get("type") == "audio"
                ]
                if not audios:
                    raise RuntimeError(
                        "Gemini não retornou áudio. Verifique a disponibilidade do modelo e as cotas de sua API."
                    )
                raw = base64.b64decode(audios[0]["data"], validate=True)
                extension = (
                    "wav" if audios[0].get("mime_type") == "audio/wav" else "mp3"
                )
            if cancelled():
                raise InterruptedError("Geração cancelada antes de salvar o resultado.")
            if not raw or len(raw) > 100 * 1024**2:
                raise RuntimeError("Áudio musical vazio ou maior que 100 MiB.")
            destination = output_directory()
            destination.mkdir(parents=True, exist_ok=True)
            name = uuid.uuid4().hex + "." + extension
            (destination / name).write_bytes(raw)
            result = {
                "file": name,
                "provider": provider,
                "prompt": prompt,
                "lyrics": lyrics,
                "requested_duration": duration,
                "audio_url": "/api/pia/music/files/" + name,
            }
            save_json(destination / (name + ".json"), result)
            from Plugins.Connectors.pia_server.media import enqueue

            enqueue(destination / name)
            return result
    finally:
        try:
            if provider == "local":
                stop_engine()
        finally:
            _generation_lock.release()

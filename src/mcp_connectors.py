"""Custom MCP connectors: STDIO/HTTP Streaming, OAuth, Multi-Account routing & tool discovery."""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from .user_paths import user_path
from .workspace_store import WorkspaceStore

logger = logging.getLogger(__name__)

STORE_KEY = "mcp:custom_servers"
OAUTH_STATE_KEY = "mcp:oauth_states"
OAUTH_STATE_TTL_SECONDS = 900
MCP_PROTOCOL_VERSION = "2025-11-25"
DEFAULT_TOOL_TIMEOUT = 30
# HTTP status codes that mean "this server does not speak the initialize
# handshake" (legacy/stateless endpoints). The call proceeds without a session.
_HANDSHAKE_UNSUPPORTED_STATUS = (400, 404, 405, 501)

SUNO_OAUTH_DEFAULTS = {
    "mcp_url": "https://api.suno.com/mcp",
    "register_url": "https://studio-api-prod.suno.com/api/v2/external/oauth/register/",
    "auth_url": "https://studio-api-prod.suno.com/api/v2/external/oauth/authorize/",
    "token_url": "https://studio-api-prod.suno.com/api/v2/external/oauth/token/",
    "scopes": "api:v0 credits:spend download library:read library:search library:write offline_access profile:read",
    "redirect_uri": "https://pia.travelrpg.com/oauth/callback",
    "client_name": "pia.travelrpg.com",
}


def _is_suno_server(server_id: str, server: dict[str, Any] | None = None) -> bool:
    if (server_id or "").strip() == "suno_mcp":
        return True
    raw_url = str((server or {}).get("url") or "").strip()
    if not raw_url:
        return False
    try:
        return (urlsplit(raw_url).hostname or "").lower() == "api.suno.com"
    except ValueError:
        return False


_ERROR_URL_RE = re.compile(r"https?://[^\s'\"<>]+")
_ERROR_SECRET_RE = re.compile(
    r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"
    r"|\b(access_token|refresh_token|token|api[_-]?key|key|secret|sig|signature|code)=[^&\s'\"]+"
)


def mask_url(url: str) -> str:
    """scheme://host[:port]/path, without userinfo, query or fragment."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return ""
    if not parts.scheme or not parts.hostname:
        return ""
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return f"{parts.scheme}://{netloc}{parts.path}"


def redact_error_text(text: str, limit: int = 300) -> str:
    """Error text safe to persist: URLs masked, bearer/token params removed."""
    out = _ERROR_URL_RE.sub(lambda m: mask_url(m.group(0)) or "<url>", str(text or ""))
    out = _ERROR_SECRET_RE.sub(
        lambda m: (m.group(1) + " ••••") if m.group(1) else (m.group(2) + "=••••"),
        out,
    )
    return out[:limit]


AUTH_ERROR_CODES = ("401", "403")
# JSON-RPC codes some MCP servers use for auth/credits (non-standard range).
_RPC_AUTH_CODES = (-32001, 401, 403)
_RPC_CREDIT_CODES = (402,)
_CREDIT_MESSAGE_RE = re.compile(
    r"insufficient[_ ]credits?|no credits|out of credits|not enough credits"
    r"|credits? (exhausted|insufficient)|payment required|insufficient[_ ]balance",
    re.I,
)


# Conservative: only explicit auth wording in a tool ``isError`` result marks
# the credential as expired ("forbidden"/policy texts do not).
_TOOL_AUTH_ERROR_RE = re.compile(
    r"\bunauthori[sz]ed\b"
    r"|\b(?:invalid|expired|revoked)[_ -]?(?:access[_ -]?|bearer[_ -]?)?token\b"
    r"|\b(?:access[_ -]?)?token[_ -]?(?:has[_ -]?)?(?:expired|invalid|revoked)\b"
    r"|\bnot[_ -]authenticated\b|\bauthentication[_ -](?:failed|required)\b",
    re.I,
)
TOOL_AUTH_ERROR_MESSAGE = "Autorização recusada pela ferramenta MCP (isError)."


def tool_error_text(result: Any) -> str:
    """Text of a tools/call result flagged ``isError`` (for classification only)."""
    if not isinstance(result, dict):
        return ""
    parts = [
        str(part.get("text") or "")
        for part in (result.get("content") or [])
        if isinstance(part, dict)
    ]
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        parts.append(json.dumps(structured, ensure_ascii=False))
    return " ".join(p for p in parts if p)[:2000]


def is_tool_auth_error(result: Any) -> bool:
    return bool(
        isinstance(result, dict)
        and result.get("isError")
        and _TOOL_AUTH_ERROR_RE.search(tool_error_text(result))
    )


class MCPRpcError(RuntimeError):
    """JSON-RPC error returned by an MCP server (keeps the numeric ``code``)."""

    def __init__(self, message: str, code: Any = None):
        super().__init__(message or "Erro MCP")
        self.rpc_code = code


def _rpc_error(error: Any) -> MCPRpcError:
    if isinstance(error, dict):
        return MCPRpcError(str(error.get("message") or "Erro MCP"), error.get("code"))
    return MCPRpcError(str(error or "Erro MCP"))


def keep_if_masked(received: Any, currents: list[Any], masker: Any) -> Any:
    """Round-trip guard for values the UI got masked and sends back unchanged.

    If ``received`` equals ``masker(current)`` for a real current value (and
    differs from it), return the real value instead of the masked one.
    """
    if received is None:
        return None
    value = str(received).strip()
    for current in currents:
        current = str(current or "").strip()
        if current and value != current and value == masker(current):
            return current
    return received


def safe_error(exc: BaseException) -> tuple[str, str]:
    """(code, message) for persisting an error (last_error_code/last_error).

    ``code`` is the HTTP status ("401", "503"...), "timeout", "connection" or
    the exception class name. ``message`` never carries URL query/secrets.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    message = str(exc)
    if isinstance(exc, requests.HTTPError) and status:
        code = str(int(status))
    elif isinstance(exc, MCPRpcError) and (
        exc.rpc_code in _RPC_AUTH_CODES or _TOOL_AUTH_ERROR_RE.search(message)
    ):
        # JSON-RPC authorization error counts as HTTP 401. Conservative rule
        # (same as tool isError): a policy "forbidden" does not expire.
        code = "401"
    elif isinstance(exc, MCPRpcError) and (
        exc.rpc_code in _RPC_CREDIT_CODES or _CREDIT_MESSAGE_RE.search(message)
    ):
        code = "402"
    elif isinstance(exc, (requests.Timeout, subprocess.TimeoutExpired, TimeoutError)):
        code = "timeout"
    elif isinstance(exc, requests.ConnectionError):
        code = "connection"
    else:
        code = type(exc).__name__
    return code, redact_error_text(str(exc))


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


ACCOUNT_MODES = [
    {
        "id": "distributed",
        "label": "Distribuído",
        "description": "Divide as requisições entre as contas ativas (round-robin com fallback automático).",
    },
    {
        "id": "incremental",
        "label": "Incremental",
        "description": "Consulta todas as contas ativas em conjunto e agrega os resultados identificando a conta.",
    },
    {
        "id": "alternating",
        "label": "Alternado",
        "description": "Usa a conta correspondente ao contexto ativo (ex.: Trabalho, Pessoal).",
    },
]

_KNOWN_TOOL_CATALOGS: list[tuple[tuple[str, ...], list[dict[str, Any]]]] = [
    (
        ("suno",),
        [
            {
                "name": "generate_music",
                "description": "Gera música a partir de prompt de estilo, letra opcional e duração.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "lyrics": {"type": "string"},
                        "duration": {"type": "integer"},
                    },
                    "required": ["prompt"],
                },
            },
            {
                "name": "get_credits",
                "description": "Consulta créditos disponíveis na conta Suno.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ],
    ),
    (
        ("dropbox",),
        [
            {
                "name": "list_files",
                "description": "Lista arquivos e pastas em um caminho do Dropbox.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "name": "search_files",
                "description": "Busca arquivos no Dropbox por nome ou conteúdo.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "read_file",
                "description": "Lê o conteúdo de um arquivo no Dropbox.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        ],
    ),
    (
        ("github",),
        [
            {
                "name": "list_repositories",
                "description": "Lista repositórios acessíveis no GitHub.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "search_code",
                "description": "Busca código em repositórios do GitHub.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        ],
    ),
    (
        ("filesystem", "files", "storage", "bucket"),
        [
            {
                "name": "list_directory",
                "description": "Lista arquivos e diretórios disponíveis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "name": "read_file",
                "description": "Lê o conteúdo de um arquivo.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        ],
    ),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str, fallback: str = "mcp") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "").strip().lower()).strip("_")
    return slug[:48] or f"{fallback}_{uuid.uuid4().hex[:6]}"


def _mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def _normalize_kv_list(items: Any) -> list[dict[str, str]]:
    if isinstance(items, dict):
        return [
            {"key": str(k).strip(), "value": str(v)}
            for k, v in items.items()
            if str(k).strip()
        ]
    if not isinstance(items, list):
        return []
    result: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("name") or "").strip()
            if key:
                result.append({"key": key, "value": str(item.get("value") or "")})
    return result


def _normalize_args(args: Any) -> list[str]:
    if isinstance(args, list):
        return [str(a) for a in args if str(a).strip()]
    if isinstance(args, str) and args.strip():
        return shlex.split(args)
    return []


from .core.secrets.vault import MemoryVault as _MemoryVault, get_vault


def _default_vault():
    return get_vault()


def _infer_known_tools(server: dict[str, Any]) -> list[dict[str, Any]]:
    haystack = " ".join(
        [
            str(server.get("id") or ""),
            str(server.get("name") or ""),
            str(server.get("url") or ""),
            str(server.get("command") or ""),
        ]
    ).lower()
    for keywords, tools in _KNOWN_TOOL_CATALOGS:
        if any(kw in haystack for kw in keywords):
            return [dict(t) for t in tools]
    return []


OAUTH_ACCOUNT_REMOVED_MESSAGE = (
    "A conta foi removida durante a conexão OAuth; conecte o Suno de novo."
)


def _with_store_lock(method: Any) -> Any:
    """Run a read-modify-write of the server store under ``_store_lock``.

    Note: start_oauth/complete_oauth may do an OAuth HTTP call (timeout 15 s)
    while holding it; runtime merges of in-flight calls wait meanwhile.
    """

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._store_lock:
            return method(self, *args, **kwargs)

    return wrapper


class MCPConnectorManager:
    def __init__(self, store: WorkspaceStore | None = None, vault: Any = None):
        self.store = store or WorkspaceStore(user_path("workspace.sqlite3"))
        self.vault = vault if vault is not None else _default_vault()
        # Streamable HTTP sessions, keyed by (url, sha256(Authorization)) so each
        # server/account pair has its own Mcp-Session-Id. Never stores the token.
        self._http_sessions: dict[tuple[str, str], dict[str, str]] = {}
        self._http_sessions_lock = threading.Lock()
        # Runtime fields (usage, last_error, rr_cursor, cached_tools) are merged
        # into a fresh read under this lock, never saved from a stale snapshot
        # taken before a long tools/call (review item d).
        self._store_lock = threading.RLock()

    def _vault_key(self, server_id: str, scope: str, field: str) -> str:
        return f"mcp:connector:{server_id}:{scope}:{field}"

    def _get_secret(self, server_id: str, scope: str, field: str) -> str:
        try:
            val = self.vault.get(self._vault_key(server_id, scope, field))
            return str(val) if val else ""
        except Exception:
            return ""

    def _set_secret(self, server_id: str, scope: str, field: str, value: str) -> None:
        key = self._vault_key(server_id, scope, field)
        try:
            if value:
                self.vault.set(key, value)
            elif hasattr(self.vault, "delete"):
                self.vault.delete(key)
        except Exception as exc:
            logger.warning("Failed to store MCP secret for %s: %s", server_id, exc)

    def _raw_servers(self) -> list[dict[str, Any]]:
        data = self.store.get(STORE_KEY, [])
        return data if isinstance(data, list) else []

    def _save_raw_servers(self, servers: list[dict[str, Any]]) -> None:
        self.store.set(STORE_KEY, servers)

    def list_servers(self) -> list[dict[str, Any]]:
        return [self._public_server(s) for s in self._raw_servers()]

    def get_server(self, server_id: str) -> dict[str, Any]:
        raw = self._find_raw(server_id)
        return self._public_server(raw)

    def _find_raw(self, server_id: str) -> dict[str, Any]:
        for s in self._raw_servers():
            if s.get("id") == server_id:
                return s
        raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")

    def find_suno_servers(self) -> list[dict[str, Any]]:
        """Registered servers recognized as Suno (id ``suno_mcp`` or host ``api.suno.com``).

        Returns the raw entries (secrets live in the vault, never here), in the
        stored order. Enabled/disabled filtering is left to the caller.
        """
        return [
            s for s in self._raw_servers() if _is_suno_server(str(s.get("id") or ""), s)
        ]

    def _normalize_account(
        self,
        server_id: str,
        raw_acc: dict[str, Any],
        existing_acc: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        acc_id = str(
            raw_acc.get("id") or (existing_acc or {}).get("id") or uuid.uuid4().hex[:10]
        ).strip()
        acc_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", acc_id) or uuid.uuid4().hex[:10]
        label = str(
            raw_acc.get("name")
            or raw_acc.get("label")
            or (existing_acc or {}).get("name")
            or acc_id
        ).strip()
        context = str(
            raw_acc.get("context")
            if "context" in raw_acc
            else (existing_acc or {}).get("context", "")
        ).strip()
        enabled = bool(
            raw_acc.get("enabled")
            if "enabled" in raw_acc
            else (existing_acc or {}).get("enabled", True)
        )
        bearer_env = str(
            raw_acc.get("bearer_token_env")
            if "bearer_token_env" in raw_acc
            else (existing_acc or {}).get("bearer_token_env", "")
        ).strip()

        # A freshly provided credential clears a stale auth error (last_error),
        # otherwise an "expired" provider would never come back after reconnect.
        new_credential = False
        bearer_plain = raw_acc.get("bearer_token")
        if (
            isinstance(bearer_plain, str)
            and bearer_plain.strip()
            and not bearer_plain.startswith("••••")
        ):
            self._set_secret(server_id, acc_id, "bearer_token", bearer_plain.strip())
            new_credential = True
            has_bearer = True
            bearer_masked = _mask_secret(bearer_plain.strip())
        else:
            stored = self._get_secret(server_id, acc_id, "bearer_token")
            has_bearer = bool(stored)
            bearer_masked = _mask_secret(stored)

        raw_oauth = (
            raw_acc.get("oauth") if isinstance(raw_acc.get("oauth"), dict) else {}
        )
        prev_oauth = (existing_acc or {}).get("oauth") or {}
        if (
            isinstance(raw_oauth.get("client_secret"), str)
            and raw_oauth["client_secret"].strip()
            and not raw_oauth["client_secret"].startswith("••••")
        ):
            self._set_secret(
                server_id,
                acc_id,
                "oauth_client_secret",
                raw_oauth["client_secret"].strip(),
            )
        if (
            isinstance(raw_oauth.get("access_token"), str)
            and raw_oauth["access_token"].strip()
            and not raw_oauth["access_token"].startswith("••••")
        ):
            self._set_secret(
                server_id,
                acc_id,
                "oauth_access_token",
                raw_oauth["access_token"].strip(),
            )
            new_credential = True
        if (
            isinstance(raw_oauth.get("refresh_token"), str)
            and raw_oauth["refresh_token"].strip()
            and not raw_oauth["refresh_token"].startswith("••••")
        ):
            self._set_secret(
                server_id,
                acc_id,
                "oauth_refresh_token",
                raw_oauth["refresh_token"].strip(),
            )

        stored_access = self._get_secret(server_id, acc_id, "oauth_access_token")
        stored_csecret = self._get_secret(server_id, acc_id, "oauth_client_secret")
        oauth_connected = bool(stored_access)
        oauth_cfg = {
            "client_id": str(
                raw_oauth.get("client_id", prev_oauth.get("client_id", ""))
            ).strip(),
            "auth_url": str(
                raw_oauth.get("auth_url", prev_oauth.get("auth_url", ""))
            ).strip(),
            "token_url": str(
                raw_oauth.get("token_url", prev_oauth.get("token_url", ""))
            ).strip(),
            "scopes": str(
                raw_oauth.get("scopes", prev_oauth.get("scopes", ""))
            ).strip(),
            "redirect_uri": str(
                raw_oauth.get("redirect_uri", prev_oauth.get("redirect_uri", ""))
            ).strip(),
            "connected": oauth_connected,
            "has_client_secret": bool(stored_csecret),
            "token_masked": _mask_secret(stored_access),
        }

        auth_type = str(
            raw_acc.get("auth_type")
            or (existing_acc or {}).get("auth_type")
            or (
                "oauth"
                if oauth_cfg["client_id"] or oauth_connected
                else ("bearer" if has_bearer or bearer_env else "none")
            )
        ).strip()
        if auth_type not in ("bearer", "oauth", "headers", "none"):
            auth_type = "none"

        headers = (
            _normalize_kv_list(raw_acc.get("headers"))
            if "headers" in raw_acc
            else list((existing_acc or {}).get("headers") or [])
        )
        env_headers = (
            _normalize_kv_list(raw_acc.get("env_headers"))
            if "env_headers" in raw_acc
            else list((existing_acc or {}).get("env_headers") or [])
        )

        return {
            "id": acc_id,
            "name": label,
            "label": label,
            "context": context,
            "enabled": enabled,
            "auth_type": auth_type,
            "bearer_token_env": bearer_env,
            "has_bearer_token": has_bearer,
            "bearer_token_masked": bearer_masked,
            "headers": headers,
            "env_headers": env_headers,
            "oauth": oauth_cfg,
            "usage_count": int((existing_acc or {}).get("usage_count", 0)),
            "last_used_at": (existing_acc or {}).get("last_used_at"),
            "last_error": None
            if new_credential
            else (existing_acc or {}).get("last_error"),
            "last_error_code": None
            if new_credential
            else (existing_acc or {}).get("last_error_code"),
        }

    @_with_store_lock
    def save_server(
        self, payload: dict[str, Any], server_id: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Payload inválido.")
        servers = self._raw_servers()
        target_id = (server_id or payload.get("id") or "").strip()
        existing = (
            next((s for s in servers if s.get("id") == target_id), None)
            if target_id
            else None
        )

        name = str(payload.get("name") or (existing or {}).get("name") or "").strip()
        if not name:
            raise ValueError("Nome do servidor MCP é obrigatório.")

        if not target_id:
            base = _slugify(name)
            candidate = base
            idx = 2
            used = {s.get("id") for s in servers}
            while candidate in used:
                candidate = f"{base}_{idx}"
                idx += 1
            target_id = candidate
        elif not re.fullmatch(r"[a-zA-Z0-9_-]+", target_id):
            raise ValueError("ID de servidor MCP inválido.")

        transport = str(
            payload.get("transport")
            or payload.get("type")
            or (existing or {}).get("transport")
            or "http_streaming"
        ).strip()
        if transport in ("http", "http-streaming", "streamable_http"):
            transport = "http_streaming"
        if transport not in ("stdio", "http_streaming"):
            raise ValueError(
                "Tipo de transporte inválido. Use 'stdio' ou 'http_streaming'."
            )

        enabled = bool(
            payload.get("enabled")
            if "enabled" in payload
            else (existing or {}).get("enabled", True)
        )

        account_mode = str(
            payload.get("account_mode")
            or (existing or {}).get("account_mode")
            or "distributed"
        ).strip()
        if account_mode not in ("distributed", "incremental", "alternating"):
            raise ValueError("Modo de contas inválido.")

        new_server_credential = False
        bearer_plain = payload.get("bearer_token")
        if (
            isinstance(bearer_plain, str)
            and bearer_plain.strip()
            and not bearer_plain.startswith("••••")
        ):
            self._set_secret(target_id, "_server", "bearer_token", bearer_plain.strip())
            new_server_credential = True
            has_bearer = True
            bearer_masked = _mask_secret(bearer_plain.strip())
        else:
            stored = self._get_secret(target_id, "_server", "bearer_token")
            has_bearer = bool(stored)
            bearer_masked = _mask_secret(stored)

        existing_accounts = {
            a["id"]: a
            for a in ((existing or {}).get("accounts") or [])
            if isinstance(a, dict)
        }
        if "accounts" in payload:
            raw_accounts = payload.get("accounts") or []
            if not isinstance(raw_accounts, list):
                raise ValueError("accounts deve ser uma lista.")
            accounts = [
                self._normalize_account(
                    target_id,
                    acc,
                    existing_accounts.get(str(acc.get("id") or "")),
                )
                for acc in raw_accounts
                if isinstance(acc, dict)
            ]
        else:
            accounts = list((existing or {}).get("accounts") or [])

        cached_tools = (
            payload.get("cached_tools")
            if isinstance(payload.get("cached_tools"), list)
            else list((existing or {}).get("cached_tools") or [])
        )

        record = {
            "id": target_id,
            "name": name,
            "transport": transport,
            "type": transport,
            "enabled": enabled,
            "url": str(
                payload.get("url")
                if "url" in payload
                else (existing or {}).get("url", "")
            ).strip(),
            "bearer_token_env": str(
                payload.get("bearer_token_env")
                if "bearer_token_env" in payload
                else (existing or {}).get("bearer_token_env", "")
            ).strip(),
            "has_bearer_token": has_bearer,
            "bearer_token_masked": bearer_masked,
            "headers": (
                _normalize_kv_list(payload.get("headers"))
                if "headers" in payload
                else list((existing or {}).get("headers") or [])
            ),
            "env_headers": (
                _normalize_kv_list(payload.get("env_headers"))
                if "env_headers" in payload
                else list((existing or {}).get("env_headers") or [])
            ),
            "command": str(
                payload.get("command")
                if "command" in payload
                else (existing or {}).get("command", "")
            ).strip(),
            "args": (
                _normalize_args(payload.get("args"))
                if "args" in payload
                else list((existing or {}).get("args") or [])
            ),
            "cwd": str(
                payload.get("cwd")
                if "cwd" in payload
                else (existing or {}).get("cwd", "")
            ).strip(),
            "env": (
                _normalize_kv_list(payload.get("env"))
                if "env" in payload
                else list((existing or {}).get("env") or [])
            ),
            "account_mode": account_mode,
            "active_context": str(
                payload.get("active_context")
                if "active_context" in payload
                else (existing or {}).get("active_context", "")
            ).strip(),
            "active_account_id": str(
                payload.get("active_account_id")
                if "active_account_id" in payload
                else (existing or {}).get("active_account_id", "")
            ).strip(),
            "accounts": accounts,
            "rr_cursor": int((existing or {}).get("rr_cursor", 0)),
            "cached_tools": cached_tools,
            "last_inspected_at": (existing or {}).get("last_inspected_at"),
            "last_status": (existing or {}).get("last_status", "configured"),
            # Server-level errors survive a re-save; only a new credential clears.
            "last_error": None
            if new_server_credential
            else (existing or {}).get("last_error"),
            "last_error_code": None
            if new_server_credential
            else (existing or {}).get("last_error_code"),
            "updated_at": _now_iso(),
        }

        if existing is not None:
            servers = [record if s.get("id") == target_id else s for s in servers]
        else:
            servers.append(record)
        self._save_raw_servers(servers)
        return self._public_server(record)

    def delete_server(self, server_id: str) -> dict[str, Any]:
        servers = self._raw_servers()
        filtered = [s for s in servers if s.get("id") != server_id]
        if len(filtered) == len(servers):
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")
        self._save_raw_servers(filtered)
        return {"ok": True, "deleted": server_id}

    def _public_server(self, server: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in server.items() if k != "rr_cursor"}
        out["type"] = out.get("transport", "http_streaming")
        sid = str(server.get("id") or "")
        if sid:
            srv_bearer = bool(self._get_secret(sid, "_server", "bearer_token").strip())
            out["has_bearer_token"] = srv_bearer
            if not srv_bearer:
                out["bearer_token_masked"] = ""
            accounts = []
            for acc in server.get("accounts") or []:
                acc_copy = dict(acc)
                acc_id = str(acc_copy.get("id") or "")
                oauth_tok = self._get_secret(sid, acc_id, "oauth_access_token").strip()
                acc_bearer = self._get_secret(sid, acc_id, "bearer_token").strip()
                acc_copy["has_bearer_token"] = bool(acc_bearer)
                if isinstance(acc_copy.get("oauth"), dict):
                    oauth_copy = dict(acc_copy["oauth"])
                    oauth_copy["connected"] = bool(oauth_tok)
                    if not oauth_tok:
                        oauth_copy["token_masked"] = ""
                    acc_copy["oauth"] = oauth_copy
                accounts.append(acc_copy)
            out["accounts"] = accounts
        return out

    def _resolve_credentials(
        self, server: dict[str, Any], account: dict[str, Any] | None = None
    ) -> tuple[dict[str, str], dict[str, str]]:
        headers: dict[str, str] = {}
        env_vars: dict[str, str] = {}

        for item in server.get("headers") or []:
            headers[item["key"]] = item["value"]
        for item in server.get("env_headers") or []:
            env_val = os.environ.get(item["value"], "")
            if env_val:
                headers[item["key"]] = env_val
        for item in server.get("env") or []:
            env_vars[item["key"]] = item["value"]

        srv_bearer = self._get_secret(server["id"], "_server", "bearer_token")
        if not srv_bearer and server.get("bearer_token_env"):
            srv_bearer = os.environ.get(server["bearer_token_env"], "")
        if srv_bearer:
            headers["Authorization"] = f"Bearer {srv_bearer}"

        if account:
            acc_id = account["id"]
            for item in account.get("headers") or []:
                headers[item["key"]] = item["value"]
            for item in account.get("env_headers") or []:
                env_val = os.environ.get(item["value"], "")
                if env_val:
                    headers[item["key"]] = env_val
            acc_token = self._get_secret(server["id"], acc_id, "oauth_access_token")
            if not acc_token:
                acc_token = self._get_secret(server["id"], acc_id, "bearer_token")
            if not acc_token and account.get("bearer_token_env"):
                acc_token = os.environ.get(account["bearer_token_env"], "")
            if acc_token:
                headers["Authorization"] = f"Bearer {acc_token}"

        return headers, env_vars

    @staticmethod
    def _http_session_key(url: str, headers: dict[str, str]) -> tuple[str, str]:
        auth = str(headers.get("Authorization") or "")
        return url, hashlib.sha256(auth.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _response_header(resp: Any, name: str) -> str:
        headers = getattr(resp, "headers", None) or {}
        try:
            value = headers.get(name)
        except Exception:
            value = None
        if value is None:
            lname = name.lower()
            for key, val in dict(headers).items():
                if str(key).lower() == lname:
                    value = val
                    break
        return str(value or "").strip()

    @staticmethod
    def _parse_rpc_response(resp: Any, req_id: int) -> dict[str, Any]:
        content_type = (
            MCPConnectorManager._response_header(resp, "Content-Type")
        ).lower()
        if "text/event-stream" in content_type:
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict) and (
                        parsed.get("id") == req_id
                        or "result" in parsed
                        or "error" in parsed
                    ):
                        if "error" in parsed:
                            raise _rpc_error(parsed["error"])
                        return parsed.get("result") or {}
            return {}
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise _rpc_error(data["error"])
        if isinstance(data, dict) and "result" in data:
            return data["result"] or {}
        return data if isinstance(data, dict) else {}

    def _http_initialize(
        self, url: str, headers: dict[str, str], *, timeout: float
    ) -> dict[str, str]:
        """Streamable HTTP handshake: initialize + notifications/initialized.

        Backwards compatible: servers that reject ``initialize`` with
        400/404/405/501 are treated as stateless, and servers that answer without
        ``Mcp-Session-Id`` simply get no session header. 401/403 and network
        errors propagate (no silent fallback).
        """
        base = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        }
        resp = requests.post(
            url,
            headers=base,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "pia", "version": "1.0.0"},
                },
            },
            timeout=timeout,
            allow_redirects=False,
        )
        status = int(getattr(resp, "status_code", 200) or 200)
        if status in _HANDSHAKE_UNSUPPORTED_STATUS:
            logger.debug(
                "MCP initialize respondeu HTTP %s em %s; seguindo sem sessão.",
                status,
                mask_url(url),
            )
            return {"session_id": "", "protocol_version": "", "mode": "stateless"}
        resp.raise_for_status()
        session_id = self._response_header(resp, "Mcp-Session-Id")
        protocol_version = ""
        try:
            result = self._parse_rpc_response(resp, 1)
            protocol_version = str(result.get("protocolVersion") or "").strip()
        except Exception:
            protocol_version = ""
        notif_headers = dict(base)
        if session_id:
            notif_headers["Mcp-Session-Id"] = session_id
        if protocol_version:
            notif_headers["MCP-Protocol-Version"] = protocol_version
        notif = requests.post(
            url,
            headers=notif_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=timeout,
            allow_redirects=False,
        )
        if int(getattr(notif, "status_code", 202) or 202) in (401, 403):
            notif.raise_for_status()
        return {
            "session_id": session_id,
            "protocol_version": protocol_version,
            "mode": "session" if session_id else "stateless",
        }

    def _http_session(
        self,
        url: str,
        headers: dict[str, str],
        *,
        timeout: float,
        refresh: bool = False,
    ) -> dict[str, str]:
        key = self._http_session_key(url, headers)
        with self._http_sessions_lock:
            cached = None if refresh else self._http_sessions.get(key)
        if cached is not None:
            return cached
        session = self._http_initialize(url, headers, timeout=min(timeout, 30))
        with self._http_sessions_lock:
            self._http_sessions[key] = session
        return session

    def _rpc_http(
        self,
        url: str,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
        *,
        req_id: int = 1,
        timeout: float = 15,
    ) -> dict[str, Any]:
        def post(session: dict[str, str]) -> Any:
            req_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **headers,
            }
            if session.get("session_id"):
                req_headers["Mcp-Session-Id"] = session["session_id"]
            if session.get("protocol_version"):
                req_headers["MCP-Protocol-Version"] = session["protocol_version"]
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            return requests.post(
                url,
                headers=req_headers,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
            )

        session = self._http_session(url, headers, timeout=timeout)
        resp = post(session)
        if int(getattr(resp, "status_code", 200) or 200) == 404 and session.get(
            "session_id"
        ):
            # Spec: 404 with a session id means the session expired and the
            # request was not processed. Re-handshake exactly once.
            session = self._http_session(url, headers, timeout=timeout, refresh=True)
            resp = post(session)
        resp.raise_for_status()
        return self._parse_rpc_response(resp, req_id)

    def _rpc_stdio(
        self,
        server: dict[str, Any],
        method: str,
        params: dict[str, Any],
        env_vars: dict[str, str],
        *,
        timeout: float = 15,
    ) -> dict[str, Any]:
        command = str(server.get("command") or "").strip()
        if not command:
            raise RuntimeError("Comando STDIO não configurado.")
        args = [command, *(server.get("args") or [])]
        msgs = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pia", "version": "1.0.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": method, "params": params},
        ]
        stdin_payload = "\n".join(json.dumps(m) for m in msgs) + "\n"
        env = {**os.environ, **env_vars} if env_vars else None
        cwd = server.get("cwd") or None
        proc = subprocess.run(
            args,
            input=stdin_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        for line in reversed(proc.stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if parsed.get("id") == 2:
                    if "error" in parsed:
                        raise _rpc_error(parsed["error"])
                    return parsed.get("result") or {}
            except json.JSONDecodeError:
                continue
        raise RuntimeError(
            proc.stderr.strip()
            or "Servidor MCP STDIO não retornou resposta JSON-RPC válida."
        )

    def _exec_single(
        self,
        server: dict[str, Any],
        account: dict[str, Any] | None,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = DEFAULT_TOOL_TIMEOUT,
    ) -> dict[str, Any]:
        timeout = timeout or DEFAULT_TOOL_TIMEOUT
        headers, env_vars = self._resolve_credentials(server, account)
        if server.get("transport") == "stdio":
            return self._rpc_stdio(server, method, params, env_vars, timeout=timeout)
        url = str(server.get("url") or "").strip()
        if not url:
            raise RuntimeError("URL do servidor MCP não configurada.")
        return self._rpc_http(url, method, params, headers, req_id=2, timeout=timeout)

    def inspect_server(self, server_id: str) -> dict[str, Any]:
        servers = self._raw_servers()
        server = next((s for s in servers if s.get("id") == server_id), None)
        if server is None:
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")

        active_accounts = [
            a for a in (server.get("accounts") or []) if a.get("enabled", True)
        ]
        target_account = active_accounts[0] if active_accounts else None
        connection_error: str | None = None
        tools: list[dict[str, Any]] = []
        status = "configured"

        try:
            res = self._exec_single(server, target_account, "tools/list", {}, timeout=5)
            raw_tools = res.get("tools") if isinstance(res, dict) else []
            if isinstance(raw_tools, list):
                tools = [
                    {
                        "name": str(t.get("name") or ""),
                        "description": str(t.get("description") or ""),
                        "inputSchema": t.get("inputSchema")
                        or {"type": "object", "properties": {}},
                    }
                    for t in raw_tools
                    if isinstance(t, dict) and t.get("name")
                ]
            status = "online"
            server["cached_tools"] = tools
        except Exception as exc:
            connection_error = safe_error(exc)[1]
            status = "offline"
            tools = list(server.get("cached_tools") or [])
            if not tools:
                tools = _infer_known_tools(server)

        server["last_inspected_at"] = _now_iso()
        server["last_status"] = status
        self._save_raw_servers(servers)

        return {
            "server_id": server["id"],
            "name": server["name"],
            "transport": server["transport"],
            "status": status,
            "account_mode": server.get("account_mode", "distributed"),
            "active_context": server.get("active_context", ""),
            "accounts_summary": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "context": a.get("context", ""),
                    "enabled": a.get("enabled", True),
                    "auth_type": a.get("auth_type", "none"),
                    "usage_count": a.get("usage_count", 0),
                }
                for a in (server.get("accounts") or [])
            ],
            "tools": tools,
            "connection_error": connection_error,
        }

    @staticmethod
    def _record_outcome(target: dict[str, Any], exc: BaseException | None) -> None:
        if exc is None:
            target["last_error"] = None
            target["last_error_code"] = None
            return
        code, message = safe_error(exc)
        if (
            str(target.get("last_error_code") or "") in AUTH_ERROR_CODES
            and code not in AUTH_ERROR_CODES
        ):
            # An expired credential stays expired until a success or a new
            # credential; a timeout/5xx afterwards must not hide it.
            return
        target["last_error"] = message
        target["last_error_code"] = code

    def _merge_runtime(
        self, server_id: str, account_id: str | None, apply: Any
    ) -> None:
        """Apply ``apply(target)`` to the fresh stored server/account and save."""
        with self._store_lock:
            servers = self._raw_servers()
            server = next((s for s in servers if s.get("id") == server_id), None)
            if server is None:
                return
            target: dict[str, Any] | None = server
            if account_id is not None:
                target = next(
                    (
                        a
                        for a in (server.get("accounts") or [])
                        if a.get("id") == account_id
                    ),
                    None,
                )
            if target is None:
                return
            apply(target)
            self._save_raw_servers(servers)

    def _advance_cursor(self, server_id: str, n_accounts: int) -> int:
        """Read and advance ``rr_cursor`` atomically; returns the cursor used."""
        used = {"cursor": 0}

        def apply(server: dict[str, Any]) -> None:
            cursor = int(server.get("rr_cursor", 0)) % max(1, n_accounts)
            used["cursor"] = cursor
            server["rr_cursor"] = (cursor + 1) % max(1, n_accounts)

        self._merge_runtime(server_id, None, apply)
        return used["cursor"]

    def _load_server(
        self, server_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        servers = self._raw_servers()
        server = next((s for s in servers if s.get("id") == server_id), None)
        if server is None:
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")
        if not server.get("enabled", True):
            raise RuntimeError(f"Servidor MCP '{server['name']}' está desabilitado.")
        accounts = [a for a in (server.get("accounts") or []) if a.get("enabled", True)]
        return servers, server, accounts

    @staticmethod
    def _pinned_account(
        accounts: list[dict[str, Any]], account_id: str
    ) -> dict[str, Any]:
        acc = next((a for a in accounts if a.get("id") == account_id), None)
        if acc is None:
            raise KeyError(f"Conta MCP '{account_id}' não encontrada ou desabilitada.")
        return acc

    def _alternating_account(
        self,
        server: dict[str, Any],
        accounts: list[dict[str, Any]],
        req_account_id: Any = None,
        req_context: Any = None,
    ) -> dict[str, Any]:
        def by_context(ctx: Any) -> dict[str, Any] | None:
            ctx_norm = str(ctx).strip().lower()
            return next(
                (
                    a
                    for a in accounts
                    if (a.get("context") or "").strip().lower() == ctx_norm
                ),
                None,
            )

        selected = None
        if req_account_id:
            selected = next((a for a in accounts if a["id"] == req_account_id), None)
        if selected is None and req_context:
            selected = by_context(req_context)
        if selected is None and server.get("active_account_id"):
            selected = next(
                (a for a in accounts if a["id"] == server["active_account_id"]),
                None,
            )
        if selected is None and server.get("active_context"):
            selected = by_context(server["active_context"])
        return selected or accounts[0]

    def select_account(self, server_id: str) -> str | None:
        """Pick (and pin) the account a multi-step operation should use.

        distributed: the round-robin account (cursor advances once);
        alternating: context/active account; incremental: first account.
        Returns ``None`` when the server has no accounts (server credential).
        """
        servers, server, accounts = self._load_server(server_id)
        if not accounts:
            return None
        mode = server.get("account_mode", "distributed")
        if mode == "alternating":
            return self._alternating_account(server, accounts)["id"]
        if mode == "distributed":
            return accounts[self._advance_cursor(server_id, len(accounts))]["id"]
        return accounts[0]["id"]

    def _exec_recorded(
        self,
        server: dict[str, Any],
        account: dict[str, Any] | None,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None,
        count_usage: bool = True,
    ) -> Any:
        server_id = str(server.get("id") or "")
        account_id = str(account["id"]) if account is not None else None
        try:
            res = self._exec_single(server, account, method, params, timeout=timeout)
        except Exception as exc:
            self._merge_runtime(
                server_id, account_id, lambda t, err=exc: self._record_outcome(t, err)
            )
            raise

        auth_refused = method == "tools/call" and is_tool_auth_error(res)

        def ok(target: dict[str, Any]) -> None:
            if account_id is not None and count_usage:
                target["usage_count"] = int(target.get("usage_count", 0)) + 1
                target["last_used_at"] = _now_iso()
            if auth_refused:
                # Only the code + a fixed message; never the raw tool text.
                target["last_error"] = TOOL_AUTH_ERROR_MESSAGE
                target["last_error_code"] = "401"
            else:
                self._record_outcome(target, None)

        self._merge_runtime(server_id, account_id, ok)
        return res

    def list_tools(
        self,
        server_id: str,
        *,
        timeout: float | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run tools/list (pinned account or the first active one) and cache it.

        Unlike ``inspect_server`` it raises on failure instead of falling back
        to inferred catalogs. Errors are recorded (last_error_code) so a 401
        marks the credential as expired; success clears it.
        """
        _servers, server, accounts = self._load_server(server_id)
        account = (
            self._pinned_account(accounts, account_id)
            if account_id
            else (accounts[0] if accounts else None)
        )
        res = self._exec_recorded(
            server, account, "tools/list", {}, timeout=timeout, count_usage=False
        )
        raw_tools = res.get("tools") if isinstance(res, dict) else []
        tools = [
            {
                "name": str(t.get("name") or ""),
                "description": str(t.get("description") or ""),
                "inputSchema": t.get("inputSchema")
                or {"type": "object", "properties": {}},
            }
            for t in (raw_tools if isinstance(raw_tools, list) else [])
            if isinstance(t, dict) and t.get("name")
        ]

        def cache(target: dict[str, Any]) -> None:
            target["cached_tools"] = tools
            target["last_inspected_at"] = _now_iso()
            target["last_status"] = "online"

        self._merge_runtime(server_id, None, cache)
        return tools

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        retry_other_accounts: bool = True,
        account_id: str | None = None,
    ) -> Any:
        """Call ``tool_name`` on ``server_id``.

        ``timeout`` overrides the default per-request timeout (30 s).
        ``retry_other_accounts=False`` uses exactly one account in any mode
        (no distributed fallback, no incremental fan-out), for paid or
        non-idempotent tools. ``account_id`` pins that account (implies a
        single call, no cursor rotation). Runtime fields are merged into the
        store after the call (no stale snapshot is saved).
        """
        _servers, server, accounts = self._load_server(server_id)
        args = dict(arguments or {})
        req_account_id = args.pop("_account_id", None)
        req_context = args.pop("_account_context", None)
        params = {"name": tool_name, "arguments": args}
        mode = server.get("account_mode", "distributed")

        def single(account: dict[str, Any] | None) -> Any:
            return self._exec_recorded(
                server, account, "tools/call", params, timeout=timeout
            )

        if account_id:
            return single(self._pinned_account(accounts, account_id))
        if not accounts:
            return single(None)
        if mode == "alternating":
            return single(
                self._alternating_account(server, accounts, req_account_id, req_context)
            )
        if not retry_other_accounts:
            if mode == "distributed":
                return single(accounts[self._advance_cursor(server_id, len(accounts))])
            return single(accounts[0])

        if mode == "incremental":
            aggregated = []
            for acc in accounts:
                entry = {
                    "account_id": acc["id"],
                    "account_name": acc["name"],
                    "context": acc.get("context", ""),
                }
                try:
                    res = single(acc)
                    aggregated.append({**entry, "ok": True, "result": res})
                except Exception as exc:
                    aggregated.append(
                        {**entry, "ok": False, "error": safe_error(exc)[1]}
                    )
            return {"mode": "incremental", "results": aggregated}

        # Default: distributed (round-robin with automatic fallback on failure)
        cursor = self._advance_cursor(server_id, len(accounts))
        ordered = accounts[cursor:] + accounts[:cursor]
        last_exc: Exception | None = None
        for acc in ordered:
            try:
                return single(acc)
            except Exception as exc:
                last_exc = exc
        raise last_exc or RuntimeError(
            "Nenhuma conta MCP ativa conseguiu executar a ferramenta."
        )

    def start_oauth(
        self,
        server_id: str,
        account_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare/persist OAuth config and return the authorization URL.

        The Suno dynamic client registration (HTTP) runs OUTSIDE
        ``_store_lock``: read/prepare under the lock, release it, POST, then
        re-acquire and merge (client_id only if still empty).
        """
        payload = payload or {}
        with self._store_lock:
            servers, server, acc, account_id = self._oauth_prepare_account(
                server_id, account_id, payload
            )
            oauth = acc.setdefault("oauth", {})
            need_dcr = (
                _is_suno_server(server_id, server)
                and not str(oauth.get("client_id") or "").strip()
                and not payload.get("access_token")
            )
            if not need_dcr:
                return self._oauth_finish_start(
                    servers, server, acc, account_id, payload
                )
            redirect_uri = str(oauth.get("redirect_uri") or "")
            self._save_raw_servers(servers)

        cid = self._register_suno_client(redirect_uri)  # no lock held

        with self._store_lock:
            servers = self._raw_servers()
            try:
                server, acc = self._find_server_account(servers, server_id, account_id)
            except KeyError:
                raise ValueError(OAUTH_ACCOUNT_REMOVED_MESSAGE) from None
            oauth = acc.setdefault("oauth", {})
            # If another writer filled client_id during the DCR, it wins. The
            # client registered here then stays unused at the Suno: it is a
            # public client (PKCE, no secret) and there is no API to delete it.
            if not str(oauth.get("client_id") or "").strip():
                oauth["client_id"] = cid
            return self._oauth_finish_start(servers, server, acc, account_id, payload)

    @staticmethod
    def _find_server_account(
        servers: list[dict[str, Any]], server_id: str, account_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        server = next((s for s in servers if s.get("id") == server_id), None)
        if server is None:
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")
        acc = next(
            (a for a in (server.get("accounts") or []) if a.get("id") == account_id),
            None,
        )
        if acc is None:
            raise KeyError(
                f"Conta '{account_id}' não encontrada no servidor '{server_id}'."
            )
        return server, acc

    @staticmethod
    def _register_suno_client(redirect_uri: str) -> str:
        """Suno dynamic client registration (DCR). Never call under the lock."""
        reg_resp = requests.post(
            SUNO_OAUTH_DEFAULTS["register_url"],
            json={
                "client_name": SUNO_OAUTH_DEFAULTS["client_name"],
                "redirect_uris": [redirect_uri],
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        reg_resp.raise_for_status()
        reg_data = reg_resp.json() if reg_resp.content else {}
        cid = str((reg_data or {}).get("client_id") or "").strip()
        if not cid:
            raise ValueError("Registro dinâmico (DCR) do Suno não retornou client_id.")
        return cid

    def _oauth_prepare_account(
        self, server_id: str, account_id: str | None, payload: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
        """Resolve/create the account and apply payload + Suno defaults.

        Caller must hold ``_store_lock``. No network I/O.
        """
        servers = self._raw_servers()
        server = next((s for s in servers if s.get("id") == server_id), None)
        if server is None:
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")

        accounts = server.get("accounts") or []
        if not account_id:
            if accounts:
                account_id = accounts[0]["id"]
            else:
                new_acc = self._normalize_account(
                    server_id,
                    {
                        "name": payload.get("name") or f"{server['name']} OAuth",
                        "auth_type": "oauth",
                    },
                )
                accounts.append(new_acc)
                server["accounts"] = accounts
                account_id = new_acc["id"]

        acc = next((a for a in accounts if a["id"] == account_id), None)
        if acc is None:
            raise KeyError(
                f"Conta '{account_id}' não encontrada no servidor '{server_id}'."
            )

        oauth = acc.setdefault("oauth", {})
        for field in ("client_id", "auth_url", "token_url", "scopes", "redirect_uri"):
            if payload.get(field):
                value = str(payload[field]).strip()
                if field in ("auth_url", "token_url"):
                    # The UI shows these masked; never overwrite the real URL.
                    value = str(
                        keep_if_masked(value, [oauth.get(field)], mask_url)
                    ).strip()
                oauth[field] = value
        if payload.get("client_secret"):
            self._set_secret(
                server_id,
                account_id,
                "oauth_client_secret",
                str(payload["client_secret"]).strip(),
            )
            oauth["has_client_secret"] = True

        if _is_suno_server(server_id, server):
            for field in ("auth_url", "token_url", "scopes", "redirect_uri"):
                if not str(oauth.get(field) or "").strip():
                    oauth[field] = SUNO_OAUTH_DEFAULTS[field]
        return servers, server, acc, account_id

    def _oauth_finish_start(
        self,
        servers: list[dict[str, Any]],
        server: dict[str, Any],
        acc: dict[str, Any],
        account_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Direct token or PKCE state + auth URL. Caller holds ``_store_lock``."""
        server_id = str(server.get("id") or "")
        oauth = acc.setdefault("oauth", {})
        if payload.get("access_token"):
            token = str(payload["access_token"]).strip()
            self._set_secret(server_id, account_id, "oauth_access_token", token)
            oauth["connected"] = True
            oauth["token_masked"] = _mask_secret(token)
            acc["auth_type"] = "oauth"
            acc["last_error"] = None
            acc["last_error_code"] = None
            self._save_raw_servers(servers)
            return {"ok": True, "auth_url": oauth.get("auth_url", ""), "account": acc}

        code_verifier, code_challenge = _generate_pkce_pair()
        state = uuid.uuid4().hex
        states = self.store.get(OAUTH_STATE_KEY, {})
        if not isinstance(states, dict):
            states = {}
        states[state] = {
            "server_id": server_id,
            "account_id": account_id,
            "code_verifier": code_verifier,
            "redirect_uri": oauth.get("redirect_uri", ""),
            "created_at": _now_iso(),
        }
        self.store.set(OAUTH_STATE_KEY, states)

        base_auth = (
            oauth.get("auth_url")
            or server.get("url")
            or "https://localhost/oauth/authorize"
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": oauth.get("client_id", ""),
                "redirect_uri": oauth.get("redirect_uri", ""),
                "scope": oauth.get("scopes", ""),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        sep = "&" if "?" in base_auth else "?"
        auth_url = f"{base_auth}{sep}{query}"
        self._save_raw_servers(servers)
        return {"ok": True, "state": state, "auth_url": auth_url, "account": acc}

    def complete_oauth(
        self,
        server_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finish OAuth: consume ``state`` atomically, exchange the code OUTSIDE
        ``_store_lock`` and merge only the token fields afterwards."""
        payload = payload or {}
        req_account_id = str(payload.get("account_id") or "").strip()
        state = str(payload.get("state") or "").strip()
        token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        code = str(payload.get("code") or "").strip()

        code_verifier = ""
        state_redirect_uri = ""
        account_id = req_account_id

        if code and not token:
            if not state:
                raise ValueError("State OAuth ausente ou inválido.")

        with self._store_lock:
            # 1st locked section: the state is popped here, so a duplicated
            # callback can never reuse the same code.
            if state:
                states = self.store.get(OAUTH_STATE_KEY, {})
                info = states.pop(state, None) if isinstance(states, dict) else None
                if info is not None:
                    self.store.set(OAUTH_STATE_KEY, states)
                if not isinstance(info, dict):
                    raise ValueError("State OAuth inválido ou já utilizado.")
                if str(info.get("server_id") or "") != server_id:
                    raise ValueError("State OAuth não pertence a este servidor MCP.")
                state_account_id = str(info.get("account_id") or "").strip()
                if (
                    req_account_id
                    and state_account_id
                    and req_account_id != state_account_id
                ):
                    raise ValueError("State OAuth não pertence à conta informada.")
                created_raw = str(info.get("created_at") or "").strip()
                if not created_raw:
                    raise ValueError("State OAuth expirado ou inválido.")
                try:
                    created_dt = datetime.fromisoformat(created_raw)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - created_dt).total_seconds()
                except ValueError as exc:
                    raise ValueError("State OAuth expirado ou inválido.") from exc
                if age < 0 or age > OAUTH_STATE_TTL_SECONDS:
                    raise ValueError("State OAuth expirado.")
                account_id = account_id or state_account_id
                code_verifier = str(info.get("code_verifier") or "").strip()
                state_redirect_uri = str(info.get("redirect_uri") or "").strip()

            servers = self._raw_servers()
            _server, acc = self._find_server_account(servers, server_id, account_id)
            oauth_cfg = dict(acc.get("oauth") or {})

        # Token exchange (HTTP) and vault writes happen without the lock.
        if not token and code and oauth_cfg.get("token_url"):
            token_url = str(oauth_cfg["token_url"]).strip()
            client_secret = self._get_secret(
                server_id, account_id, "oauth_client_secret"
            )
            form_data = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": str(oauth_cfg.get("client_id") or ""),
            }
            if client_secret:
                form_data["client_secret"] = client_secret
            redirect_uri = (
                state_redirect_uri or str(oauth_cfg.get("redirect_uri") or "").strip()
            )
            if redirect_uri:
                form_data["redirect_uri"] = redirect_uri
            if code_verifier:
                form_data["code_verifier"] = code_verifier
            resp = requests.post(
                token_url,
                data=form_data,
                headers={"Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            token_data = resp.json() if resp.content else {}
            if isinstance(token_data, dict):
                token = str(token_data.get("access_token") or "").strip()
                if not refresh_token and token_data.get("refresh_token"):
                    refresh_token = str(token_data["refresh_token"]).strip()
            if not token:
                raise ValueError("Endpoint OAuth não retornou access_token.")
        elif not token and code:
            raise ValueError(
                "token_url OAuth não configurado para trocar o código por access_token."
            )
        if not token:
            raise ValueError("Token OAuth ausente.")
        self._set_secret(server_id, account_id, "oauth_access_token", token)
        if refresh_token:
            self._set_secret(
                server_id,
                account_id,
                "oauth_refresh_token",
                refresh_token,
            )

        removed = False
        with self._store_lock:
            # 2nd locked section: merge only token fields into a fresh read.
            servers = self._raw_servers()
            try:
                _server, acc = self._find_server_account(servers, server_id, account_id)
            except KeyError:
                removed = True
            else:
                oauth = acc.setdefault("oauth", {})
                oauth["connected"] = True
                oauth["token_masked"] = _mask_secret(token)
                acc["auth_type"] = "oauth"
                acc["last_error"] = None
                acc["last_error_code"] = None
                self._save_raw_servers(servers)
        if removed:
            # Account removed during the HTTP exchange: drop the orphan tokens
            # (vault writes stay outside the lock) and fail cleanly.
            self._set_secret(server_id, account_id, "oauth_access_token", "")
            self._set_secret(server_id, account_id, "oauth_refresh_token", "")
            raise ValueError(OAUTH_ACCOUNT_REMOVED_MESSAGE)
        return {"ok": True, "account": acc}

    def chat_tool_specs(self) -> list[dict[str, Any]]:
        """Expose enabled custom MCP server tools in OpenAI/MCP tool format."""
        specs: list[dict[str, Any]] = []
        for server in self._raw_servers():
            if not server.get("enabled", True):
                continue
            tools = server.get("cached_tools") or _infer_known_tools(server)
            for tool in tools:
                tname = str(tool.get("name") or "").strip()
                if not tname:
                    continue
                safe_name = re.sub(
                    r"[^a-zA-Z0-9_-]+", "_", f"mcp_{server['id']}__{tname}"
                )[:64]
                schema = dict(
                    tool.get("inputSchema") or {"type": "object", "properties": {}}
                )
                specs.append(
                    {
                        "name": safe_name,
                        "server_id": server["id"],
                        "server_name": server["name"],
                        "tool_name": tname,
                        "description": f"[{server['name']}] {tool.get('description') or tname}",
                        "inputSchema": schema,
                    }
                )
        return specs


_manager: MCPConnectorManager | None = None


def get_mcp_manager() -> MCPConnectorManager:
    global _manager
    if _manager is None:
        _manager = MCPConnectorManager()
    return _manager

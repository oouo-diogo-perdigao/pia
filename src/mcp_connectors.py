"""Custom MCP connectors: STDIO/HTTP Streaming, OAuth, Multi-Account routing & tool discovery."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from .user_paths import user_path
from .workspace_store import WorkspaceStore

logger = logging.getLogger(__name__)

STORE_KEY = "mcp:custom_servers"
OAUTH_STATE_KEY = "mcp:oauth_states"

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


class _MemoryVault:
    """In-memory fallback vault used only when OS keyring is unavailable in tests."""

    def __init__(self):
        self._data: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        return self._data.get(name)

    def set(self, name: str, value: Any) -> None:
        self._data[name] = value

    def delete(self, name: str) -> None:
        self._data.pop(name, None)


def _default_vault():
    try:
        from .settings_store import get_store

        return get_store().vault
    except Exception:
        return _MemoryVault()


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


class MCPConnectorManager:
    def __init__(self, store: WorkspaceStore | None = None, vault: Any = None):
        self.store = store or WorkspaceStore(user_path("workspace.sqlite3"))
        self.vault = vault if vault is not None else _default_vault()

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

        bearer_plain = raw_acc.get("bearer_token")
        if (
            isinstance(bearer_plain, str)
            and bearer_plain.strip()
            and not bearer_plain.startswith("••••")
        ):
            self._set_secret(server_id, acc_id, "bearer_token", bearer_plain.strip())
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
        oauth_connected = bool(
            raw_oauth.get("connected")
            if "connected" in raw_oauth
            else (stored_access or prev_oauth.get("connected", False))
        )
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
            "last_error": (existing_acc or {}).get("last_error"),
        }

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

        bearer_plain = payload.get("bearer_token")
        if (
            isinstance(bearer_plain, str)
            and bearer_plain.strip()
            and not bearer_plain.startswith("••••")
        ):
            self._set_secret(target_id, "_server", "bearer_token", bearer_plain.strip())
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

    def _rpc_http(
        self,
        url: str,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
        *,
        req_id: int = 1,
        timeout: int = 15,
    ) -> dict[str, Any]:
        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        }
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        resp = requests.post(
            url,
            headers=req_headers,
            json=payload,
            timeout=timeout,
            allow_redirects=False,
        )
        resp.raise_for_status()
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in content_type:
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(chunk)
                        if isinstance(parsed, dict) and (
                            parsed.get("id") == req_id
                            or "result" in parsed
                            or "error" in parsed
                        ):
                            if "error" in parsed:
                                raise RuntimeError(
                                    parsed["error"].get("message", "Erro MCP")
                                )
                            return parsed.get("result") or {}
                    except json.JSONDecodeError:
                        continue
            return {}
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(data["error"].get("message", "Erro MCP"))
        if isinstance(data, dict) and "result" in data:
            return data["result"] or {}
        return data if isinstance(data, dict) else {}

    def _rpc_stdio(
        self,
        server: dict[str, Any],
        method: str,
        params: dict[str, Any],
        env_vars: dict[str, str],
        *,
        timeout: int = 15,
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
                        raise RuntimeError(parsed["error"].get("message", "Erro MCP"))
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
        timeout: int = 30,
    ) -> dict[str, Any]:
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
            connection_error = str(exc)
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

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        servers = self._raw_servers()
        server = next((s for s in servers if s.get("id") == server_id), None)
        if server is None:
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")
        if not server.get("enabled", True):
            raise RuntimeError(f"Servidor MCP '{server['name']}' está desabilitado.")

        args = dict(arguments or {})
        req_account_id = args.pop("_account_id", None)
        req_context = args.pop("_account_context", None)

        accounts = [a for a in (server.get("accounts") or []) if a.get("enabled", True)]
        mode = server.get("account_mode", "distributed")

        if not accounts:
            return self._exec_single(
                server, None, "tools/call", {"name": tool_name, "arguments": args}
            )

        if mode == "incremental":
            aggregated = []
            for acc in accounts:
                try:
                    res = self._exec_single(
                        server,
                        acc,
                        "tools/call",
                        {"name": tool_name, "arguments": args},
                    )
                    acc["usage_count"] = int(acc.get("usage_count", 0)) + 1
                    acc["last_used_at"] = _now_iso()
                    acc["last_error"] = None
                    aggregated.append(
                        {
                            "account_id": acc["id"],
                            "account_name": acc["name"],
                            "context": acc.get("context", ""),
                            "ok": True,
                            "result": res,
                        }
                    )
                except Exception as exc:
                    acc["last_error"] = str(exc)
                    aggregated.append(
                        {
                            "account_id": acc["id"],
                            "account_name": acc["name"],
                            "context": acc.get("context", ""),
                            "ok": False,
                            "error": str(exc),
                        }
                    )
            self._save_raw_servers(servers)
            return {"mode": "incremental", "results": aggregated}

        if mode == "alternating":
            selected = None
            if req_account_id:
                selected = next(
                    (a for a in accounts if a["id"] == req_account_id), None
                )
            if selected is None and req_context:
                ctx_norm = str(req_context).strip().lower()
                selected = next(
                    (
                        a
                        for a in accounts
                        if (a.get("context") or "").strip().lower() == ctx_norm
                    ),
                    None,
                )
            if selected is None and server.get("active_account_id"):
                selected = next(
                    (a for a in accounts if a["id"] == server["active_account_id"]),
                    None,
                )
            if selected is None and server.get("active_context"):
                ctx_norm = str(server["active_context"]).strip().lower()
                selected = next(
                    (
                        a
                        for a in accounts
                        if (a.get("context") or "").strip().lower() == ctx_norm
                    ),
                    None,
                )
            if selected is None:
                selected = accounts[0]
            try:
                res = self._exec_single(
                    server,
                    selected,
                    "tools/call",
                    {"name": tool_name, "arguments": args},
                )
                selected["usage_count"] = int(selected.get("usage_count", 0)) + 1
                selected["last_used_at"] = _now_iso()
                selected["last_error"] = None
                self._save_raw_servers(servers)
                return res
            except Exception as exc:
                selected["last_error"] = str(exc)
                self._save_raw_servers(servers)
                raise

        # Default: distributed (round-robin with automatic fallback on failure)
        cursor = int(server.get("rr_cursor", 0)) % len(accounts)
        ordered = accounts[cursor:] + accounts[:cursor]
        server["rr_cursor"] = (cursor + 1) % len(accounts)

        last_exc: Exception | None = None
        for acc in ordered:
            try:
                res = self._exec_single(
                    server,
                    acc,
                    "tools/call",
                    {"name": tool_name, "arguments": args},
                )
                acc["usage_count"] = int(acc.get("usage_count", 0)) + 1
                acc["last_used_at"] = _now_iso()
                acc["last_error"] = None
                self._save_raw_servers(servers)
                return res
            except Exception as exc:
                acc["last_error"] = str(exc)
                last_exc = exc
        self._save_raw_servers(servers)
        raise last_exc or RuntimeError(
            "Nenhuma conta MCP ativa conseguiu executar a ferramenta."
        )

    def start_oauth(
        self,
        server_id: str,
        account_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
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
                oauth[field] = str(payload[field]).strip()
        if payload.get("client_secret"):
            self._set_secret(
                server_id,
                account_id,
                "oauth_client_secret",
                str(payload["client_secret"]).strip(),
            )
            oauth["has_client_secret"] = True

        if payload.get("access_token"):
            token = str(payload["access_token"]).strip()
            self._set_secret(server_id, account_id, "oauth_access_token", token)
            oauth["connected"] = True
            oauth["token_masked"] = _mask_secret(token)
            acc["auth_type"] = "oauth"
            self._save_raw_servers(servers)
            return {"ok": True, "auth_url": oauth.get("auth_url", ""), "account": acc}

        state = uuid.uuid4().hex
        states = self.store.get(OAUTH_STATE_KEY, {})
        if not isinstance(states, dict):
            states = {}
        states[state] = {
            "server_id": server_id,
            "account_id": account_id,
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
        payload = payload or {}
        account_id = str(payload.get("account_id") or "").strip()
        state = str(payload.get("state") or "").strip()
        if state:
            states = self.store.get(OAUTH_STATE_KEY, {})
            info = states.pop(state, None) if isinstance(states, dict) else None
            if info:
                self.store.set(OAUTH_STATE_KEY, states)
                account_id = account_id or info.get("account_id", "")

        servers = self._raw_servers()
        server = next((s for s in servers if s.get("id") == server_id), None)
        if server is None:
            raise KeyError(f"Servidor MCP '{server_id}' não encontrado.")
        acc = next(
            (a for a in (server.get("accounts") or []) if a["id"] == account_id), None
        )
        if acc is None:
            raise KeyError(f"Conta '{account_id}' não encontrada.")

        token = str(payload.get("access_token") or payload.get("code") or "").strip()
        if not token:
            raise ValueError("Token ou código OAuth ausente.")
        self._set_secret(server_id, account_id, "oauth_access_token", token)
        if payload.get("refresh_token"):
            self._set_secret(
                server_id,
                account_id,
                "oauth_refresh_token",
                str(payload["refresh_token"]).strip(),
            )
        acc.setdefault("oauth", {})["connected"] = True
        acc["oauth"]["token_masked"] = _mask_secret(token)
        acc["auth_type"] = "oauth"
        self._save_raw_servers(servers)
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

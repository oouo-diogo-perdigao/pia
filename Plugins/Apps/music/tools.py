"""Suno MCP tool owned by the music plugin."""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any


def _mcp_http_rpc(
    url: str, method: str, params: dict[str, Any], token: str = "", req_id: int = 1
) -> dict[str, Any]:
    import requests

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(
        url,
        headers=headers,
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
        timeout=300,
        allow_redirects=False,
    )
    resp.raise_for_status()
    return resp.json()


def _mcp_stdio_call(
    command: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    args = shlex.split(command, posix=False)
    if not args:
        raise RuntimeError("Comando do servidor Suno MCP inválido.")
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
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    ]
    payload = "\n".join(json.dumps(m) for m in msgs) + "\n"
    proc = subprocess.run(
        args,
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(
            proc.stderr.strip() or "Falha ao executar servidor Suno MCP."
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
    raise RuntimeError("Servidor Suno MCP não retornou resposta JSON-RPC válida.")


def call_suno_mcp(
    prompt: str,
    *,
    lyrics: str = "",
    duration: int = 30,
    suno_url: str = "",
    suno_cmd: str = "",
    suno_token: str = "",
) -> dict[str, Any]:
    if not suno_token or (not suno_url and not suno_cmd):
        try:
            from src.mcp_connectors import get_mcp_manager

            mgr = get_mcp_manager()
            raw = mgr._find_raw("suno_mcp")
            suno_url = suno_url or str(raw.get("url") or "").strip()
            suno_cmd = suno_cmd or str(raw.get("command") or "").strip()
            if not suno_token:
                accounts = [
                    a for a in (raw.get("accounts") or []) if a.get("enabled", True)
                ]
                acc = accounts[0] if accounts else None
                headers, _ = mgr._resolve_credentials(raw, acc)
                auth_header = headers.get("Authorization") or ""
                if auth_header.startswith("Bearer "):
                    suno_token = auth_header[len("Bearer ") :].strip()
        except Exception:
            pass
    arguments = {"prompt": prompt, "lyrics": lyrics, "duration": duration}
    if suno_url:
        try:
            rpc_res = _mcp_http_rpc(
                suno_url,
                "tools/call",
                {"name": "generate_music", "arguments": arguments},
                token=suno_token,
                req_id=2,
            )
            if isinstance(rpc_res, dict) and "result" in rpc_res:
                return rpc_res["result"]
            if isinstance(rpc_res, dict) and (
                "audio_base64" in rpc_res or "audio_url" in rpc_res
            ):
                return rpc_res
        except Exception:
            pass
        import requests

        headers = {"Content-Type": "application/json"}
        if suno_token:
            headers["Authorization"] = f"Bearer {suno_token}"
        resp = requests.post(
            suno_url,
            headers=headers,
            json=arguments,
            timeout=300,
            allow_redirects=False,
        )
        resp.raise_for_status()
        return resp.json()
    if suno_cmd:
        return _mcp_stdio_call(suno_cmd, "generate_music", arguments)
    raise RuntimeError(
        "Suno (MCP) não configurado: informe a URL ou comando do servidor MCP do Suno."
    )


def register_tools(ctx: Any) -> None:
    ctx.tools.register("pia_music_suno_mcp", call_suno_mcp)

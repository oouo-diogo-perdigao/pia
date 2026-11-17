"""Suno MCP tool owned by the music plugin."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Any

from src.mcp_connectors import _CREDIT_MESSAGE_RE, is_tool_auth_error, tool_error_text


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
        # Single source of truth (T1/D1): service.suno_status() rules.
        try:
            from Plugins.Apps.music.service import _resolve_suno_mcp_credentials

            r_url, r_cmd, r_tok = _resolve_suno_mcp_credentials()
            suno_url = suno_url or r_url
            suno_cmd = suno_cmd or r_cmd
            suno_token = suno_token or r_tok
        except Exception:
            pass
    arguments = {"prompt": prompt, "lyrics": lyrics, "duration": duration}
    if suno_url:
        import requests

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
            if isinstance(rpc_res, dict) and rpc_res:
                return rpc_res
            raise RuntimeError(
                "Resposta vazia ou inválida do Suno (MCP); a solicitação não foi repetida."
            )
        except requests.Timeout:
            raise RuntimeError(
                "Tempo esgotado aguardando resposta do Suno (MCP); a geração pode já estar em andamento."
            ) from None
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # Only fall back to plain REST POST if the endpoint rejects JSON-RPC method/path.
            if status not in (404, 405, 415, 501):
                raise
        except ValueError:
            raise RuntimeError(
                "Resposta inválida do Suno (MCP); a geração pode já estar em andamento e não foi repetida."
            ) from None

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


# --- T2: adaptador do MCP oficial do Suno (descoberta, argumentos, erros) ---
#
# O schema real de https://api.suno.com/mcp ainda não foi confirmado (spike de
# tools/list pendente de OAuth). Tudo abaixo é heurístico e coberto por fakes.

GENERATION_TOOL_PREFERENCE = (
    "generate_music",
    "create_song",
    "suno_generate_custom_music",
)
STATUS_TOOL_PREFERENCE = (
    "get_song",
    "get_clip",
    "get_task",
    "get_generation",
    "get_music",
)
PROMPT_FIELDS = ("prompt", "style", "description")
LYRICS_FIELDS = ("lyrics", "lyric")
TASK_ID_FIELDS = ("clip_id", "task_id", "song_id", "id")
STATUS_ID_FIELDS = ("id", "clip_id", "task_id", "song_id", "ids", "clip_ids")
FAILED_STATES = {"error", "failed", "failure", "cancelled", "canceled"}
DEFAULT_SUNO_TIMEOUT = 600
DEFAULT_POLL_INTERVAL = 5.0


def _tool_name(tool: dict[str, Any]) -> str:
    return str((tool or {}).get("name") or "").strip()


def _schema_properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = (tool or {}).get("inputSchema") or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    return props if isinstance(props, dict) else {}


def discover_generation_tool(
    tools: list[dict[str, Any]], configured: str = ""
) -> dict[str, Any]:
    """Pick the generation tool from a tools/list result.

    Order: ``MUSIC_SUNO_MCP_TOOL`` (must exist, no silent fallback), then
    ``GENERATION_TOOL_PREFERENCE``, then the first tool whose name has
    ``generate``/``create`` and ``song``/``music``.
    """
    from Plugins.Apps.music.service import SunoProtocolError

    by_name = {_tool_name(t): t for t in tools or [] if _tool_name(t)}
    configured = str(configured or "").strip()
    if configured:
        if configured in by_name:
            return by_name[configured]
        raise SunoProtocolError(
            "A ferramenta do Suno configurada em MUSIC_SUNO_MCP_TOOL não existe no servidor."
        )
    for name in GENERATION_TOOL_PREFERENCE:
        if name in by_name:
            return by_name[name]
    for name, tool in by_name.items():
        low = name.lower()
        if any(v in low for v in ("generate", "create")) and any(
            n in low for n in ("song", "music")
        ):
            return tool
    raise SunoProtocolError(
        "O servidor do Suno não expõe uma ferramenta de geração de música compatível."
    )


def discover_status_tool(tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_name = {_tool_name(t): t for t in tools or [] if _tool_name(t)}
    for name in STATUS_TOOL_PREFERENCE:
        if name in by_name:
            return by_name[name]
    return None


def map_generation_arguments(
    tool: dict[str, Any], prompt: str, *, lyrics: str = "", duration: int | None = None
) -> dict[str, Any]:
    """Map PIA inputs onto the tool ``inputSchema`` (only fields it declares).

    Refuses (before any paid call) when no prompt-like field exists or a
    required field cannot be filled.
    """
    from Plugins.Apps.music.service import SunoProtocolError

    props = _schema_properties(tool)
    args: dict[str, Any] = {}
    prompt_field = next((f for f in PROMPT_FIELDS if f in props), None)
    if prompt_field is None:
        raise SunoProtocolError(
            "A ferramenta de geração do Suno não aceita um prompt compatível."
        )
    args[prompt_field] = prompt
    lyrics = str(lyrics or "").strip()
    lyrics_field = next((f for f in LYRICS_FIELDS if f in props), None)
    if lyrics and lyrics_field:
        args[lyrics_field] = lyrics
    if "instrumental" in props:
        args["instrumental"] = not lyrics
    if duration is not None and "duration" in props:
        args["duration"] = duration
    schema = (tool or {}).get("inputSchema") or {}
    required = schema.get("required") if isinstance(schema, dict) else None
    missing = [f for f in (required or []) if f not in args]
    if missing:
        raise SunoProtocolError(
            "A ferramenta de geração do Suno exige campos que a PIA não preenche: "
            + ", ".join(sorted(str(m) for m in missing))
        )
    return args


def normalize_tool_result(result: Any) -> dict[str, Any]:
    """Flatten an MCP tools/call result into a dict (structuredContent or JSON text)."""
    if not isinstance(result, dict):
        return {}
    if isinstance(result.get("structuredContent"), dict):
        return dict(result["structuredContent"])
    if isinstance(result.get("content"), list):
        for part in result["content"]:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                try:
                    parsed = json.loads(part["text"])
                except (TypeError, ValueError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    return {"clips": parsed}
    return dict(result)


MAX_STATUS_FAILURES = 3  # falhas transitórias seguidas toleradas no polling
_AUTH_MESSAGE_RE = re.compile(
    r"\b(401|403)\b|\bunauthori[sz]ed\b|\bforbidden\b|\boauth\b|token (expired|invalid)",
    re.I,
)
_CANCEL_MESSAGE = (
    "A espera foi cancelada. O Suno pode continuar a geração já enviada e "
    "consumir créditos."
)


def extract_clips(data: dict[str, Any]) -> list[dict[str, Any]]:
    """All clips of a normalized result (``clips``/``songs``/``data``/``results``)."""
    for key in ("clips", "songs", "data", "results"):
        items = data.get(key)
        if isinstance(items, list) and items:
            return [dict(c) for c in items if isinstance(c, dict)]
    if any(k in data for k in ("audio_url", "audio_base64", *TASK_ID_FIELDS)):
        return [dict(data)]
    return []


def clip_id(clip: dict[str, Any]) -> str:
    for field in TASK_ID_FIELDS:
        value = clip.get(field)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def clip_state(clip: dict[str, Any]) -> str:
    """``ready`` (has audio), ``failed`` or ``pending`` (still generating)."""
    if (isinstance(clip.get("audio_base64"), str) and clip["audio_base64"]) or (
        isinstance(clip.get("audio_url"), str) and clip["audio_url"]
    ):
        return "ready"
    status = str(clip.get("status") or "").strip().lower()
    if status in FAILED_STATES or clip.get("error") or not clip_id(clip):
        return "failed"
    return "pending"


def translate_suno_error(exc: BaseException) -> Exception:
    """Map transport/MCP errors to D3 exceptions without leaking body/headers."""
    import requests

    from Plugins.Apps.music import service
    from src.mcp_connectors import MCPRpcError, safe_error

    if isinstance(exc, (service.MusicProviderError, InterruptedError)):
        return exc
    if isinstance(exc, (requests.Timeout, subprocess.TimeoutExpired, TimeoutError)):
        return service.SunoTimeoutError()
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            return service.SunoAuthError()
        if status == 402:
            return service.SunoNoCreditsError()
        if status == 408:
            return service.SunoTimeoutError()
        if status is None or status >= 500 or status in (404, 429):
            return service.SunoUnavailableError()
        return service.SunoProtocolError()
    if isinstance(exc, requests.RequestException):  # ConnectionError & co.
        return service.SunoUnavailableError()
    if isinstance(exc, KeyError):  # servidor/conta MCP não registrado
        return service.SunoUnavailableError()
    if isinstance(exc, MCPRpcError):
        code = safe_error(exc)[0]
        if code == "401":
            return service.SunoAuthError()
        if code == "402":
            return service.SunoNoCreditsError()
    message = str(exc)
    if _AUTH_MESSAGE_RE.search(message):
        return service.SunoAuthError()
    if _CREDIT_MESSAGE_RE.search(message):
        return service.SunoNoCreditsError()
    if "desabilitado" in message.lower():
        return service.SunoUnavailableError()
    return service.SunoProtocolError()


def _with_partial(exc: BaseException, clips: list[dict[str, Any]]) -> BaseException:
    """Attach the clips that already have audio (kept on timeout/cancel/error)."""
    exc.partial_clips = [c for c in clips if c.get("state") == "ready"]  # type: ignore[attr-defined]
    return exc


class SunoMcpAdapter:
    """Calls the Suno MCP through ``MCPConnectorManager`` (OAuth, sessions).

    ``generate`` returns ``{"clips": [...], "remote_ids": [...]}`` with every
    clip of the call, each tagged ``state`` = ``ready`` or ``failed``. On
    timeout/cancel/error during polling the raised exception carries
    ``partial_clips`` (clips that already have audio). A single account is
    pinned for tools/list, generation and polling (no fallback, no fan-out).
    ``service.generate``/``generate_suno_batch`` use it (T3).
    """

    def __init__(
        self,
        *,
        manager: Any = None,
        server_id: str | None = None,
        tool_name: str | None = None,
        timeout: float | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        sleep: Any = None,
        clock: Any = None,
        cancel_event: Any = None,
    ):
        import time

        from Plugins.Apps.music import service

        cfg = service.settings()
        if manager is None:
            from src.mcp_connectors import get_mcp_manager

            manager = get_mcp_manager()
        self.manager = manager
        self.server_id = server_id or service.suno_status()["server_id"]
        self.tool_name = (
            tool_name
            if tool_name is not None
            else str(cfg.get("MUSIC_SUNO_MCP_TOOL") or "").strip()
        )
        if timeout is None:
            try:
                timeout = float(cfg.get("MUSIC_SUNO_TIMEOUT") or DEFAULT_SUNO_TIMEOUT)
            except (TypeError, ValueError):
                timeout = DEFAULT_SUNO_TIMEOUT
        self.timeout = max(1.0, float(timeout))
        self.poll_interval = max(0.0, float(poll_interval))
        self.cancel_event = cancel_event
        if sleep is None:
            sleep = cancel_event.wait if cancel_event is not None else time.sleep
        self._sleep = sleep
        self._clock = clock or time.monotonic
        self.account_id: str | None = None

    # -- tools/list -------------------------------------------------------
    def _list_kwargs(self) -> dict[str, Any]:
        return {"account_id": self.account_id} if self.account_id else {}

    def tools(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        self._tools_from_cache = False
        if not refresh:
            try:
                cached = self.manager._find_raw(self.server_id).get("cached_tools")
            except Exception as exc:
                raise translate_suno_error(exc) from None
            if cached:
                self._tools_from_cache = True
                return list(cached)
        try:
            return self.manager.list_tools(
                self.server_id, timeout=min(self.timeout, 60), **self._list_kwargs()
            )
        except Exception as exc:
            raise translate_suno_error(exc) from None

    def generation_tool(self, *, refresh: bool = False) -> dict[str, Any]:
        return discover_generation_tool(
            self.tools(refresh=refresh), configured=self.tool_name
        )

    def _discover(
        self, prompt: str, lyrics: str, duration: int | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        from Plugins.Apps.music import service

        tools = self.tools()
        try:
            tool = discover_generation_tool(tools, configured=self.tool_name)
            args = map_generation_arguments(
                tool, prompt, lyrics=lyrics, duration=duration
            )
        except service.SunoProtocolError:
            if not self._tools_from_cache:
                raise
            # Stale cache: refresh tools/list once before giving up (item 9).
            tools = self.tools(refresh=True)
            tool = discover_generation_tool(tools, configured=self.tool_name)
            args = map_generation_arguments(
                tool, prompt, lyrics=lyrics, duration=duration
            )
        return tools, tool, args

    # -- calls --------------------------------------------------------------
    def _pin_account(self) -> None:
        select = getattr(self.manager, "select_account", None)
        if callable(select):
            try:
                self.account_id = select(self.server_id)
            except Exception as exc:
                raise translate_suno_error(exc) from None

    def _call(self, name: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": timeout, "retry_other_accounts": False}
        if self.account_id:
            kwargs["account_id"] = self.account_id
        try:
            result = self.manager.call_tool(self.server_id, name, args, **kwargs)
        except Exception as exc:
            raise translate_suno_error(exc) from None
        if isinstance(result, dict) and result.get("isError"):
            # Tool-level error (HTTP 200): classify by its text, never echo it.
            # Same conservative auth rule the manager uses to record "401".
            from Plugins.Apps.music import service

            if is_tool_auth_error(result):
                raise service.SunoAuthError()
            if _CREDIT_MESSAGE_RE.search(tool_error_text(result)):
                raise service.SunoNoCreditsError()
            raise service.SunoProtocolError()
        return normalize_tool_result(result)

    def _remaining(self, deadline: float) -> float:
        from Plugins.Apps.music import service

        remaining = deadline - self._clock()
        if remaining <= 0:
            raise service.SunoTimeoutError()
        return remaining

    def generate(
        self,
        prompt: str,
        *,
        lyrics: str = "",
        duration: int | None = None,
        cancelled: Any = None,
    ) -> dict[str, Any]:
        from Plugins.Apps.music import service

        if cancelled is None:
            cancelled = (
                self.cancel_event.is_set
                if self.cancel_event is not None
                else (lambda: False)
            )
        # The total timeout covers tools/list, generation and polling (item 8).
        deadline = self._clock() + self.timeout
        self._pin_account()
        tools, tool, args = self._discover(prompt, lyrics, duration)
        if cancelled():
            raise InterruptedError("Geração cancelada antes de enviar ao Suno.")
        data = self._call(_tool_name(tool), args, timeout=self._remaining(deadline))
        clips = extract_clips(data)
        if not clips:
            raise service.SunoProtocolError(
                "Resposta do servidor Suno (MCP) não trouxe áudio."
            )
        for clip in clips:
            clip["state"] = clip_state(clip)
        pending = [c for c in clips if c["state"] == "pending"]
        status_tool = discover_status_tool(tools) if pending else None
        if pending and status_tool is None:
            for clip in pending:  # sem tool de status não há como buscar o áudio
                clip["state"] = "failed"
            pending = []
        if pending:
            self._poll(clips, status_tool, deadline, cancelled)
        return {"clips": clips, "remote_ids": [clip_id(c) for c in clips]}

    def _poll(
        self,
        clips: list[dict[str, Any]],
        status_tool: dict[str, Any],
        deadline: float,
        cancelled: Any,
    ) -> None:
        from Plugins.Apps.music import service

        props = _schema_properties(status_tool)
        id_field = next((f for f in STATUS_ID_FIELDS if f in props), "id")
        batch_ids = id_field in ("ids", "clip_ids")
        failures = 0
        while True:
            pending = [c for c in clips if c["state"] == "pending"]
            if not pending:
                return
            if cancelled():
                raise _with_partial(InterruptedError(_CANCEL_MESSAGE), clips)
            try:
                remaining = self._remaining(deadline)
            except service.SunoTimeoutError as exc:
                raise _with_partial(exc, clips) from None
            self._sleep(min(self.poll_interval, remaining))
            if cancelled():
                raise _with_partial(InterruptedError(_CANCEL_MESSAGE), clips)
            requests_ = (
                [{id_field: [clip_id(c) for c in pending]}]
                if batch_ids
                else [{id_field: clip_id(c)} for c in pending]
            )
            for call_args in requests_:
                try:
                    remaining = self._remaining(deadline)
                    data = self._call(
                        _tool_name(status_tool), call_args, timeout=min(60, remaining)
                    )
                except service.SunoAuthError as exc:
                    raise _with_partial(exc, clips) from None
                except service.SunoTimeoutError as exc:
                    if deadline - self._clock() <= 0:
                        raise _with_partial(exc, clips) from None
                    failures += 1
                    if failures >= MAX_STATUS_FAILURES:
                        raise _with_partial(exc, clips) from None
                    continue
                except service.MusicProviderError as exc:
                    failures += 1
                    if failures >= MAX_STATUS_FAILURES:
                        raise _with_partial(exc, clips) from None
                    continue
                failures = 0
                by_id = {clip_id(c): c for c in clips}
                for update in extract_clips(data):
                    target = by_id.get(clip_id(update))
                    if target is None and not batch_ids:
                        target = by_id.get(str(next(iter(call_args.values()))))
                    if target is None or target["state"] != "pending":
                        continue
                    target.update({k: v for k, v in update.items() if v is not None})
                    target["state"] = clip_state(target)


def register_tools(ctx: Any) -> None:
    ctx.tools.register("pia_music_suno_mcp", call_suno_mcp)

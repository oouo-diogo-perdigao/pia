"""Despacho explícito das rotas /api/pia/openbot/* para Bots Dinâmicos."""

from __future__ import annotations

from typing import Any

from .models import OpenBotError
from .runtime import get_openbot_runtime
from .service import get_openbot_service


def dispatch_openbot(
    method: str,
    subpath: str,
    data: dict[str, Any],
    query: dict[str, list[str]],
    *,
    headers: dict[str, str] | None = None,
    workspace_jobs: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    svc = get_openbot_service()
    rt = get_openbot_runtime()

    if subpath == "/openbot/bots":
        if method == "GET":
            cursor = (query.get("cursor") or [None])[0]
            limit = (query.get("limit") or ["50"])[0]
            return 200, svc.list_bots(cursor=cursor, limit=int(limit))
        if method == "POST":
            return 201, svc.create_bot(data)

    if subpath == "/openbot/avatars" and method == "POST":
        return 201, svc.upload_avatar(data.get("svg", ""))

    if subpath.startswith("/openbot/bots/"):
        rest = subpath.removeprefix("/openbot/bots/")
        if rest.endswith("/runs") and method == "POST":
            bot_id = rest.removesuffix("/runs").strip("/")
            res = rt.start_run(
                bot_id,
                chat_id=data.get("chat_id"),
                input_text=data.get("input", ""),
                request_id=data.get("request_id"),
                speak=bool(data.get("speak", False)),
                workspace_jobs=workspace_jobs,
            )
            return 202, res

        bot_id = rest.strip("/")
        if "/" in bot_id or not bot_id:
            raise OpenBotError(
                "Rota OpenBot não encontrada.", status=404, code="not_found"
            )
        if method == "GET":
            return 200, svc.get_bot(bot_id)
        if method in ("PATCH", "PUT"):
            return 200, svc.update_bot(bot_id, data)
        if method == "DELETE":
            if_match = None
            if headers:
                raw_im = headers.get("If-Match") or headers.get("if-match")
                if raw_im is not None:
                    try:
                        if_match = int(str(raw_im).strip().strip('"'))
                    except ValueError:
                        raise OpenBotError("If-Match inválido.") from None
            if if_match is None and "revision" in (data or {}):
                if_match = int(data["revision"])
            svc.delete_bot(
                bot_id,
                expected_revision=if_match,
                has_active_run=rt.has_active_run(bot_id),
            )
            return 204, b""

    if subpath.startswith("/openbot/runs/"):
        rest = subpath.removeprefix("/openbot/runs/")
        if rest.endswith("/cancel") and method == "POST":
            run_id = rest.removesuffix("/cancel").strip("/")
            return 202, rt.cancel_run(run_id)
        run_id = rest.strip("/")
        if "/" in run_id or not run_id:
            raise OpenBotError("Execução não encontrada.", status=404, code="not_found")
        if method == "GET":
            return 200, rt.get_run(run_id)

    raise OpenBotError("Rota OpenBot não encontrada.", status=404, code="not_found")

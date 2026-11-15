"""Bots routes for /api/pia/bots/*."""

from __future__ import annotations


def _list_bots(ctx, data, query):
    return ctx.bot_records()


def register(router) -> None:
    router.add("GET", "/bots", _list_bots, description="Listar bots disponíveis")

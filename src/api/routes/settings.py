"""Settings routes for /api/pia/settings/*."""

from __future__ import annotations


def _get_settings(ctx, data, query):
    return ctx.settings()


def register(router) -> None:
    router.add(
        "GET", "/settings", _get_settings, description="Obter configurações da PIA"
    )

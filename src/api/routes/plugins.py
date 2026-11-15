"""Plugins catalog routes for /api/pia/plugins/*."""

from __future__ import annotations

from src.plugins_catalog import get_plugins_catalog


def _list_plugins(ctx, data, query):
    return {"plugins": get_plugins_catalog().list_plugins()}


def _toggle_plugin(ctx, data, query, plugin_id):
    return get_plugins_catalog().toggle_plugin(
        plugin_id, data.get("enabled") if "enabled" in data else None
    )


def register(router) -> None:
    router.add("GET", "/plugins", _list_plugins, description="Listar plugins")
    router.add(
        "POST",
        "/plugins/{plugin_id}/toggle",
        _toggle_plugin,
        description="Ativar/desativar plugin",
    )

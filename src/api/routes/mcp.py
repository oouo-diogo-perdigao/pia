"""MCP custom connector routes for /api/pia/mcp/*."""

from __future__ import annotations

from src.integrations.mcp import ACCOUNT_MODES, get_mcp_manager


def _list_servers(ctx, data, query):
    return {"servers": get_mcp_manager().list_servers(), "account_modes": ACCOUNT_MODES}


def _save_server(ctx, data, query):
    return {"server": get_mcp_manager().save_server(data)}


def _get_server(ctx, data, query, server_id):
    return {"server": get_mcp_manager().get_server(server_id)}


def _update_server(ctx, data, query, server_id):
    return {"server": get_mcp_manager().save_server(data, server_id=server_id)}


def _delete_server(ctx, data, query, server_id):
    return get_mcp_manager().delete_server(server_id)


def _inspect_server(ctx, data, query, server_id):
    return get_mcp_manager().inspect_server(server_id)


def _oauth_start(ctx, data, query, server_id):
    return get_mcp_manager().start_oauth(
        server_id, account_id=data.get("account_id"), payload=data
    )


def _oauth_callback(ctx, data, query, server_id):
    return get_mcp_manager().complete_oauth(server_id, payload=data)


def register(router) -> None:
    router.add(
        "GET", "/mcp/servers", _list_servers, description="Listar servidores MCP"
    )
    router.add(
        "POST", "/mcp/servers", _save_server, description="Criar/atualizar servidor MCP"
    )
    router.add(
        "GET", "/mcp/servers/{server_id}", _get_server, description="Obter servidor MCP"
    )
    router.add(
        "PUT",
        "/mcp/servers/{server_id}",
        _update_server,
        description="Atualizar servidor MCP",
    )
    router.add(
        "POST",
        "/mcp/servers/{server_id}",
        _update_server,
        description="Atualizar servidor MCP",
    )
    router.add(
        "PATCH",
        "/mcp/servers/{server_id}",
        _update_server,
        description="Atualizar servidor MCP",
    )
    router.add(
        "DELETE",
        "/mcp/servers/{server_id}",
        _delete_server,
        description="Remover servidor MCP",
    )
    router.add(
        "GET",
        "/mcp/servers/{server_id}/tools",
        _inspect_server,
        description="Listar ferramentas do servidor MCP",
    )
    router.add(
        "POST",
        "/mcp/servers/{server_id}/inspect",
        _inspect_server,
        description="Inspecionar servidor MCP",
    )
    router.add(
        "POST",
        "/mcp/servers/{server_id}/oauth/start",
        _oauth_start,
        description="Iniciar OAuth MCP",
    )
    router.add(
        "POST",
        "/mcp/servers/{server_id}/oauth/callback",
        _oauth_callback,
        description="Concluir OAuth MCP",
    )

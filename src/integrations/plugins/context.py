"""Standardized PluginContext injected into plugins (inversion of control)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.core.secrets.vault import get_vault
from src.core.settings import document, save_document, values


class _ToolsFacade:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        self._handlers[str(name)] = handler

    def get(self, name: str) -> Callable[..., Any] | None:
        return self._handlers.get(str(name))

    def list(self) -> list[str]:
        return sorted(self._handlers)


class _RoutesFacade:
    def __init__(self) -> None:
        self._routes: list[tuple[str, str, Callable[..., Any]]] = []

    def register(self, method: str, pattern: str, handler: Callable[..., Any]) -> None:
        self._routes.append((method.upper(), pattern, handler))

    def list(self) -> list[tuple[str, str, Callable[..., Any]]]:
        return list(self._routes)


class _SettingsFacade:
    def __init__(self, section: str) -> None:
        self.section = section

    def values(self) -> dict[str, Any]:
        return values(self.section)

    def document(self, default: Any = None) -> Any:
        return document(self.section, {} if default is None else default)

    def save(self, data: Any) -> None:
        save_document(self.section, data)


class PluginContext:
    """Isolated runtime context given to plugins instead of importing core/plugins directly."""

    def __init__(
        self,
        plugin_id: str,
        category: str = "app",
        *,
        host: Any = None,
        vault: Any = None,
        tts_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.category = category
        self._host = host
        self._vault = vault
        self._tts_provider = tts_provider
        section_prefix = {
            "app": "Apps",
            "bot": "Bot",
            "connector": "Connectors",
            "skill": "Skills",
        }.get(category, "Apps")
        self.settings = _SettingsFacade(f"{section_prefix}/{plugin_id}")
        self.tools = _ToolsFacade()
        self.routes = _RoutesFacade()
        self.logger = logging.getLogger(f"pia.plugin.{plugin_id}")

    @property
    def vault(self) -> Any:
        return self._vault if self._vault is not None else get_vault()

    @property
    def tts(self) -> Any:
        if self._tts_provider is not None:
            return self._tts_provider()
        from src.voice.tts.service import get_tts_service

        return get_tts_service()

    def connector(self, connector_id: str) -> Any:
        if self._host is not None:
            return self._host.get_connector(connector_id)
        from src.resource_plugins import get_resources

        return get_resources()

    def plugin(self, target_id: str) -> Any:
        if self._host is not None:
            return self._host.get_context(target_id)
        return None

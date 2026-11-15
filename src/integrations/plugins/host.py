"""PluginHost: discovers manifests, loads plugin tools/modules dynamically, and manages PluginContext."""

from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path
from typing import Any

from .context import PluginContext
from .manifest import PluginManifest, discover_manifests


class PluginHost:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self._lock = threading.RLock()
        self._manifests: dict[str, PluginManifest] | None = None
        self._contexts: dict[str, PluginContext] = {}
        self._tool_modules: dict[str, types.ModuleType] = {}

    def manifests(self, *, refresh: bool = False) -> dict[str, PluginManifest]:
        with self._lock:
            if self._manifests is None or refresh:
                self._manifests = {m.id: m for m in discover_manifests(self.root)}
            return dict(self._manifests)

    def get_manifest(self, plugin_id: str) -> PluginManifest:
        manifests = self.manifests()
        if plugin_id not in manifests:
            raise KeyError(f"Plugin '{plugin_id}' não encontrado.")
        return manifests[plugin_id]

    def get_context(self, plugin_id: str) -> PluginContext:
        with self._lock:
            if plugin_id not in self._contexts:
                manifest = self.get_manifest(plugin_id)
                self._contexts[plugin_id] = PluginContext(
                    plugin_id, manifest.category, host=self
                )
            return self._contexts[plugin_id]

    def get_connector(self, connector_id: str) -> Any:
        from src.resource_plugins import get_resources

        resources = get_resources()
        if connector_id in ("google", "microsoft"):
            return resources
        return self.load_tools_module(connector_id)

    def load_tools_module(self, plugin_id: str) -> types.ModuleType:
        with self._lock:
            if plugin_id in self._tool_modules:
                return self._tool_modules[plugin_id]
            manifest = self.get_manifest(plugin_id)
            rel = manifest.tools_module or "tools.py"
            path = (manifest.folder / rel).resolve()
            if not path.is_relative_to(manifest.folder.resolve()) or not path.is_file():
                raise FileNotFoundError(
                    f"Módulo de tools não encontrado para plugin '{plugin_id}': {rel}"
                )
            mod_name = f"_pia_plugin_tools_{plugin_id}"
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Não foi possível carregar {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            ctx = self.get_context(plugin_id)
            if hasattr(module, "register_tools") and callable(module.register_tools):
                module.register_tools(ctx)
            self._tool_modules[plugin_id] = module
            return module

    def call_tool(self, plugin_id: str, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        ctx = self.get_context(plugin_id)
        mod = self.load_tools_module(plugin_id)
        handler = ctx.tools.get(fn_name) or getattr(mod, fn_name, None)
        if not callable(handler):
            raise AttributeError(
                f"Tool '{fn_name}' não encontrada no plugin '{plugin_id}'."
            )
        return handler(*args, **kwargs)


_host: PluginHost | None = None


def get_plugin_host() -> PluginHost:
    global _host
    if _host is None:
        _host = PluginHost()
    return _host

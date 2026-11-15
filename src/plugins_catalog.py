"""Catalog and enable/disable state for PIA plugins."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .config_paths import BASE_DIR
from .user_paths import user_path
from .workspace_store import WorkspaceStore

STORE_KEY = "plugins:state"


class PluginsCatalog:
    def __init__(self, root: Path | None = None, store: WorkspaceStore | None = None):
        self.root = Path(root or BASE_DIR / "Plugins")
        self.store = store or WorkspaceStore(user_path("workspace.sqlite3"))

    def _state(self) -> dict[str, bool]:
        raw = self.store.get(STORE_KEY, {})
        return raw if isinstance(raw, dict) else {}

    def list_plugins(self) -> list[dict[str, Any]]:
        state = self._state()
        plugins: list[dict[str, Any]] = []
        seen: set[str] = set()

        for category, folder_name in (("app", "Apps"), ("bot", "Bot")):
            base = self.root / folder_name
            if not base.is_dir():
                continue
            for manifest in sorted(base.glob("*/plugin.toml")):
                try:
                    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
                except Exception:
                    continue
                plugin_id = str(data.get("id") or manifest.parent.name).strip()
                if not plugin_id or plugin_id in seen:
                    continue
                seen.add(plugin_id)

                pia_json = manifest.parent / "pia.json"
                meta: dict[str, Any] = {}
                if pia_json.is_file():
                    try:
                        meta = json.loads(pia_json.read_text(encoding="utf-8"))
                    except Exception:
                        meta = {}

                capabilities: list[str] = []
                if data.get("web"):
                    capabilities.append("web")
                if isinstance(data.get("voice"), dict) and data["voice"].get(
                    "enabled", True
                ):
                    capabilities.append("voice")
                if data.get("native"):
                    capabilities.append("native")
                if category == "bot":
                    capabilities.append("bot")

                default_enabled = bool(data.get("enabled", True))
                enabled = bool(state.get(plugin_id, default_enabled))
                plugins.append(
                    {
                        "id": plugin_id,
                        "name": str(meta.get("nome") or data.get("name") or plugin_id),
                        "description": str(
                            meta.get("info")
                            or data.get("description")
                            or f"Plugin {plugin_id}"
                        ),
                        "version": str(
                            data.get("version") or meta.get("version") or "1.0.0"
                        ),
                        "enabled": enabled,
                        "category": category,
                        "capabilities": capabilities,
                        "icon": str(
                            data.get("icon") or ("bot" if category == "bot" else "app")
                        ),
                        "route": f"/apps/{plugin_id}/" if data.get("web") else None,
                    }
                )
        return plugins

    def toggle_plugin(
        self, plugin_id: str, enabled: bool | None = None
    ) -> dict[str, Any]:
        plugins = self.list_plugins()
        target = next((p for p in plugins if p["id"] == plugin_id), None)
        if target is None:
            raise KeyError(f"Plugin '{plugin_id}' não encontrado.")
        new_enabled = (not target["enabled"]) if enabled is None else bool(enabled)
        state = self._state()
        state[plugin_id] = new_enabled
        self.store.set(STORE_KEY, state)
        target["enabled"] = new_enabled
        return {"ok": True, "plugin": target}


_catalog: PluginsCatalog | None = None


def get_plugins_catalog() -> PluginsCatalog:
    global _catalog
    if _catalog is None:
        _catalog = PluginsCatalog()
    return _catalog

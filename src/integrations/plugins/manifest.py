"""Plugin manifest loader (plugin.toml + pia.json)."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config_paths import BASE_DIR


@dataclass
class PluginManifest:
    id: str
    name: str
    category: str
    folder: Path
    description: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    tools_module: str | None = None
    backend_api: str | None = None
    web_panel: str | None = None
    voice_config: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def load_manifest(manifest_path: Path, category: str) -> PluginManifest:
    data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    folder = manifest_path.parent
    pia_json = folder / "pia.json"
    meta: dict[str, Any] = {}
    if pia_json.is_file():
        try:
            meta = json.loads(pia_json.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    plugin_id = str(data.get("id") or folder.name).strip()
    tools_section = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    backend_section = (
        data.get("backend") if isinstance(data.get("backend"), dict) else {}
    )
    web_section = data.get("web") if isinstance(data.get("web"), dict) else {}
    voice_section = data.get("voice") if isinstance(data.get("voice"), dict) else {}

    return PluginManifest(
        id=plugin_id,
        name=str(meta.get("nome") or data.get("name") or plugin_id),
        category=category,
        folder=folder,
        description=str(meta.get("info") or data.get("description") or ""),
        version=str(data.get("version") or meta.get("version") or "1.0.0"),
        enabled=bool(data.get("enabled", True)),
        tools_module=tools_section.get("module"),
        backend_api=backend_section.get("api") or web_section.get("api"),
        web_panel=web_section.get("panel"),
        voice_config=voice_section,
        raw=data,
    )


def discover_manifests(root: Path | None = None) -> list[PluginManifest]:
    base = Path(root or BASE_DIR / "Plugins")
    manifests: list[PluginManifest] = []
    for category, folder_name in (
        ("app", "Apps"),
        ("bot", "Bot"),
        ("connector", "Connectors"),
        ("skill", "Skills"),
    ):
        cat_dir = base / folder_name
        if not cat_dir.is_dir():
            continue
        for file in sorted(cat_dir.glob("*/plugin.toml")):
            try:
                manifests.append(load_manifest(file, category))
            except Exception:
                continue
    return manifests

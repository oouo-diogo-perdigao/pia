"""Screenshot app API. No email, network upload or background capture."""

import os
from pathlib import Path
import re
import tempfile
import yaml

from src.settings_store import document, save_document

ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    "format": "png",
    "quality": 92,
    "prefill_title": True,
    "prefill_url": False,
    "border": False,
    "output_folder": "",
    "auto_save": True,
    "auto_copy": True,
    "default_tool": "free",
    "default_color": "#ff4278",
    "default_width": 3,
    "smooth": True,
    "bgr": False,
}

FOLDER_ERROR = (
    "Esta pasta não pode ser usada (não existe ou sem permissão). "
    "As capturas continuam indo para a pasta padrão."
)


def _same_path(first: str, second: str) -> bool:
    try:
        return Path(first).expanduser().resolve() == Path(second).expanduser().resolve()
    except OSError:
        return first.strip() == second.strip()


def _validate_writable_folder(folder_str: str) -> Path:
    path = Path(folder_str).expanduser()
    if not path.is_absolute():
        raise ValueError(FOLDER_ERROR)
    try:
        if path.exists() and not path.is_dir():
            raise ValueError(FOLDER_ERROR)
        created = False
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created = True
        with tempfile.NamedTemporaryFile(dir=path, prefix=".pia-check-", delete=True):
            pass
        if created:
            pass
    except OSError as exc:
        raise ValueError(FOLDER_ERROR) from exc
    return path


def config():
    from src.user_paths import user_path

    saved = document("Apps/screenshots", {})
    if not isinstance(saved, dict):
        saved = {}
    default_folder = str(user_path("screenshots"))
    raw_folder = str(saved.get("output_folder") or "").strip()
    is_default = (not raw_folder) or _same_path(raw_folder, default_folder)
    return {
        **DEFAULTS,
        **saved,
        "output_folder": default_folder if is_default else raw_folder,
        "default_output_folder": default_folder,
        "is_default_folder": is_default,
    }


def _load_shortcuts_raw() -> dict:
    from src.hotkeys import EXAMPLE_FILE

    text = document("main/shortcuts.yaml")
    if text is None and EXAMPLE_FILE.exists():
        text = EXAMPLE_FILE.read_text(encoding="utf-8")
    if not text:
        return {}
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Arquivo de atalhos inválido.")
    return loaded


def get_shortcuts() -> dict:
    from src.hotkeys import (
        ACTION_FRIENDLY_NAMES,
        DEFAULT_SHORTCUTS,
        current_os,
    )

    os_key = current_os()
    raw = _load_shortcuts_raw()
    shortcuts_raw = raw.get("shortcuts") or {}
    if not isinstance(shortcuts_raw, dict):
        raise ValueError("A chave 'shortcuts' precisa ser um mapa.")

    def read_action(action: str) -> str:
        item = shortcuts_raw.get(action)
        if isinstance(item, dict) and os_key in item and item[os_key] is not None:
            return str(item[os_key]).strip()
        return DEFAULT_SHORTCUTS.get(action, {}).get(os_key, "")

    others = {}
    all_actions = list(DEFAULT_SHORTCUTS.keys()) + [
        key for key in shortcuts_raw.keys() if key not in DEFAULT_SHORTCUTS
    ]
    for action in all_actions:
        if action in ("screenshot", "screenshot_window"):
            continue
        others[action] = {
            "shortcut": read_action(action),
            "label": ACTION_FRIENDLY_NAMES.get(action, action),
        }

    return {
        "os": os_key,
        "screenshot": read_action("screenshot"),
        "screenshot_window": read_action("screenshot_window"),
        "defaults": {
            "screenshot": DEFAULT_SHORTCUTS["screenshot"][os_key],
            "screenshot_window": DEFAULT_SHORTCUTS["screenshot_window"][os_key],
        },
        "others": others,
    }


def _save_shortcuts(data: dict, context) -> dict:
    from src.hotkeys import (
        ACTION_FRIENDLY_NAMES,
        DEFAULT_SHORTCUTS,
        current_os,
        normalize_shortcut,
        split_shortcut,
    )

    payload = data.get("value", data) if isinstance(data, dict) else {}
    os_key = current_os()
    raw = _load_shortcuts_raw()
    shortcuts_raw = raw.get("shortcuts")
    if shortcuts_raw is None:
        shortcuts_raw = {}
        raw["shortcuts"] = shortcuts_raw
    if not isinstance(shortcuts_raw, dict):
        raise ValueError("A chave 'shortcuts' precisa ser um mapa.")

    updates = {}
    for key in ("screenshot", "screenshot_window"):
        if key in payload:
            updates[key] = str(payload[key] or "").strip().lower()
        else:
            item = shortcuts_raw.get(key)
            if isinstance(item, dict) and os_key in item and item[os_key] is not None:
                updates[key] = str(item[os_key]).strip().lower()
            else:
                updates[key] = DEFAULT_SHORTCUTS[key][os_key]

    normalized = {}
    for key, val in updates.items():
        if not val:
            normalized[key] = None
            continue
        _mods, main_key = split_shortcut(val)
        if main_key in ("esc", "escape"):
            raise ValueError("A tecla Esc não pode ser usada como atalho.")
        normalized[key] = normalize_shortcut(val)

    if (
        normalized["screenshot"] is not None
        and normalized["screenshot"] == normalized["screenshot_window"]
    ):
        raise ValueError(
            'Este atalho já é usado por "Capturar região". Escolha outro.'
        )

    # Check conflicts against all other PIA shortcuts
    all_actions = list(DEFAULT_SHORTCUTS.keys()) + [
        k for k in shortcuts_raw.keys() if k not in DEFAULT_SHORTCUTS
    ]
    for other_action in all_actions:
        if other_action in ("screenshot", "screenshot_window"):
            continue
        item = shortcuts_raw.get(other_action)
        if isinstance(item, dict) and os_key in item and item[os_key] is not None:
            other_val = str(item[os_key]).strip().lower()
        else:
            other_val = DEFAULT_SHORTCUTS.get(other_action, {}).get(os_key, "")
        if not other_val:
            continue
        try:
            other_norm = normalize_shortcut(other_val)
        except ValueError:
            continue
        for key in ("screenshot", "screenshot_window"):
            if normalized[key] is not None and normalized[key] == other_norm:
                label = ACTION_FRIENDLY_NAMES.get(other_action, other_action)
                raise ValueError(
                    f'Este atalho já é usado por "{label}". Escolha outro.'
                )

    for key in ("screenshot", "screenshot_window"):
        existing_entry = shortcuts_raw.get(key)
        if not isinstance(existing_entry, dict):
            existing_entry = dict(DEFAULT_SHORTCUTS[key])
        else:
            existing_entry = dict(existing_entry)
        existing_entry[os_key] = updates[key]
        shortcuts_raw[key] = existing_entry

    save_document(
        "main/shortcuts.yaml",
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
    )

    reload_info = {"ok": True, "mode": "restart-required", "conflicts": []}
    if context is not None and getattr(context, "native_handler", None) is not None:
        try:
            reload_info = context.native("reload-hotkeys", {})
        except Exception:
            reload_info = {"ok": False, "mode": "restart-required", "conflicts": []}

    return {"ok": True, "reload": reload_info, "shortcuts": get_shortcuts()}


def handle(action, data, context):
    if action == "config":
        return config()
    if action == "save-config":
        from src.user_paths import user_path

        saved = document("Apps/screenshots", {})
        if not isinstance(saved, dict):
            saved = {}
        incoming = data.get("value", {}) if isinstance(data, dict) else {}
        if not isinstance(incoming, dict):
            raise ValueError("Preferência inválida.")
        value = {**config(), **incoming}
        quality = value.get("quality")
        if (
            value.get("format") not in ("png", "jpg", "bmp")
            or isinstance(quality, bool)
            or not isinstance(quality, (int, float))
            or int(quality) != quality
            or not 1 <= int(quality) <= 100
        ):
            raise ValueError("Formato ou qualidade inválidos.")
        value["quality"] = int(quality)

        for key in (
            "prefill_title",
            "prefill_url",
            "border",
            "auto_save",
            "auto_copy",
            "smooth",
            "bgr",
        ):
            if not isinstance(value.get(key), bool):
                raise ValueError("Preferência inválida.")

        if value.get("default_tool") not in ("free", "rect"):
            raise ValueError("Ferramenta inicial inválida.")

        if not isinstance(value.get("default_color"), str) or not re.fullmatch(
            r"#[0-9a-fA-F]{6}", value["default_color"]
        ):
            raise ValueError("Use uma cor no formato #RRGGBB.")

        width = value.get("default_width")
        if (
            isinstance(width, bool)
            or not isinstance(width, (int, float))
            or int(width) != width
            or not 1 <= int(width) <= 80
        ):
            raise ValueError("Use um valor de 1 a 80 px.")
        value["default_width"] = int(width)

        default_folder = str(user_path("screenshots"))
        raw_folder = str(value.get("output_folder") or "").strip()
        if not raw_folder or _same_path(raw_folder, default_folder):
            stored_folder = ""
        else:
            _validate_writable_folder(raw_folder)
            stored_folder = raw_folder
        value["output_folder"] = stored_folder

        persisted = {
            k: v
            for k, v in saved.items()
            if k not in ("default_output_folder", "is_default_folder")
        }
        for key in DEFAULTS:
            persisted[key] = value[key]
        save_document("Apps/screenshots", persisted)
        return {"ok": True, "config": config()}
    if action == "shortcuts":
        return get_shortcuts()
    if action == "save-shortcuts":
        return _save_shortcuts(data, context)
    if action == "status" and context.native_handler is None:
        return {"available": False, "captures": []}
    allowed = {
        "status",
        "capture",
        "image",
        "cancel",
        "copy",
        "save",
        "desktop",
        "drag",
        "print",
        "edit",
        "color",
        "finalize",
        "choose-folder",
        "saved-image",
        "list-saved",
        "delete-saved",
        "open-saved",
        "copy-saved",
    }
    if action not in allowed:
        raise ValueError("Operação de captura desconhecida.")
    return context.native(
        "app", {"id": "screenshots", "action": action, "payload": data}
    )

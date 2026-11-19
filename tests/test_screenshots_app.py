"""Unit tests for screenshots app (Card C2 & C3)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import yaml

import pytest

from Plugins.Apps.screenshots import web_api
from src import hotkeys, launcher, settings_store, user_paths


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(user_paths, "USER_DIR", tmp_path)

    class _Vault:
        def __init__(self):
            self.items = {}

        def get(self, name):
            return self.items.get(name)

        def set(self, name, value):
            self.items[name] = value

        def delete(self, name):
            self.items.pop(name, None)

    store = settings_store.SettingsStore(tmp_path / "workspace.sqlite3", _Vault())
    monkeypatch.setattr(settings_store, "_store", store)
    return store


def test_config_defaults_and_save_output_folder_and_editor(isolated_store, tmp_path):
    initial = web_api.handle("config", {}, SimpleNamespace(native_handler=None))
    assert initial["format"] == "png"
    assert initial["quality"] == 92
    assert initial["default_tool"] == "free"
    assert initial["default_color"] == "#ff4278"
    assert initial["default_width"] == 3
    assert initial["smooth"] is True
    assert initial["bgr"] is False
    assert initial["is_default_folder"] is True
    assert initial["output_folder"] == initial["default_output_folder"]

    custom_dir = tmp_path / "minhas-capturas"
    res = web_api.handle(
        "save-config",
        {
            "value": {
                "format": "jpg",
                "quality": 80,
                "output_folder": str(custom_dir),
                "default_tool": "rect",
                "default_color": "#00ff88",
                "default_width": 12,
                "smooth": False,
                "bgr": True,
            }
        },
        SimpleNamespace(native_handler=None),
    )
    assert res["ok"] is True
    assert custom_dir.is_dir()

    reloaded = web_api.config()
    assert reloaded["format"] == "jpg"
    assert reloaded["quality"] == 80
    assert reloaded["output_folder"] == str(custom_dir)
    assert reloaded["is_default_folder"] is False
    assert reloaded["default_tool"] == "rect"
    assert reloaded["default_color"] == "#00ff88"
    assert reloaded["default_width"] == 12
    assert reloaded["smooth"] is False
    assert reloaded["bgr"] is True

    # Restoring default folder resets is_default_folder
    web_api.handle(
        "save-config",
        {"value": {"output_folder": reloaded["default_output_folder"]}},
        SimpleNamespace(native_handler=None),
    )
    restored = web_api.config()
    assert restored["is_default_folder"] is True
    assert restored["output_folder"] == restored["default_output_folder"]


def test_save_config_validations(isolated_store, tmp_path):
    ctx = SimpleNamespace(native_handler=None)
    with pytest.raises(ValueError, match="Use uma cor no formato #RRGGBB"):
        web_api.handle("save-config", {"value": {"default_color": "red"}}, ctx)

    with pytest.raises(ValueError, match="Use um valor de 1 a 80 px"):
        web_api.handle("save-config", {"value": {"default_width": 100}}, ctx)

    with pytest.raises(ValueError, match="Esta pasta não pode ser usada"):
        web_api.handle("save-config", {"value": {"output_folder": "relative/path"}}, ctx)

    blocking_file = tmp_path / "not-a-dir.txt"
    blocking_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Esta pasta não pode ser usada"):
        web_api.handle(
            "save-config", {"value": {"output_folder": str(blocking_file)}}, ctx
        )


def test_shortcuts_surgical_edit_and_conflict_detection(isolated_store):
    base_yaml = {
        "server": "http://127.0.0.1:9999",
        "voice": "custom_voice",
        "speed": 1.15,
        "shortcuts": {
            "voice": {"windows": "ctrl+alt+p", "linux": "ctrl+alt+p"},
            "dictation": {"windows": "ctrl+alt+d", "linux": "ctrl+alt+shift+d"},
            "speak": {"windows": "ctrl+alt+t", "linux": "ctrl+alt+shift+t"},
            "storytelling": {"windows": "ctrl+alt+l", "linux": "ctrl+alt+l"},
            "screenshot": {"windows": "print_screen", "linux": "print_screen"},
            "screenshot_window": {
                "windows": "alt+print_screen",
                "linux": "alt+print_screen",
            },
        },
    }
    settings_store.save_document(
        "main/shortcuts.yaml", yaml.safe_dump(base_yaml, sort_keys=False)
    )

    native_calls = []

    def fake_native(action, payload):
        native_calls.append((action, payload))
        return {"ok": True, "mode": "hot-reload", "conflicts": []}

    ctx = SimpleNamespace(native_handler=fake_native, native=fake_native)

    info = web_api.handle("shortcuts", {}, ctx)
    assert info["screenshot"] == "print_screen"
    assert info["screenshot_window"] == "alt+print_screen"
    assert info["others"]["voice"]["label"] == "Voz"

    # Conflict with voice
    with pytest.raises(ValueError, match='Este atalho já é usado por "Voz"'):
        web_api.handle(
            "save-shortcuts",
            {"screenshot": "ctrl+alt+p", "screenshot_window": "alt+print_screen"},
            ctx,
        )

    # Modifier-only rejected
    with pytest.raises(ValueError, match="Inclua uma tecla além de Ctrl"):
        web_api.handle(
            "save-shortcuts",
            {"screenshot": "ctrl+shift", "screenshot_window": "alt+print_screen"},
            ctx,
        )

    # Conflict between screenshot and screenshot_window
    with pytest.raises(ValueError, match="Este atalho já é usado por"):
        web_api.handle(
            "save-shortcuts",
            {"screenshot": "ctrl+shift+s", "screenshot_window": "shift+ctrl+s"},
            ctx,
        )

    # Valid surgical update preserves server/voice/speed/other shortcuts/other OS
    result = web_api.handle(
        "save-shortcuts",
        {"screenshot": "ctrl+shift+s", "screenshot_window": "ctrl+shift+w"},
        ctx,
    )
    assert result["ok"] is True
    assert result["reload"]["mode"] == "hot-reload"
    assert native_calls == [("reload-hotkeys", {})]

    saved_raw = yaml.safe_load(settings_store.document("main/shortcuts.yaml"))
    os_key = hotkeys.current_os()
    other_os = "linux" if os_key == "windows" else "windows"
    assert saved_raw["server"] == "http://127.0.0.1:9999"
    assert saved_raw["voice"] == "custom_voice"
    assert saved_raw["speed"] == 1.15
    assert saved_raw["shortcuts"]["voice"][os_key] == "ctrl+alt+p"
    assert saved_raw["shortcuts"]["screenshot"][os_key] == "ctrl+shift+s"
    assert saved_raw["shortcuts"]["screenshot_window"][os_key] == "ctrl+shift+w"
    assert saved_raw["shortcuts"]["screenshot"][other_os] == "print_screen"


def test_native_output_directory_fallback_and_memory_cache(isolated_store, tmp_path):
    from PyQt6.QtGui import QImage
    from Plugins.Apps.screenshots import native as native_mod

    ui = SimpleNamespace(
        url="http://localhost:8762",
        main_action=Mock(),
        window=Mock(),
    )
    ui.main_action.isChecked.return_value = False

    with patch("src.config_paths.BASE_DIR", tmp_path):
        app = native_mod.NativeApp(ui, None)

        # Valid custom folder
        custom_dir = tmp_path / "custom-shots"
        web_api.handle(
            "save-config",
            {"value": {"output_folder": str(custom_dir)}},
            SimpleNamespace(native_handler=None),
        )
        assert app.output_directory() == custom_dir
        assert app._last_folder_warning == ""

        # Broken folder falls back safely to default user_path("screenshots")
        blocking_file = tmp_path / "blocked"
        blocking_file.write_text("x", encoding="utf-8")
        settings_store.save_document(
            "Apps/screenshots", {**web_api.DEFAULTS, "output_folder": str(blocking_file)}
        )
        fallback_dir = app.output_directory()
        assert fallback_dir == user_paths.user_path("screenshots")
        assert "Esta pasta não pode ser usada" in app._last_folder_warning

        # In-memory cache serves handle("image") without re-reading disk
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(0xFF112233)
        identity = app.store_capture(img, title="Teste", url="https://example.com")
        raw_path = app.records[identity]["path"]
        assert raw_path.is_file()
        raw_path.unlink()  # Delete raw file to prove memory cache is used
        payload = app.handle("image", {"id": identity})
        assert payload["data"].startswith("data:image/png;base64,")
        assert "path" not in payload and "_data" not in payload
        assert payload["title"] == "Teste"
        app.shutdown()


def test_launcher_reload_hotkeys_modes():
    fake_old = Mock()
    fake_old.poll.return_value = None
    fake_new = Mock()

    with (
        patch.object(hotkeys, "current_os", return_value="windows"),
        patch.object(launcher, "_hotkey_managed", True),
        patch.object(launcher, "_hotkey_listener", fake_old),
        patch("subprocess.Popen", return_value=fake_new) as popen,
    ):
        res = launcher.reload_hotkey_listener()
        assert res == {"ok": True, "mode": "hot-reload", "conflicts": []}
        fake_old.terminate.assert_called_once()
        popen.assert_called_once()
        launcher._hotkey_listener = None

    with (
        patch.object(hotkeys, "current_os", return_value="linux"),
        patch.object(hotkeys, "is_gnome", return_value=True),
        patch.object(hotkeys, "load_config", return_value={"shortcuts": {}}),
        patch.object(hotkeys, "install_gnome", return_value=["terminal"]),
    ):
        res = launcher.reload_hotkey_listener()
        assert res == {"ok": True, "mode": "gnome", "conflicts": ["terminal"]}

    with (
        patch.object(hotkeys, "current_os", return_value="windows"),
        patch.object(launcher, "_hotkey_managed", False),
        patch.object(launcher, "_hotkey_listener", None),
    ):
        res = launcher.reload_hotkey_listener()
        assert res == {"ok": True, "mode": "restart-required", "conflicts": []}


def test_capture_editor_assets_and_accessibility_rules():
    root = Path(__file__).resolve().parents[1]
    capture_html = (root / "Plugins/Apps/screenshots/web/capture.html").read_text(
        encoding="utf-8"
    )
    capture_css = (root / "Plugins/Apps/screenshots/web/capture.css").read_text(
        encoding="utf-8"
    )
    capture_jsx = (root / "Plugins/Apps/screenshots/web/CaptureEditor.jsx").read_text(
        encoding="utf-8"
    )
    capture_js = (root / "Plugins/Apps/screenshots/web/capture.js").read_text(
        encoding="utf-8"
    )

    # CSS preloaded directly in capture.html without JS waterfall
    assert '/apps/screenshots/capture.css' in capture_html
    assert "style.onload" not in capture_jsx

    # Accessible visual effect (Section 4 of ux-especificacao.md)
    assert "capture-aura" not in capture_css
    assert ".capture-vignette" in capture_css
    assert ".capture-frame" in capture_css
    assert ".capture-flash" in capture_css
    assert "prefers-reduced-motion:reduce" in capture_css or "prefers-reduced-motion: reduce" in capture_css
    assert "❄ Captura congelada · Arraste para recortar · Esc para cancelar" in capture_jsx
    assert 'role="toolbar"' in capture_jsx
    assert 'role="status"' in capture_jsx
    assert 'aria-live="polite"' in capture_jsx
    assert 'tabIndex={-1}' in capture_jsx

    # Keyboard fix: Enter/Space on BUTTON does not trigger fullScreen()
    assert 'active?.tagName === "BUTTON"' in capture_js
    assert "window.piaCapture" in capture_js
    assert "open: openCapture" in capture_js


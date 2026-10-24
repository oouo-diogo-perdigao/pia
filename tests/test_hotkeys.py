"""Atalhos: conversão de teclas e registro no GNOME, sem servidor e sem teclado."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hotkeys_under_test", ROOT / "hotkeys.py")
hotkeys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hotkeys)


class ShortcutFormatTests(unittest.TestCase):
    def test_gnome_binding_uses_primary_for_ctrl(self):
        self.assertEqual(hotkeys.to_gnome("ctrl+alt+p"), "<Primary><Alt>p")
        self.assertEqual(hotkeys.to_gnome("ctrl+alt+shift+t"), "<Primary><Alt><Shift>t")

    def test_pynput_binding(self):
        self.assertEqual(hotkeys.to_pynput("ctrl+alt+d"), "<ctrl>+<alt>+d")
        self.assertEqual(hotkeys.to_pynput("super+shift+f1"), "<cmd>+<shift>+<f1>")

    def test_example_keeps_windows_keys_and_avoids_gnome_reserved_ones(self):
        config = hotkeys.load_config(ROOT / "shortcuts.example.yaml")
        self.assertEqual(config["shortcuts"]["speak"]["windows"], "ctrl+alt+t")
        self.assertEqual(config["shortcuts"]["speak"]["linux"], "ctrl+alt+shift+t")
        self.assertEqual(config["shortcuts"]["dictation"]["linux"], "ctrl+alt+shift+d")

    def test_explicit_empty_value_is_not_replaced_by_the_default(self):
        text = "shortcuts:\n  speak:\n    linux: ''\n    windows: ctrl+alt+t\n"
        path = ROOT / "logs" / "shortcuts-test.yaml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        try:
            config = hotkeys.load_config(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(config["shortcuts"]["speak"]["linux"], "")

    def test_server_without_scheme_gets_http(self):
        self.assertEqual(hotkeys.normalize_server("127.0.0.1:8762"), "http://127.0.0.1:8762")


class GnomeRegistrationTests(unittest.TestCase):
    def test_merge_keeps_user_shortcuts_and_replaces_pia(self):
        existing = [
            "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/",
            "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/pia-speak/",
        ]
        enabled = [hotkeys.gnome_path("voice")]
        self.assertEqual(
            hotkeys.merge_custom_paths(existing, enabled),
            [
                "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/",
                hotkeys.gnome_path("voice"),
            ],
        )

    def test_conflict_ignores_pia_bindings(self):
        dumped = "\n".join(
            [
                "org.gnome.settings-daemon.plugins.media-keys terminal ['<Primary><Alt>t']",
                "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/pia-speak/ binding '<Primary><Alt>t'",
                "org.gnome.desktop.wm.keybindings show-desktop ['<Primary><Alt>d', '<Super>d']",
            ]
        )
        self.assertEqual(
            hotkeys.binding_conflicts("<Primary><Alt>t", dumped),
            ["terminal"],
        )
        self.assertEqual(hotkeys.binding_conflicts("<Primary><Alt>p", dumped), [])

    def test_command_quotes_paths_with_spaces(self):
        command = hotkeys.action_command("voice")
        self.assertIn(" voice", command)
        self.assertIn("hotkeys.py", command)


if __name__ == "__main__":
    unittest.main()

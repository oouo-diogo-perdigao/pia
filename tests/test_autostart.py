"""Inicialização: o arquivo de login aponta para a bandeja, não para o servidor cru."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("autostart_under_test", ROOT / "autostart.py")
autostart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autostart)


class AutostartTests(unittest.TestCase):
    def test_linux_entry_runs_the_shell_script(self):
        text = autostart.desktop_contents(ROOT, enabled=True)
        self.assertIn('Exec=bash "', text)
        self.assertIn("startup/piaSATServer.sh", text.replace("\\", "/"))
        self.assertIn("X-GNOME-Autostart-enabled=true", text)
        self.assertNotIn("python -m server", text)

    def test_disabled_flag_is_explicit(self):
        text = autostart.desktop_contents(ROOT, enabled=False)
        self.assertFalse(autostart.gnome_autostart_is_enabled(text))

    def test_missing_flag_counts_as_enabled(self):
        self.assertTrue(autostart.gnome_autostart_is_enabled("[Desktop Entry]\nType=Application\n"))

    def test_server_only_launcher_is_gone(self):
        self.assertFalse((ROOT / "startup" / "piaServer.vbs").exists())


if __name__ == "__main__":
    unittest.main()

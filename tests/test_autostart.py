"""Inicialização: o arquivo de login aponta para a bandeja, não para o servidor cru."""

import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "autostart_under_test", ROOT / "src/autostart.py"
)
autostart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autostart)


class AutostartTests(unittest.TestCase):
    def test_linux_entry_runs_the_shell_script(self):
        text = autostart.desktop_contents(ROOT, enabled=True)
        self.assertIn('Exec=bash "', text)
        self.assertIn("start.sh", text.replace("\\", "/"))
        self.assertIn("X-GNOME-Autostart-enabled=true", text)
        self.assertNotIn("python -m server", text)

    def test_disabled_flag_is_explicit(self):
        text = autostart.desktop_contents(ROOT, enabled=False)
        self.assertFalse(autostart.gnome_autostart_is_enabled(text))

    def test_missing_flag_counts_as_enabled(self):
        self.assertTrue(
            autostart.gnome_autostart_is_enabled("[Desktop Entry]\nType=Application\n")
        )

    def test_windows_login_runs_the_same_start_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bash = root / "Git/bin/bash.exe"
            bash.parent.mkdir(parents=True)
            bash.touch()
            with (
                patch.object(autostart, "project_dir", return_value=root),
                patch.object(
                    autostart, "windows_startup_dir", return_value=root / "startup"
                ),
                patch.object(autostart, "git_bash", return_value=bash),
                patch.object(autostart.subprocess, "run") as run,
            ):
                self.assertTrue(autostart._set_windows(True))
            command = run.call_args.args[0][-1]
            self.assertIn("bash.exe", command)
            self.assertIn("start.sh", command)
            self.assertNotIn("pia_launcher.py", command)
            self.assertNotIn("PIA Server Python.exe", command)

    def test_server_only_launcher_is_gone(self):
        self.assertFalse((ROOT / "startup" / "piaSATServer.sh").exists())


if __name__ == "__main__":
    unittest.main()

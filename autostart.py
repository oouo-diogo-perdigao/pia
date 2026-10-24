"""Liga ou desliga a entrada da PIA no login.

No Linux o alvo é startup/piaSATServer.sh. No Windows é o executável
gerado a partir de pia_launcher.py. Os dois abrem a bandeja e a API juntos.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DESKTOP_NAME = "piaSAT.desktop"
SHORTCUT_NAME = "PIA.lnk"
# Atalhos antigos que abriam só o servidor, sem a bandeja.
OLD_WINDOWS_SHORTCUTS = ("piaServer.lnk", "piaSATServer.lnk")
EXE_NAME = "PIA Server Python.exe"


def project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("PIA_DIR", r"D:\codes\pia"))
    return Path(__file__).resolve().parent


def linux_desktop_file() -> Path:
    return Path.home() / ".config" / "autostart" / DESKTOP_NAME


def windows_startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def windows_exe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return project_dir() / "dist" / EXE_NAME


def desktop_contents(project: Path, *, enabled: bool) -> str:
    script = project / "startup" / "piaSATServer.sh"
    flag = "true" if enabled else "false"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PIA\n"
        f'Exec=bash "{script}"\n'
        f"Path={project}\n"
        f"Icon={project / 'pia.png'}\n"
        "Terminal=false\n"
        f"X-GNOME-Autostart-enabled={flag}\n"
        "X-GNOME-Autostart-Delay=5\n"
    )


def gnome_autostart_is_enabled(text: str) -> bool:
    for line in text.splitlines():
        if line.strip().lower().startswith("x-gnome-autostart-enabled="):
            return line.split("=", 1)[1].strip().lower() == "true"
    return True


def is_enabled() -> bool:
    if sys.platform == "win32":
        return (windows_startup_dir() / SHORTCUT_NAME).is_file()
    desktop = linux_desktop_file()
    if not desktop.is_file():
        return False
    return gnome_autostart_is_enabled(desktop.read_text(encoding="utf-8"))


def set_enabled(enabled: bool) -> bool:
    if sys.platform == "win32":
        return _set_windows(enabled)
    _set_linux(enabled)
    return True


def _set_linux(enabled: bool) -> None:
    desktop = linux_desktop_file()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        desktop_contents(project_dir(), enabled=enabled),
        encoding="utf-8",
    )


def _set_windows(enabled: bool) -> bool:
    startup = windows_startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    for name in OLD_WINDOWS_SHORTCUTS:
        (startup / name).unlink(missing_ok=True)

    shortcut = startup / SHORTCUT_NAME
    if not enabled:
        shortcut.unlink(missing_ok=True)
        return True

    exe = windows_exe()
    if not exe.is_file():
        print(
            f"Executável não encontrado: {exe}. "
            "Gere o .exe com pyinstaller antes de marcar Inicializar.",
            file=sys.stderr,
        )
        return False

    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$link = $shell.CreateShortcut({_ps(shortcut)}); "
        f"$link.TargetPath = {_ps(exe)}; "
        f"$link.WorkingDirectory = {_ps(project_dir())}; "
        "$link.WindowStyle = 7; "
        "$link.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
    )
    return True


def _ps(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"

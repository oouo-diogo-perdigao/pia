"""Top level server runner inside src package for the pia engine."""

from __future__ import annotations
import os
import sys
import time
import threading
import traceback
import types
from pathlib import Path


def _ensure_xauthority() -> None:
    """No Wayland o XWayland só aceita o cookie da sessão gráfica."""
    current = os.environ.get("XAUTHORITY", "")
    if current and os.path.isfile(current):
        return
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    folder = Path(runtime)
    if not folder.is_dir():
        return
    matches = sorted(
        folder.glob(".mutter-Xwaylandauth.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if matches:
        os.environ["XAUTHORITY"] = str(matches[0])


def _keep_api_up_without_x_display() -> None:
    """PyAutoGUI abre o X na importação e derruba o processo inteiro.

    A API HTTP precisa continuar no ar. Colar na janela ativa é que depende do X.
    """
    if sys.platform == "win32":
        return
    _ensure_xauthority()
    try:
        import pyautogui  # noqa: F401
        return
    except ImportError:
        return
    except Exception as exc:
        for name in list(sys.modules):
            if name == "pyautogui" or name.startswith("pyautogui.") or name == "mouseinfo":
                sys.modules.pop(name, None)
        sys.modules["mouseinfo"] = types.ModuleType("mouseinfo")
        x11 = types.ModuleType("pyautogui._pyautogui_x11")
        x11._size = lambda: (0, 0)
        x11.keyboardMapping = {}
        sys.modules["pyautogui._pyautogui_x11"] = x11
        import pyautogui  # noqa: F401
        print(
            f"[PIA] Display X indisponível ({exc}). A API continua no ar; "
            "ações de teclado na tela ficam indisponíveis.",
            file=sys.stderr,
        )

# Reuse the project's existing Gemini credential when a dedicated STT key was
# not configured. Also normalize the unary model name to the Live variant used
# by HybridSTTManager.
from src import config as _config

if not _config.STT_GEMINI_API_KEY:
    _config.STT_GEMINI_API_KEY = _config.AGE_GEMINI_API_KEY
if _config.STT_GEMINI_MODEL == "gemini-3.5-transcribe":
    _config.STT_GEMINI_MODEL = "gemini-3.5-transcribe-live"

# Keep the existing public import path (src.STTManager.STTManager) intact while
# swapping in the cloud-first implementation before HTTPServer imports it.
# HybridSTTManager itself imports the original class first and subclasses it, so
# local Faster-Whisper remains the transparent fallback.
from src import STTManager as _stt_module
from src.HybridSTTManager import STTManager as _HybridSTTManager

_stt_module.STTManager = _HybridSTTManager

_keep_api_up_without_x_display()

from src.commands_loader import load_commands
from src.HTTPServer import run_http_server
from src.thread_wakeword import audio_listening_loop
from src.PiaOverlay import run_overlay_app


def main() -> None:
    """Start the pia application.

    The overlay must run in the main thread due to platform/UI requirements.
    The HTTP server and audio listening loop run in daemon threads.

    To avoid accidental process shutdown when a background thread crashes,
    the main thread keeps running while the overlay is active.
    """
    load_commands()

    # Keep HTTP server in background so overlay can stay in main thread.
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Audio listening should continue in background as before.
    audio_thread = threading.Thread(target=audio_listening_loop, daemon=True)
    audio_thread.start()

    try:
        run_overlay_app()
    finally:
        # If overlay exits unexpectedly, keep process alive briefly to surface
        # useful logs from background services instead of silent shutdown.
        for _ in range(10):
            if http_thread.is_alive() or audio_thread.is_alive():
                time.sleep(0.5)
            else:
                break


if __name__ == "__main__":
    main()

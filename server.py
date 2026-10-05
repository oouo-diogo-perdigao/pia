"""Top level server runner inside src package for the pia engine."""

from __future__ import annotations
import time
import threading
import traceback

# Keep the existing public import path (src.STTManager.STTManager) intact while
# swapping in the cloud-first implementation before HTTPServer imports it.
# HybridSTTManager itself imports the original class first and subclasses it, so
# local Faster-Whisper remains the transparent fallback.
from src import STTManager as _stt_module
from src.HybridSTTManager import STTManager as _HybridSTTManager

_stt_module.STTManager = _HybridSTTManager

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
    load_commands("commands")

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

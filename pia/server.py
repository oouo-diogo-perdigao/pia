"""Top level server runner inside src package for the pia engine."""

import threading

from src.commands_loader import load_commands
from src.HTTPServer import run_http_server
from src.thread_wakeword import audio_listening_loop
from src.PiaOverlay import run_overlay_app


def main() -> None:
    """Start the pia application.

    The HTTP server runs in the main process/thread so it becomes the primary
    process. The overlay application and audio listening loop run in daemon
    threads so they don't block shutdown of the main server.

    This change swaps previous behaviour where the HTTP server ran in a
    background thread and the overlay was the foreground task.
    """
    load_commands("commands")

    # Start overlay as a daemon thread so the HTTP server can run in main.
    overlay_thread = threading.Thread(target=run_overlay_app, daemon=True)
    overlay_thread.start()

    # Audio listening should continue in background as before.
    audio_thread = threading.Thread(target=audio_listening_loop, daemon=True)
    audio_thread.start()

    # Run the HTTP server in the main thread (blocking). This makes the
    # process lifecycle controlled by the HTTP server.
    run_http_server()


if __name__ == "__main__":
    main()

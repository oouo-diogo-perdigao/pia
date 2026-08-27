"""Top level server runner inside src package for the wakeword engine."""

import threading

from .src.commands_loader import load_commands
from .src.http_server import run_http_server
from .src.audio import audio_listening_loop
from .src.overlay import run_overlay_app


def main() -> None:
    load_commands("commands")

    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    audio_thread = threading.Thread(target=audio_listening_loop, daemon=True)
    audio_thread.start()

    run_overlay_app()


if __name__ == "__main__":
    main()

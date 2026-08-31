"""Shared runtime state and helper utilities for the PIA engine (src)."""

import threading

from threading import Event, Lock
import time
import os
import pygame

from .config import logging

COMMAND_ACTIONS: dict = {}
TRIGGER_EVENT = Event()
SESSION_ACTIVE = False
LOCK = Lock()

# Initialize audio mixer once (safe to call multiple times)
try:
    pygame.mixer.init()
except Exception:
    logging.warning("pygame mixer couldn't be initialized - audio playback disabled")


def play_sound(file_path: str) -> None:
    """Reproduz som de feedback sem bloquear a thread.

    Args:
        file_path: Path to the audio file.
    """

    def _play():
        try:
            if os.path.exists(file_path):
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
        except Exception as e:
            logging.error("[SOUND] Erro ao tocar som: %s", e)

    threading.Thread(target=_play, daemon=True).start()

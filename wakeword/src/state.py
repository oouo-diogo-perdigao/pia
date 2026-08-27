"""Shared runtime state and helper utilities for the wakeword engine (src)."""

from threading import Event, Lock
import logging
import time
import os
import pygame

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
    """Play a short sound file using pygame.

    Args:
        file_path: Path to the audio file.
    """
    try:
        if os.path.exists(file_path):
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
    except Exception as e:
        logging.error(f"[AUDIO] Error playing sound ({file_path}): {e}")

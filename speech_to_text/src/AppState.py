"""Centralized application state and lifecycle management for the STT service.

This module avoids module-level globals spread across modules and provides a
single place to start and stop background components (recorder, bridge,
stt manager).
"""

from __future__ import annotations

import threading
import queue
from pathlib import Path

from .AudioRecorder import AudioRecorder, worker_audio_bridge
from .STTWorkerManager import STTWorkerManager
from .config import logging


class AppState:
    """Holds shared objects and controls background workers.

    Responsibilities:
    - create and expose the AudioRecorder
    - create STTWorkerManager (lazy models_dir injection)
    - manage background bridge thread lifecycle
    - expose simple start/stop methods used by HTTP server
    """

    def __init__(self, models_dir: Path | None = None):
        self.recorder = AudioRecorder()
        self.transcribed_texts: queue.Queue = queue.Queue()
        self.is_transcribing_event = threading.Event()
        self.stop_bridge_event = threading.Event()
        self.bridge_thread: threading.Thread | None = None
        self.state_lock = threading.RLock()
        self.status = "idle"

        # STT manager lazily created to allow model dir injection
        self.stt_manager = STTWorkerManager(models_dir=models_dir)

    def start_recording(self) -> None:
        with self.state_lock:
            if self.status == "recording":
                return

            logging.info("[APP] Starting recorder and bridge thread...")
            self.recorder.start()
            self.stop_bridge_event.clear()
            self.bridge_thread = threading.Thread(
                target=worker_audio_bridge,
                args=(
                    self.recorder,
                    self.stt_manager,
                    self.transcribed_texts,
                    self.is_transcribing_event,
                    self.stop_bridge_event,
                ),
                daemon=True,
            )
            self.bridge_thread.start()
            # warm up STT in background
            threading.Thread(
                target=self.stt_manager.ensure_worker_running, daemon=True
            ).start()
            self.status = "recording"

    def stop_recording(self) -> None:
        with self.state_lock:
            if self.status != "recording":
                return
            logging.info("[APP] Stopping recorder and bridge thread...")
            self.recorder.stop()
            # request bridge shutdown and wait briefly
            self.stop_bridge_event.set()
            if self.bridge_thread is not None:
                self.bridge_thread.join(timeout=1.0)
                self.bridge_thread = None
            self.status = "idle"

    def shutdown(self) -> None:
        logging.info("[APP] Shutdown requested. Stopping recording and STT worker.")
        try:
            self.stop_recording()
        finally:
            self.stt_manager.stop_worker()


APP_STATE: AppState | None = None


def get_app_state(models_dir: Path | None = None) -> AppState:
    global APP_STATE
    if APP_STATE is None:
        APP_STATE = AppState(models_dir=models_dir)
    return APP_STATE

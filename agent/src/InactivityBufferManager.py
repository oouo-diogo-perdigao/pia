import threading
import time
import os
import pygame
import requests

from .config import logging, TTS_SERVER_URL
from .agents import AgentManager

# Initialize audio mixer once (safe to call multiple times)
try:
    pygame.mixer.init()
except Exception:
    logging.warning("pygame mixer couldn't be initialized - audio playback disabled")


PROCESSING_SOUND_PATH = os.path.join("..", "..", "sounds", "end.mp3")


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


def speak_tts(text: str):
    """Envia o texto para o serviço local de TTS."""
    try:
        requests.post(
            f"{TTS_SERVER_URL}/speak",
            json={"text": text},
            timeout=5,
        )
    except Exception as e:
        logging.error("[TTS ERRO] Falha ao enviar para o TTS: %s", e)


# ============================================================================
# GERENCIADOR DE BUFFER E INATIVIDADE
# ============================================================================
class InactivityBufferManager:
    def __init__(self, inactivity_timeout: float = 3.0):
        self.timeout = inactivity_timeout
        self.buffer = []
        self.last_update_time = 0.0
        self.lock = threading.Lock()
        self.agent_manager = AgentManager()
        self.worker_thread = threading.Thread(
            target=self._monitor_inactivity, daemon=True
        )
        self.worker_thread.start()

    def add_text(self, text: str, max_tokens: int = 0):
        with self.lock:
            self.buffer.append(text)
            self.last_update_time = time.time()
            logging.info("[BUFFER] Texto adicionado: '%s'", " ".join(self.buffer))

    def _monitor_inactivity(self):
        while True:
            time.sleep(0.2)
            with self.lock:
                if not self.buffer:
                    continue
                elapsed = time.time() - self.last_update_time
                if elapsed >= self.timeout:
                    full_prompt = " ".join(self.buffer).strip()
                    self.buffer.clear()
                    play_sound(PROCESSING_SOUND_PATH)
                    threading.Thread(
                        target=self._execute_agent, args=(full_prompt,), daemon=True
                    ).start()

    def _execute_agent(self, prompt: str):
        logging.info("[AGENT EXEC] Prompt final: '%s'", prompt)
        try:
            response_text = self.agent_manager.process(prompt)
            logging.info("[AGENT EXEC] Resposta: '%s'", response_text)
            speak_tts(response_text)
        except Exception as e:
            logging.error("[AGENT EXEC] Erro ao executar LLM/Fallback: %s", e)

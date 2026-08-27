"""Helpers to communicate with STT/TTS/Agent servers (simple HTTP wrappers) in src."""

import logging
import threading
import requests

from .config import STT_SERVER_URL, TTS_SERVER_URL, AGENT_SERVER_URL


def send_to_agent(prompt_text: str) -> None:
    try:
        logging.info(f"[AGENT] Disparando requisição -> '{prompt_text}'")
        requests.post(
            f"{AGENT_SERVER_URL}/process",
            json={"text": prompt_text},
            timeout=(0.5, 0.1),
        )
    except requests.exceptions.ReadTimeout:
        logging.info("[AGENT] Texto enviado com sucesso (sem aguardar resposta).")
    except Exception as e:
        logging.error(f"[AGENT] Erro na conexão com o servidor Agent: {e}")


def warm_up_services() -> None:
    def _ping(url: str, name: str) -> None:
        try:
            logging.info(f"[WAKEWORD] Pré-aquecendo o servidor {name}...")
            requests.get(url)
        except Exception as e:
            logging.warning(f"[WAKEWORD] Não foi possível pré-aquecer o {name}: {e}")

    threading.Thread(
        target=lambda: _ping(f"{STT_SERVER_URL}/warmup", "STT"), daemon=True
    ).start()
    threading.Thread(
        target=lambda: _ping(f"{TTS_SERVER_URL}/warmup", "TTS"), daemon=True
    ).start()
    threading.Thread(
        target=lambda: _ping(f"{AGENT_SERVER_URL}/warmup", "Agent"), daemon=True
    ).start()

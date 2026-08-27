"""Audio capture, wakeword detection loop and session management (src)."""

from pathlib import Path
import time
import logging
import threading

import numpy as np
import pyaudio
import requests

from .config import (
    RATE,
    CHANNELS,
    CHUNK,
    THRESHOLD,
    STT_SERVER_URL,
    START_SOUND,
    END_SOUND,
)
from .state import TRIGGER_EVENT, LOCK, SESSION_ACTIVE, play_sound
from .agent_client import warm_up_services
from .commands_loader import process_command


def start_continuous_session(stream, model) -> None:
    from . import state as _state

    with _state.LOCK:
        _state.SESSION_ACTIVE = True

    logging.info(">>> SESSÃO DE COMANDOS INICIADA <<<")
    warm_up_services()

    try:
        from commands import modo_ditado
    except Exception:
        modo_ditado = None

    play_sound(START_SOUND)
    model.reset()
    time.sleep(0.3)

    while stream.get_read_available() > 0:
        stream.read(CHUNK, exception_on_overflow=False)

    try:
        requests.post(f"{STT_SERVER_URL}/start", timeout=2)
    except Exception as e:
        logging.error(f"Erro ao conectar ao servidor STT: {e}")
        with _state.LOCK:
            _state.SESSION_ACTIVE = False
        return

    session_start_time = time.time()
    last_speech_time = time.time()
    prompted_inactivity = False

    try:
        while _state.SESSION_ACTIVE:
            time.sleep(0.1)
            now = time.time()

            try:
                status_res = requests.get(f"{STT_SERVER_URL}/status", timeout=2)
                if status_res.ok:
                    data = status_res.json()
                    chunks = data.get("text_chunks", [])
                    is_speaking = data.get("is_speaking", False)

                    if chunks or is_speaking:
                        last_speech_time = now

                    for text in chunks:
                        text_lower = text.lower().strip()
                        words = text_lower.split()

                        if (
                            len(words) <= 3
                            and words
                            and (
                                words[-1] == "finalizar"
                                or words[-1].startswith("encerra")
                            )
                        ):
                            logging.info(f"[PARADA SOLICITADA]: '{text_lower}'")
                            if modo_ditado:
                                modo_ditado.disable_dictation()
                            return

                        if modo_ditado and modo_ditado.process_dictation_chunk(text):
                            continue

                        if text_lower:
                            process_command(text_lower, lambda t: None)

            except Exception as e:
                logging.error(f"Erro ao consultar status do STT: {e}")

            if (
                modo_ditado
                and not modo_ditado.dictation_active
                and not prompted_inactivity
                and (now - last_speech_time >= 3.0)
            ):
                logging.info("[INATIVIDADE] Invocando prompt TTS...")
                from lib.utils import speak_tts

                speak_tts("Em que posso ajudá-lo, mestre?")
                prompted_inactivity = True

            if now - session_start_time > 2.5:
                if stream.get_read_available() >= CHUNK:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_frame = np.frombuffer(data, dtype=np.int16)
                    predictions = model.predict(audio_frame)

                    for wakeword, score in predictions.items():
                        if score >= THRESHOLD:
                            logging.info(f"[CANCELAMENTO VIA WAKEWORD]: {wakeword}")
                            if modo_ditado:
                                modo_ditado.disable_dictation()
                            return

    finally:
        try:
            requests.post(f"{STT_SERVER_URL}/stop", timeout=2)
        except Exception:
            pass

        if modo_ditado:
            modo_ditado.disable_dictation()

        play_sound(END_SOUND)
        model.reset()

        with _state.LOCK:
            _state.SESSION_ACTIVE = False

        logging.info(">>> SESSÃO DE COMANDOS ENCERRADA <<<\n")


def audio_listening_loop() -> None:
    logging.info("Carregando modelos do OpenWakeword...")
    import openwakeword
    from openwakeword.model import Model
    import numpy as np

    openwakeword.utils.download_models()
    model = Model(wakeword_models=["alexa", "hey_mycroft"])

    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    logging.info("Microfone escutando. Fale 'Hey Mycroft' ou ative via AHK.")
    last_detection = 0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_frame = np.frombuffer(data, dtype=np.int16)
            predictions = model.predict(audio_frame)

            detected_by_voice = any(
                score >= THRESHOLD for score in predictions.values()
            )
            detected_by_http = TRIGGER_EVENT.is_set()

            if detected_by_http:
                TRIGGER_EVENT.clear()

            now = time.time()
            if (detected_by_voice or detected_by_http) and (
                now - last_detection >= 1.5
            ):
                last_detection = time.time()
                trigger_source = "HTTP/AHK" if detected_by_http else "VOZ"
                logging.info(f"[DISPARO DETECTADO VIA {trigger_source}]")
                start_continuous_session(stream, model)

    except KeyboardInterrupt:
        logging.info("Encerrando...")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

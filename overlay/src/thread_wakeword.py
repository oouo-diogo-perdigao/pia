"""Audio capture, wakeword detection loop and session management (src)."""

import logging
import shutil
import time
import urllib.request
import tarfile
from pathlib import Path
import numpy as np
import pyaudio
import requests
import sherpa_onnx

from .config import (
    RATE,
    CHANNELS,
    CHUNK,
    THRESHOLD,
    SAT_SERVER_URL,
    START_SOUND,
    END_SOUND,
    logging,
)
from .state import TRIGGER_EVENT, play_sound
from .agent_client import warm_up_services, send_to_agent
from .commands_loader import process_command

# ---------------------------------------------------------------------------
# Modelo KWS
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
KWS_ROOT = BASE_DIR / "models_cache"
# MODEL_NAME = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile" # chinese model
MODEL_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"  # english model
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "kws-models/"
    f"{MODEL_NAME}.tar.bz2"
)

MODEL_DIR = KWS_ROOT / MODEL_NAME
KWS_TOKENS = MODEL_DIR / "tokens.txt"
KWS_ENCODER = MODEL_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
KWS_DECODER = MODEL_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"
KWS_JOINER = MODEL_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
KWS_KEYWORDS = BASE_DIR / "keywords.txt"
KWS_REQUIRED_FILES = (
    KWS_TOKENS,
    KWS_ENCODER,
    KWS_DECODER,
    KWS_JOINER,
)


def _download_file(url: str, destination: Path) -> None:
    """Baixa um arquivo para um caminho temporário e move ao finalizar."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"[KWS] Baixando modelo de:\n{url}")
    temporary_file = destination.with_name(destination.name + ".download")

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            total_size = response.headers.get("Content-Length")

            if total_size is not None:
                total_size = int(total_size)

            downloaded = 0

            with temporary_file.open("wb") as file:
                while True:
                    chunk = response.read(1024 * 1024)

                    if not chunk:
                        break

                    file.write(chunk)
                    downloaded += len(chunk)

                    if total_size:
                        percent = downloaded * 100 / total_size

                        logging.info(f"[KWS] Download: " f"{percent:.1f}%")

                    else:
                        logging.info(
                            f"[KWS] Download: " f"{downloaded / 1024 / 1024:.1f} MB"
                        )

        temporary_file.replace(destination)
        logging.info("[KWS] Download concluído.")

    except Exception:
        temporary_file.unlink(missing_ok=True)
        raise


def _extract_model_archive(archive: Path) -> None:
    """Extrai o .tar.bz2 do modelo."""

    logging.info(f"[KWS] Extraindo modelo para: {KWS_ROOT}")

    temporary_dir = KWS_ROOT / ".extracting"

    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)

    temporary_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        with tarfile.open(archive, mode="r:bz2") as tar:
            tar.extractall(temporary_dir, filter="data")

        extracted_model = temporary_dir / MODEL_NAME

        if not extracted_model.is_dir():
            candidates = [path for path in temporary_dir.iterdir() if path.is_dir()]

            if len(candidates) != 1:
                raise RuntimeError(
                    "Não foi possível identificar "
                    "o diretório do modelo KWS extraído."
                )

            extracted_model = candidates[0]

        if MODEL_DIR.exists():
            shutil.rmtree(MODEL_DIR)

        shutil.move(
            str(extracted_model),
            str(MODEL_DIR),
        )
        logging.info("[KWS] Modelo extraído com sucesso.")

    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)


def _ensure_keyword_model() -> None:
    """Baixa e instala automaticamente o modelo KWS quando necessário."""

    if not all(path.is_file() for path in KWS_REQUIRED_FILES):
        logging.info("[KWS] Modelo Sherpa-ONNX não encontrado.")

        archive = KWS_ROOT / f"{MODEL_NAME}.tar.bz2"

        if not archive.is_file():
            _download_file(
                MODEL_URL,
                archive,
            )

        _extract_model_archive(archive)

        archive.unlink(missing_ok=True)
    # else:
    #     logging.info("[KWS] Modelo Sherpa-ONNX já está instalado.")

    if not KWS_KEYWORDS.is_file():
        logging.info("[KWS] Criando arquivo de palavras-chave.")

        KWS_KEYWORDS.write_text(
            "hey mycroft\n",
            encoding="utf-8",
        )

    missing_files = [path for path in KWS_REQUIRED_FILES if not path.is_file()]

    if missing_files:
        raise RuntimeError(
            "O download do modelo KWS foi concluído, "
            "mas os seguintes arquivos não foram encontrados:\n"
            + "\n".join(f" - {path}" for path in missing_files)
        )


def _create_keyword_spotter() -> sherpa_onnx.KeywordSpotter:
    """Cria o detector KWS, baixando o modelo se necessário."""

    return sherpa_onnx.KeywordSpotter(
        tokens=str(KWS_TOKENS),
        encoder=str(KWS_ENCODER),
        decoder=str(KWS_DECODER),
        joiner=str(KWS_JOINER),
        keywords_file=str(KWS_KEYWORDS),
        num_threads=2,
        sample_rate=RATE,
        feature_dim=80,
        max_active_paths=4,
        keywords_score=1.0,
        keywords_threshold=THRESHOLD,
        num_trailing_blanks=1,
        provider="cpu",
    )


# ---------------------------------------------------------------------------
# Sessão contínua
# ---------------------------------------------------------------------------
def _start_continuous_session(stream, keyword_spotter) -> None:
    from . import state as _state
    import queue
    import json
    import threading

    with _state.LOCK:
        _state.SESSION_ACTIVE = True

    logging.info(">>> SESSÃO DE COMANDOS INICIADA <<<")
    warm_up_services()

    try:
        from commands import modo_ditado
    except Exception:
        modo_ditado = None

    # play_sound(START_SOUND)
    # time.sleep(0.3)

    while stream.get_read_available() > 0:
        stream.read(CHUNK, exception_on_overflow=False)

    try:
        requests.get(f"{SAT_SERVER_URL}/start", timeout=2)
    except Exception as e:
        logging.error(f"Erro ao conectar ao servidor SAT: {e}")

        with _state.LOCK:
            _state.SESSION_ACTIVE = False

        return

    session_start_time = time.time()
    last_speech_time = time.time()
    prompted_inactivity = False
    kws_stream = keyword_spotter.create_stream()

    event_queue = queue.Queue()

    def sse_worker():
        try:
            with requests.get(f"{SAT_SERVER_URL}/status/stream", stream=True) as r:
                for line in r.iter_lines():
                    with _state.LOCK:
                        if not _state.SESSION_ACTIVE:
                            break
                    if line:
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data: "):
                            try:
                                data = json.loads(decoded[6:])
                                event_queue.put(data)
                            except Exception:
                                pass
        except Exception as e:
            logging.error(f"[SSE Worker Error]: {e}")

    sse_thread = threading.Thread(target=sse_worker, daemon=True)
    sse_thread.start()

    try:
        while _state.SESSION_ACTIVE:
            time.sleep(0.05)
            now = time.time()

            while not event_queue.empty():
                try:
                    data = event_queue.get_nowait()
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
                            logging.info(f"[COMANDO PROCESSADO]: {text_lower}")
                            process_command(text_lower, send_to_agent)
                except queue.Empty:
                    break
                except Exception as e:
                    logging.error(f"Erro ao processar evento SSE do SAT: {e}")

            if (
                modo_ditado
                and not modo_ditado.dictation_active
                and not prompted_inactivity
                and (now - last_speech_time >= 3.0)
            ):
                logging.info("[INATIVIDADE] Invocando prompt TTS...")
                from .lib.utils import speak_tts

                speak_tts("Em que posso ajudá-lo, mestre?")

                prompted_inactivity = True

            if now - session_start_time > 2.5:
                if stream.get_read_available() >= CHUNK:
                    data = stream.read(CHUNK, exception_on_overflow=False)

                    audio_frame = (
                        np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    )

                    kws_stream.accept_waveform(
                        RATE,
                        audio_frame,
                    )

                    while keyword_spotter.is_ready(kws_stream):
                        keyword_spotter.decode_stream(kws_stream)

                    keyword = keyword_spotter.get_result(kws_stream)

                    if keyword:
                        logging.info(f"[CANCELAMENTO VIA PIA]: {keyword}")

                        if modo_ditado:
                            modo_ditado.disable_dictation()
                        return

    finally:
        try:
            requests.post(f"{SAT_SERVER_URL}/stop", timeout=2)
        except Exception:
            pass

        if modo_ditado and getattr(modo_ditado, "dictation_active", False):
            modo_ditado.disable_dictation()

        play_sound(END_SOUND)

        with _state.LOCK:
            _state.SESSION_ACTIVE = False

        logging.info(">>> SESSÃO DE COMANDOS ENCERRADA <<<\n")


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------
def audio_listening_loop() -> None:
    # logging.info("Verificando/Baixando modelos do sherpa_onnx...")
    _ensure_keyword_model()  # <--- Adicione esta linha aqui

    # logging.info("Carregando modelos do sherpa_onnx...")
    keyword_spotter = _create_keyword_spotter()

    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
        # input_device_index=2,
    )

    logging.info("Microfone escutando. Fale 'PIA' ou ative via AHK.")
    kws_stream = keyword_spotter.create_stream()
    last_detection = 0.0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_frame = (
                np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            )

            # --- ADIÇÃO PARA DEBUG DE ÁUDIO ---
            # rms = np.sqrt(np.mean(audio_frame**2))
            # if rms > 0.01:  # Se houver som acima de um nível mínimo
            #     print(f"[DEBUG AUDIO] Nível de som (RMS): {rms:.4f}")
            # -----------------------------------

            kws_stream.accept_waveform(
                RATE,
                audio_frame,
            )

            while keyword_spotter.is_ready(kws_stream):
                keyword_spotter.decode_stream(kws_stream)

            detected_keyword = keyword_spotter.get_result(kws_stream)

            # --- ADIÇÃO PARA VERIFICAR SE O DECODER RETORNOU ALGO ---
            if detected_keyword:
                print(f"[DEBUG KWS] Palavra-chave detectada: '{detected_keyword}'")
            # ---------------------------------------------------------

            detected_by_voice = bool(detected_keyword)
            detected_by_http = TRIGGER_EVENT.is_set()

            if detected_by_voice:
                logging.info(f"[WAKE WORD DETECTADA]: " f"{detected_keyword}")

                keyword_spotter.reset_stream(kws_stream)

            if detected_by_http:
                TRIGGER_EVENT.clear()

            now = time.time()

            if (detected_by_voice or detected_by_http) and (
                now - last_detection >= 1.5
            ):
                last_detection = now
                trigger_source = "HTTP/AHK" if detected_by_http else "VOZ"
                logging.info(f"[DISPARO DETECTADO VIA {trigger_source}]")
                _start_continuous_session(stream, keyword_spotter)
                kws_stream = keyword_spotter.create_stream()

    except KeyboardInterrupt:
        logging.info("Encerrando...")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

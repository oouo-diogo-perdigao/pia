import difflib
import importlib
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import openwakeword
from dotenv import load_dotenv
from openwakeword.model import Model
import pyaudio
import pygame
import requests

from lib.utils import speak_tts

# ==============================================================================
# CONFIGURAÇÃO E VARIÁVEIS DE AMBIENTE
# ==============================================================================
load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("WAKEWORD_PORT", "8768"))

RATE = int(os.getenv("RATE", "16000"))
CHANNELS = int(os.getenv("CHANNELS", "1"))
CHUNK = int(os.getenv("CHUNK", "1280"))
THRESHOLD = float(os.getenv("THRESHOLD", "0.5"))

STT_SERVER_URL = os.getenv("STT_SERVER_URL", "http://127.0.0.1:8767")
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://127.0.0.1:8765")
AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "http://127.0.0.1:866")

START_SOUND = os.path.join(os.path.dirname(__file__), "..", "sounds", "start.mp3")
END_SOUND = os.path.join(os.path.dirname(__file__), "..", "sounds", "end.mp3")

# ==============================================================================
# CONFIGURAÇÃO DE LOGS
# ==============================================================================
log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "wakeword_agent.log", encoding="utf-8"),
    ],
)

# ==============================================================================
# ESTADO GLOBAL DO ENGINE
# ==============================================================================
COMMAND_ACTIONS = {}
TRIGGER_EVENT = threading.Event()
SESSION_ACTIVE = False
LOCK = threading.Lock()

pygame.mixer.init()


def play_sound(file_path):
    try:
        if os.path.exists(file_path):
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
    except Exception as e:
        logging.error(f"[AUDIO] Erro ao reproduzir som ({file_path}): {e}")


def load_commands(folder_name="commands"):
    """Carrega ou recarrega dinamicamente os arquivos .py na pasta 'commands'."""
    global COMMAND_ACTIONS
    COMMAND_ACTIONS.clear()

    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    logging.info(f"[COMANDOS] Carregando comandos dinamicamente de '{folder_name}'...")

    for file_name in os.listdir(folder_name):
        if file_name.endswith(".py") and not file_name.startswith("__"):
            module_name = f"{folder_name}.{file_name[:-3]}"
            try:
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)

                if hasattr(module, "COMMAND_NAME") and hasattr(module, "execute"):
                    cmd_name = module.COMMAND_NAME.lower().strip()
                    COMMAND_ACTIONS[cmd_name] = module.execute
                    logging.info(f" -> Comando carregado: '{cmd_name}' ({file_name})")
                else:
                    logging.warning(
                        f" -> Ignorado '{file_name}': falta COMMAND_NAME ou execute()"
                    )
            except Exception as e:
                logging.error(f" -> Falha ao carregar '{file_name}': {e}")

    COMMAND_ACTIONS["recarregar comandos"] = lambda: load_commands(folder_name)
    logging.info(f"[COMANDOS] Total de {len(COMMAND_ACTIONS)} comando(s) ativo(s).")


def send_to_agent(prompt_text: str):
    """Envia requisição assíncrona ao agente (Fire and Forget)."""
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


def process_command(text: str):
    """Filtra comandos locais ou repassa para o agente externo."""
    text_clean = text.lower().strip()

    if "comando" in text_clean:
        action_text = text_clean.replace("comando", "").strip()
        logging.info(f"[COMANDO LOCAL DETECTADO]: '{action_text}'")

        best_match = None
        best_ratio = 0.0
        cutoff = 0.6

        for target_cmd in COMMAND_ACTIONS.keys():
            ratio = difflib.SequenceMatcher(None, action_text, target_cmd).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = target_cmd

        if best_match and best_ratio >= cutoff:
            logging.info(
                f"-> Executando comando ({best_ratio*100:.1f}%): '{best_match}'"
            )
            COMMAND_ACTIONS[best_match]()
            return
        else:
            logging.info("-> Comando local não reconhecido. Repassando ao Agent...")

    send_to_agent(text_clean)


def start_continuous_session(stream, model):
    """Inicia e gerencia o ciclo contínuo de captura e execução de voz."""
    global SESSION_ACTIVE
    with LOCK:
        SESSION_ACTIVE = True

    logging.info(">>> SESSÃO DE COMANDOS INICIADA <<<")

    try:
        from commands import modo_ditado
    except ImportError:
        modo_ditado = None

    play_sound(START_SOUND)
    model.reset()
    time.sleep(0.3)

    # Drena o buffer antigo do áudio
    while stream.get_read_available() > 0:
        stream.read(CHUNK, exception_on_overflow=False)

    try:
        requests.post(f"{STT_SERVER_URL}/start", timeout=2)
    except Exception as e:
        logging.error(f"Erro ao conectar ao servidor STT: {e}")
        with LOCK:
            SESSION_ACTIVE = False
        return

    session_start_time = time.time()
    last_speech_time = time.time()
    prompted_inactivity = False

    try:
        while SESSION_ACTIVE:
            time.sleep(0.1)
            now = time.time()

            # Checa respostas vindas do Servidor STT
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

                        # Regra de parada falada
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

                        # Redirecionamento de ditado
                        if modo_ditado and modo_ditado.process_dictation_chunk(text):
                            continue

                        # Processamento de comando regular
                        if text_lower:
                            process_command(text_lower)

            except Exception as e:
                logging.error(f"Erro ao consultar status do STT: {e}")

            # Prompt por inatividade (3 segundos sem falar)
            if (
                modo_ditado
                and not modo_ditado.dictation_active
                and not prompted_inactivity
                and (now - last_speech_time >= 3.0)
            ):
                logging.info("[INATIVIDADE] Invocando prompt TTS...")
                speak_tts("Em que posso ajudá-lo, mestre?")
                prompted_inactivity = True

            # Checagem de cancelamento via Wakeword novamente
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

        with LOCK:
            SESSION_ACTIVE = False

        logging.info(">>> SESSÃO DE COMANDOS ENCERRADA <<<\n")


# ==============================================================================
# SERVIDOR HTTP NATIVO
# ==============================================================================
class Handler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        global SESSION_ACTIVE
        try:
            if self.path in ["/trigger", "/trigger_wakeword", "/start"]:
                TRIGGER_EVENT.set()
                self.send_json(200, {"ok": True, "status": "triggered"})
                return

            if self.path == "/stop":
                with LOCK:
                    SESSION_ACTIVE = False
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})
        except Exception as exc:
            logging.exception("Erro em POST")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        if self.path == "/status":
            with LOCK:
                active = SESSION_ACTIVE
            self.send_json(200, {"ok": True, "active": active})
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def run_http_server():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logging.info(f"Servidor HTTP Wakeword rodando em http://{HOST}:{PORT}")
    server.serve_forever()


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def main():
    load_commands("commands")

    # Inicia o servidor de APIs REST leve em uma thread dedicada
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    logging.info("Carregando modelos do OpenWakeword...")
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
            # 1. Checa se o microfone captou a palavra-chave
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


if __name__ == "__main__":
    main()

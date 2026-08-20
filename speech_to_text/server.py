from __future__ import annotations

import gc
import json
import logging
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.agent import VoiceAgent
from src.audio_recorder import AudioRecorder

import os
import site

# Carrega as variáveis do arquivo .env
from dotenv import load_dotenv

load_dotenv()

# Adiciona o caminho das DLLs da NVIDIA ao PATH do Windows
venv_path = site.getsitepackages()[0]
nvidia_bin_dir = os.path.join(venv_path, "nvidia")
if os.path.exists(nvidia_bin_dir):
    for root, dirs, files in os.walk(nvidia_bin_dir):
        if "bin" in dirs:
            os.add_dll_directory(os.path.join(root, "bin"))

# Garante que a pasta de logs exista antes de configurar o FileHandler
log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            log_dir / "voice_agent.log",
            encoding="utf-8",
        ),
    ],
)
# --- Logger exclusivo para transcrições ---
transcription_logger = logging.getLogger("transcription_logger")
transcription_logger.setLevel(logging.INFO)
transcription_logger.propagate = False  # Impede de duplicar no voice_agent.log

transcription_handler = logging.FileHandler(
    log_dir / "transcriptions.log", encoding="utf-8"
)
# Formato apenas com a mensagem pura, sem data/hora ou level
transcription_handler.setFormatter(logging.Formatter("%(message)s"))
transcription_logger.addHandler(transcription_handler)

STATE_LOCK = threading.RLock()
STATUS = "idle"  # "idle", "recording"
IS_TRANSCRIBING = False
TRANSCRIBED_TEXTS = queue.Queue()

# Controle do Lazy Unload (10 Minutos)
AGENT: VoiceAgent | None = None
LAST_USED_TIME: float = 0.0
UNLOAD_TIMEOUT_SECONDS = 600

MODELS_DIR = Path(__file__).parent / "models_cache"

RECORDER = AudioRecorder(
    sample_rate=int(os.getenv("SAMPLE_RATE", 16000)),
    channels=int(os.getenv("CHANNELS", 1)),
)


def get_or_load_agent():
    global AGENT
    if AGENT is None:
        AGENT = VoiceAgent(MODELS_DIR)
    return AGENT


def worker_lazy_unload():
    global AGENT
    while True:
        time.sleep(30)
        with STATE_LOCK:
            if AGENT is not None and STATUS == "idle":
                elapsed = time.time() - LAST_USED_TIME
                if elapsed >= UNLOAD_TIMEOUT_SECONDS:
                    logging.info(
                        "[MODELO] Inativo por 10 minutos. Limpando memória VRAM..."
                    )
                    AGENT = None
                    gc.collect()


def worker_transcription():
    global IS_TRANSCRIBING
    while True:
        try:
            chunk = RECORDER.audio_queue.get(timeout=0.1)
            IS_TRANSCRIBING = True

            agent = get_or_load_agent()
            text = agent.transcribe_chunk(chunk)

            if text:
                # Grava a mensagem formatada no log geral da aplicação
                logging.info("[TRANSCRICAO CONCLUIDA]: %s", text)

                # Grava SOMENTE o texto limpo no arquivo transcriptions.log
                transcription_logger.info(text)

                TRANSCRIBED_TEXTS.put(text)
            else:
                logging.info("[TRANSCRICAO]: (Sem texto inteligível no chunk)")

            RECORDER.audio_queue.task_done()
        except queue.Empty:
            IS_TRANSCRIBING = False
        except Exception as e:
            logging.error("[WORKER] Erro na transcrição: %s", e)
            IS_TRANSCRIBING = False


threading.Thread(target=worker_transcription, daemon=True).start()
threading.Thread(target=worker_lazy_unload, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/status":
            with STATE_LOCK:
                new_text = []
                while not TRANSCRIBED_TEXTS.empty():
                    new_text.append(TRANSCRIBED_TEXTS.get())

                self.send_json(
                    200,
                    {
                        "ok": True,
                        "status": STATUS,
                        "is_speaking": bool(RECORDER.is_speaking),
                        "is_transcribing": bool(IS_TRANSCRIBING),
                        "text_chunks": new_text,
                    },
                )
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def do_POST(self) -> None:
        global STATUS, LAST_USED_TIME

        if self.path == "/start":
            with STATE_LOCK:
                if STATUS == "recording":
                    self.send_json(409, {"ok": False, "error": "Já está gravando."})
                    return

                logging.info("[POST /start] Iniciando escuta instantânea...")
                LAST_USED_TIME = time.time()

                # 1. Inicia a captura do microfone PRIMEIRO (resposta instantânea ao botão)
                RECORDER.start()
                STATUS = "recording"

                # 2. Carrega o modelo em segundo plano (não bloqueia a resposta do HTTP)
                threading.Thread(target=get_or_load_agent, daemon=True).start()

            self.send_json(200, {"ok": True})
            return

        if self.path == "/stop":
            with STATE_LOCK:
                logging.info(
                    "[POST /stop] Pausando gravação. Modelo permanece carregado."
                )
                STATUS = "idle"
                RECORDER.stop()
                LAST_USED_TIME = time.time()

            self.send_json(200, {"ok": True})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def log_message(self, fmt, *args) -> None:
        pass


def main() -> None:
    PORT = int(os.getenv("PORT", 8767))
    HOST = os.getenv("HOST", "127.0.0.1").strip()
    model_size = os.getenv("STT_MODEL", "small")

    VoiceAgent.ensure_model_downloaded(model_size, MODELS_DIR)

    logging.info("Servidor STT pronto e ouvindo na porta %d", PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

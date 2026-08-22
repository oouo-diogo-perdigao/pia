from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import queue
import site
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", 8767))
HOST = os.getenv("HOST", "127.0.0.1").strip()
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", 16000))
CHANNELS = int(os.getenv("CHANNELS", 1))

# Configuração de DLLs NVIDIA
venv_path = site.getsitepackages()[0]
nvidia_bin_dir = os.path.join(venv_path, "nvidia")
if os.path.exists(nvidia_bin_dir):
    for root, dirs, files in os.walk(nvidia_bin_dir):
        if "bin" in dirs:
            try:
                os.add_dll_directory(os.path.join(root, "bin"))
            except Exception:
                pass

# Configuração de Logs
log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "voice_agent.log", encoding="utf-8"),
    ],
)

transcription_logger = logging.getLogger("transcription_logger")
transcription_logger.setLevel(logging.INFO)
transcription_logger.propagate = False
transcription_handler = logging.FileHandler(
    log_dir / "transcriptions.log", encoding="utf-8"
)
transcription_handler.setFormatter(logging.Formatter("%(message)s"))
transcription_logger.addHandler(transcription_handler)

STATE_LOCK = threading.RLock()
STATUS = "idle"  # "idle", "recording"
IS_TRANSCRIBING = False
TRANSCRIBED_TEXTS = queue.Queue()
UNLOAD_TIMEOUT_SECONDS = 600
MODELS_DIR = Path(__file__).parent / "models_cache"


# ==============================================================================
# WORKER PROCESS (ISOLADO): O VoiceAgent / PyTorch rodam EXCLUSIVAMENTE aqui
# ==============================================================================
def stt_worker_process(
    audio_chunk_queue: mp.Queue, text_result_queue: mp.Queue, models_dir: Path
):
    """Processo isolado para transcrição. O encerramento deste processo devolve 100% da RAM/VRAM ao SO."""
    # Importações pesadas acontecem APENAS dentro do processo filho
    from src.agent import VoiceAgent

    logging.info("[WORKER STT] Inicializando modelo de IA no processo filho...")
    agent = VoiceAgent(models_dir)
    logging.info("[WORKER STT] Modelo pronto para transcrição.")

    last_used = time.monotonic()

    while True:
        try:
            # Aguarda novo chunk de áudio para transcrição
            item = audio_chunk_queue.get(timeout=1.0)
        except queue.Empty:
            if time.monotonic() - last_used >= UNLOAD_TIMEOUT_SECONDS:
                logging.info(
                    "[WORKER STT] Inatividade de %ds atingida. Finalizando processo e liberando memória...",
                    UNLOAD_TIMEOUT_SECONDS,
                )
                break
            continue

        if item == "SHUTDOWN":
            logging.info("[WORKER STT] Comando de shutdown recebido.")
            break

        chunk = item
        last_used = time.monotonic()

        try:
            text = agent.transcribe_chunk(chunk)
            if text:
                text_result_queue.put({"ok": True, "text": text})
            else:
                text_result_queue.put({"ok": True, "text": None})
        except Exception as e:
            logging.error("[WORKER STT] Erro durante transcrição: %s", e)
            text_result_queue.put({"ok": False, "error": str(e)})

    logging.info(
        "[WORKER STT] Processo encerrado. Toda a memória VRAM/RAM foi devolvida ao sistema."
    )


# ==============================================================================
# GERENCIADOR DO WORKER NO PROCESSO PRINCIPAL
# ==============================================================================
class STTWorkerManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.worker_process = None
        self.audio_chunk_queue = None
        self.text_result_queue = None

    def ensure_worker_running(self):
        with self.lock:
            if self.worker_process is None or not self.worker_process.is_alive():
                logging.info("[MANAGER STT] Subindo novo worker isolado para STT...")
                self.audio_chunk_queue = mp.Queue()
                self.text_result_queue = mp.Queue()
                self.worker_process = mp.Process(
                    target=stt_worker_process,
                    args=(self.audio_chunk_queue, self.text_result_queue, MODELS_DIR),
                    daemon=True,
                )
                self.worker_process.start()

    def send_chunk(self, chunk):
        self.ensure_worker_running()
        self.audio_chunk_queue.put(chunk)

    def get_result(self, timeout=0.1):
        if self.text_result_queue is None:
            return None
        try:
            return self.text_result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop_worker(self):
        with self.lock:
            if self.worker_process and self.worker_process.is_alive():
                self.audio_chunk_queue.put("SHUTDOWN")
                self.worker_process.join(timeout=3)
                if self.worker_process.is_alive():
                    self.worker_process.terminate()
                self.worker_process = None


STT_MANAGER = STTWorkerManager()

# Carrega o AudioRecorder (Processo Principal)
from src.audio_recorder import AudioRecorder

RECORDER = AudioRecorder(
    sample_rate=SAMPLE_RATE,
    channels=CHANNELS,
)


# ==============================================================================
# THREADS DE LEITURA E PROCESSAMENTO
# ==============================================================================
def worker_audio_bridge():
    """Lê os chunks capturados pelo AudioRecorder e repassa ao Worker de IA."""
    global IS_TRANSCRIBING
    while True:
        try:
            chunk = RECORDER.audio_queue.get(timeout=0.1)
            IS_TRANSCRIBING = True
            STT_MANAGER.send_chunk(chunk)
            RECORDER.audio_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logging.error("[BRIDGE] Erro no repasse de áudio: %s", e)

        # Coleta respostas vindas do Worker STT
        result = STT_MANAGER.get_result(timeout=0.01)
        if result:
            if result.get("ok") and result.get("text"):
                text = result["text"]
                logging.info("[TRANSCRICAO CONCLUIDA]: %s", text)
                transcription_logger.info(text)
                TRANSCRIBED_TEXTS.put(text)
            IS_TRANSCRIBING = False


threading.Thread(target=worker_audio_bridge, daemon=True).start()


# ==============================================================================
# SERVIDOR HTTP LEVE
# ==============================================================================
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
        global STATUS

        if self.path == "/start":
            with STATE_LOCK:
                if STATUS == "recording":
                    self.send_json(409, {"ok": False, "error": "Já está gravando."})
                    return

                logging.info("[POST /start] Iniciando gravação e subindo Worker STT...")
                RECORDER.start()
                STATUS = "recording"

                # Sobe/Aquece o processo do modelo em background
                threading.Thread(
                    target=STT_MANAGER.ensure_worker_running, daemon=True
                ).start()

            self.send_json(200, {"ok": True})
            return

        if self.path == "/stop":
            with STATE_LOCK:
                logging.info("[POST /stop] Pausando gravação.")
                STATUS = "idle"
                RECORDER.stop()

            self.send_json(200, {"ok": True})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def log_message(self, fmt, *args) -> None:
        pass


def main() -> None:
    mp.set_start_method("spawn", force=True)

    logging.info("Servidor STT pronto e ouvindo na porta %d", PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        STT_MANAGER.stop_worker()
        server.server_close()


if __name__ == "__main__":
    main()

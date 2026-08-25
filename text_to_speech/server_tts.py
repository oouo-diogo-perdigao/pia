import json
import multiprocessing as mp
import os
import logging
from logging.handlers import RotatingFileHandler
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from lib.AudioPlayer import AudioPlayer
from lib.TTSManager import TTSManager

from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST").strip()
PORT = int(os.getenv("PORT"))
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "pm_santa").strip()
DEFAULT_SPEED = float(os.getenv("DEFAULT_SPEED", "1.00").strip())

# ==============================================================================
# CONFIGURAÇÃO DE LOGS
# ==============================================================================
log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# Exemplo: ~1000 linhas por arquivo (1000 linhas * 100 bytes = 100_000 bytes)
# backupCount=1 mantém o log atual e no máximo 1 arquivo antigo de backup.
max_bytes_1000_lines = 100_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "tts_agent.log", encoding="utf-8"),
        RotatingFileHandler(
            log_dir / "tts_agent.log",
            maxBytes=10 * 1024 * 1024,  # Limite exato de 10 MB (10.485.760 bytes)
            backupCount=1,
            encoding="utf-8",
        ),
    ],
)

tts_text_logger = logging.getLogger("tts_text_logger")
tts_text_logger.setLevel(logging.INFO)
tts_text_logger.propagate = False
tts_text_handler = logging.FileHandler(log_dir / "tts_texts.log", encoding="utf-8")
tts_text_handler.setFormatter(logging.Formatter("%(message)s"))
tts_text_logger.addHandler(tts_text_handler)

TTS_MANAGER = TTSManager()
PLAYER = AudioPlayer(TTS_MANAGER)


def log_tts_text(text: str):
    if text and text.strip():
        clean_entry = text.strip().replace("\r\n", " ").replace("\n", " ")
        tts_text_logger.info(clean_entry)


# ==============================================================================
# SERVIDOR HTTP
# ==============================================================================
class Handler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

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
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(data.decode("utf-8"))

            if self.path == "/speak":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                device = payload.get("device", None)  # <--- Extrai o novo parâmetro

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                log_tts_text(text)
                logging.info("[SPEAK] Novo texto enviado para a fila local.")
                PLAYER.add_job(text, voice, speed, device=device)  # <--- Passa o device
                self.send_json(200, {"ok": True, "status": "queued"})
                return

            if self.path == "/stop":
                PLAYER.stop()
                logging.info("[STOP] Leitura interrompida.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if self.path == "/generate":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                log_tts_text(text)
                logging.info("[GENERATE] Gerando WAV via Worker Process...")
                wav_data = TTS_MANAGER.generate_wav(text, voice, speed)

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(wav_data)
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})
        except Exception as exc:
            logging.exception("Erro durante requisição POST HTTP.")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        if self.path == "/status":
            with PLAYER.lock:
                status = PLAYER.status
            self.send_json(
                200,
                {
                    "ok": True,
                    "status": status,
                    "model_loaded": TTS_MANAGER.is_loaded(),
                },
            )
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def main():
    # Define o método de spawn para compatibilidade multiplataforma (Windows/Linux)
    mp.set_start_method("spawn", force=True)

    logging.info("Servidor HTTP leve iniciado em http://%s:%d", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        PLAYER.stop()
        TTS_MANAGER.stop_worker()
        try:
            server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

"""Simple HTTP server that exposes /trigger, /start, /stop and /status endpoints (src)."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from .config import HOST, PORT, logging
from pathlib import Path

from .AppState import get_app_state

MODELS_DIR = Path(__file__).parent.parent / "models_cache"

# Lazily retrieve app state (created on first use). Caller can pass models_dir
# to get_app_state if needed.
APP = get_app_state(models_dir=MODELS_DIR)


# ==============================================================================
# SERVIDOR HTTP LEVE
# ==============================================================================
class HTTPServer(BaseHTTPRequestHandler):
    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/warmup":
            logging.info("[GET /warmup] Aquecendo Worker STT antecipadamente...")
            threading.Thread(
                target=APP.stt_manager.ensure_worker_running, daemon=True
            ).start()
            self.send_json(200, {"ok": True, "status": "warming_up"})
            return

        if self.path == "/status":
            with APP.state_lock:
                new_text = []
                while not APP.transcribed_texts.empty():
                    new_text.append(APP.transcribed_texts.get())

                self.send_json(
                    200,
                    {
                        "status": APP.status,
                        "is_speaking": bool(APP.recorder.is_speaking),
                        "is_transcribing": bool(APP.is_transcribing_event.is_set()),
                        "text_chunks": new_text,
                    },
                )
            return

        if self.path == "/start":
            logging.info("[GET /start] Iniciando gravação e subindo Worker STT...")
            with APP.state_lock:
                if APP.status == "recording":
                    self.send_json(409, {"ok": False, "error": "Já está gravando."})
                    return

                APP.start_recording()

            self.send_json(200, {"ok": True})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def do_POST(self) -> None:
        global STATUS
        if self.path == "/stop":
            logging.info("[POST /stop] Pausando gravação.")
            with APP.state_lock:
                APP.stop_recording()

            self.send_json(200, {"ok": True})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def log_message(self, fmt, *args) -> None:
        pass


def run_http_server():
    logging.info(f"Servidor HTTP STT rodando em http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), HTTPServer)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            APP.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        import os

        os._exit(0)

import json
from .AudioPlayer import AudioPlayer
from .TTSManager import TTSManager
from .utils import clean_text

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import HOST, PORT, DEFAULT_VOICE, DEFAULT_SPEED, logging, logger_tts

PLAYER = AudioPlayer()
TTS_MANAGER = TTSManager(PLAYER)


# ==============================================================================
# SERVIDOR HTTP
# ==============================================================================
class HTTPServer(BaseHTTPRequestHandler):
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
                device = payload.get("device", None)
                style = payload.get("style", None)

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                text = clean_text(text)
                textCuteName = text[:30] + "..." if len(text) > 30 else text
                parts = [p.strip() for p in text.split("\n\n") if p.strip()]

                for i, part in enumerate(parts, start=1):
                    logger_tts.info(part)
                    TTS_MANAGER.add_tts_job(
                        text=part.strip(),
                        voice=voice,
                        speed=speed,
                        style=style,
                        device=device,
                        job_name=f" ({i} de {len(parts)}) {textCuteName}",
                    )

                logging.info(
                    "[SPEAK] %d parte(s) enfileirada(s) para o TTSManager.", len(parts)
                )
                self.send_json(200, {"ok": True, "status": "queued"})
                return

            if self.path == "/stop":
                TTS_MANAGER.stop_tts_queue()
                PLAYER.stop()
                logging.info("[STOP] Leitura e filas de TTS/Áudio interrompidas.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if self.path == "/generate":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                style = payload.get("style", None)  # <--- Captura o style também aqui

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                text = clean_text(text)

                logger_tts.info(text)
                logging.info("[GENERATE] Gerando WAV via Worker Process...")
                wav_data = TTS_MANAGER.generate_wav(text, voice, speed, style=style)

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
        if self.path == "/warmup":
            logging.info("[WARMUP] Aquecendo Worker do TTS antecipadamente...")
            TTS_MANAGER.ensure_worker_running()
            self.send_json(200, {"ok": True, "status": "warmed_up"})
            return

        if self.path == "/status":
            with PLAYER.lock:
                status = PLAYER.status
            self.send_json(
                200,
                {
                    "status": status,
                    "model_loaded": TTS_MANAGER.is_loaded(),
                },
            )
            return

        if self.path == "/help":
            import os

            help_file_path = os.path.join(os.path.dirname(__file__), "help.html")

            if os.path.exists(help_file_path):
                with open(help_file_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_json(
                    404, {"ok": False, "error": "Arquivo help.html não encontrado."}
                )
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def run_http_server():
    logging.info("Servidor HTTP TTS rodando em http://%s:%d", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), HTTPServer)

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
        import os

        os._exit(0)

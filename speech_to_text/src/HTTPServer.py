"""Simple HTTP server that exposes /trigger, /start, /stop and /status endpoints."""

import json
import logging
import os
import queue
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import HOST, PORT
from .AppState import get_app_state, STTState

APP = get_app_state()


# ==============================================================================
# SERVIDOR HTTP COM TRATAMENTO DE CONEXÕES ENCERRADAS
# ==============================================================================
class STTThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        exc_type, exc_value, _ = sys.exc_info()

        ignored_errors = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)

        if exc_type and issubclass(exc_type, ignored_errors):
            logging.info(
                "[HTTP] Cliente desconectado: %s (%s)", client_address[0], exc_value
            )
            return

        super().handle_error(request, client_address)


# ==============================================================================
# HANDLER HTTP
# ==============================================================================
class HTTPServer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            self.wfile.write(body)
            self.wfile.flush()

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            logging.debug("[HTTP] Cliente desconectou antes de receber a resposta.")

    def do_GET(self) -> None:

        # ==========================================================================
        # WARMUP
        # ==========================================================================
        if self.path == "/warmup":
            logging.info("[GET /warmup] Aquecendo Worker STT antecipadamente...")
            APP.warmup()
            self.send_json(200, APP.get_status_payload())
            return

        # ==========================================================================
        # START / STATUS e/ou STREAM / STOP
        # ==========================================================================
        if self.path == "/start":
            logging.info("[GET /start] Iniciando gravação...")
            APP.start()
            self.send_json(
                200 if APP.status == STTState.RECORDING else 409,
                APP.get_status_payload(),
            )
            return

        if self.path == "/status":
            logging.info("[GET /status] Verificando status do Worker STT...")

            payload = APP.get_status_payload()
            text_chunks = APP.get_status_queue()

            self.send_json(
                200,
                {
                    **payload,
                    "text_chunks": text_chunks,
                },
            )
            return

        if self.path == "/status/stream":
            logging.info(
                "[GET /status/stream] Iniciando stream SSE para status do Worker STT..."
            )

            client_queue = APP.add_stream_queue()

            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self.wfile.flush()

                last_payload_signature = None

                while True:
                    payload = APP.get_status_payload()
                    text_chunks = APP.get_stream_queue(client_queue)

                    current_signature = (
                        payload["status"],
                        payload["is_speaking"],
                        payload["is_transcribing"],
                    )

                    if current_signature != last_payload_signature or text_chunks:
                        last_payload_signature = current_signature
                        message = (
                            f"data: {json.dumps({**payload, 'text_chunks': text_chunks}, ensure_ascii=False)}\n\n"
                        ).encode("utf-8")

                        self.wfile.write(message)
                        self.wfile.flush()

                    time.sleep(0.1)

            except (
                ConnectionResetError,
                ConnectionAbortedError,
                BrokenPipeError,
                ConnectionError,
            ):
                logging.info("[SSE /status/stream] Cliente desconectado.")

            finally:
                APP.remove_stream_queue(client_queue)

            return

        if self.path == "/stop":
            logging.info("[GET /stop] Pausando gravação.")
            APP.stop()
            self.send_json(200, APP.get_status_payload())
            return

        # ==========================================================================
        # INSERT START / STOP
        # ==========================================================================
        if self.path == "/insert/start":
            logging.info("[GET /insert/start] Ativando inserção no cursor...")
            APP.start_cursor_insert()
            self.send_json(200, APP.get_status_payload())
            return

        if self.path == "/insert/stop":
            logging.info("[GET /insert/stop] Desativando inserção no cursor...")
            APP.stop_cursor_insert()
            self.send_json(200, APP.get_status_payload())
            return

        # ==========================================================================
        # NOT FOUND
        # ==========================================================================
        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def log_message(self, fmt, *args) -> None:
        pass


# ==============================================================================
# INICIALIZAÇÃO DO SERVIDOR
# ==============================================================================
def run_http_server():
    logging.info(f"Servidor HTTP STT rodando em http://{HOST}:{PORT}")
    server = STTThreadingHTTPServer((HOST, PORT), HTTPServer)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            APP.shutdown()
        except Exception:
            logging.exception("Erro durante shutdown da aplicação.")
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        os._exit(0)

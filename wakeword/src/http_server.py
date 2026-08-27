"""Simple HTTP server that exposes /trigger, /start, /stop and /status endpoints (src)."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from .state import TRIGGER_EVENT, LOCK, SESSION_ACTIVE
from .config import HOST, PORT


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
        try:
            if self.path in ["/trigger", "/trigger_wakeword", "/start"]:
                TRIGGER_EVENT.set()
                self.send_json(200, {"ok": True, "status": "triggered"})
                return

            if self.path == "/stop":
                with LOCK:
                    from . import state as _state

                    _state.SESSION_ACTIVE = False
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})
        except Exception as exc:
            logging.exception("Erro em POST")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        if self.path == "/status":
            from . import state as _state

            with _state.LOCK:
                active = _state.SESSION_ACTIVE
            self.send_json(200, {"ok": True, "active": active})
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def run_http_server():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logging.info(f"Servidor HTTP Wakeword rodando em http://{HOST}:{PORT}")
    server.serve_forever()

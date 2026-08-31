"""Simple HTTP server that exposes /trigger, /start, /stop and /status endpoints (src)."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from .state import TRIGGER_EVENT, LOCK
from .config import HOST, PORT, logging

from .overlay import get_overlay, get_state_machine


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

    def do_DELETE(self):
        try:
            if self.path in [
                "/hud/thinking",
                "/hud/processing",
                "/hud/speaking",
                "/hud/listening",
                "/hud/pulse",
            ]:
                self._handle_hud_action(self.path, -1)
                return

            self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})
        except Exception as exc:
            logging.exception("Erro em DELETE")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self):
        try:
            if self.path == "/start":
                TRIGGER_EVENT.set()
                self.send_json(200, {"ok": True, "status": "triggered"})
                return

            if self.path == "/stop":
                with LOCK:
                    from . import state as _state

                    _state.SESSION_ACTIVE = False

                overlay = get_overlay()
                if overlay:
                    overlay.set_thinking(False)
                    overlay.set_speaking(False)
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if self.path in [
                "/hud/thinking",
                "/hud/processing",
                "/hud/speaking",
                "/hud/listening",
                "/hud/pulse",
            ]:
                self._handle_hud_action(self.path, 1)
                return

            if self.path == "/hud/blink":
                state_machine.trigger_blink()
                self.send_json(200, {"ok": True, "state": self.path})
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

    def _handle_hud_action(self, path, delta):
        state_machine = get_state_machine()
        if path == "/hud/thinking":
            state_machine.adjust_counter("thinking", delta)
        elif path == "/hud/processing":
            state_machine.adjust_counter("processing", delta)
        elif path == "/hud/speaking":
            state_machine.adjust_counter("speaking", delta)
        elif path == "/hud/silent":
            state_machine.adjust_counter("speaking", delta)
        elif path == "/hud/listening":
            state_machine.adjust_counter("listening", delta)
        elif path == "/hud/pulse":
            state_machine.adjust_counter("pulse", delta)
        self.send_json(200, {"ok": True, "state": path})


def run_http_server():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logging.info(f"Servidor HTTP Wakeword rodando em http://{HOST}:{PORT}")
    server.serve_forever()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            server.server_close()
        except Exception:
            pass

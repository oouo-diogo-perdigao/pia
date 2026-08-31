import json

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import HOST, PORT, logging

from .InactivityBufferManager import InactivityBufferManager

BUFFER_MANAGER = InactivityBufferManager(inactivity_timeout=3.0)


# ============================================================================
# SERVIDOR HTTP
# ============================================================================
class Handler(BaseHTTPRequestHandler):
    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/process":
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(raw_body)
                user_text = data.get("text", "").strip()
                if not user_text:
                    self.send_json(400, {"ok": False, "error": "Texto ausente."})
                    return
                BUFFER_MANAGER.add_text(user_text)
                self.send_json(200, {"ok": True, "status": "buffered"})
            except Exception as e:
                logging.error("[HTTP ERRO]: %s", e)
                self.send_json(500, {"ok": False, "error": str(e)})
            return
        self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})

    def do_GET(self) -> None:
        if self.path == "/warmup":
            try:
                logging.info("[WARMUP] Aquecendo conexões do Agent/LiteLLM...")
                BUFFER_MANAGER.add_text("Diga Olá!", 0)
                logging.info("[WARMUP] Modelo de IA aquecido com sucesso!")
                self.send_json(200, {"ok": True, "status": "warmed_up"})
            except Exception as e:
                logging.error("[HTTP ERRO]: %s", e)
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})

    # Override para suprimir logs de requisições HTTP padrão
    def log_message(self, fmt, *args) -> None:
        pass


def run_http_server():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logging.info("Servidor HTTP leve iniciado em http://%s:%d", HOST, PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            server.server_close()
        except Exception:
            pass

import hmac
import json
import os
from urllib.parse import urlsplit

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import HOST, PORT, OPENAI_COMPAT_API_KEY, logging


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

    def send_openai_error(
        self,
        code: int,
        message: str,
        *,
        error_type: str = "invalid_request_error",
        param=None,
        error_code=None,
    ):
        self.send_json(
            code,
            {
                "error": {
                    "message": message,
                    "type": error_type,
                    "param": param,
                    "code": error_code,
                }
            },
        )

    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _read_body(self) -> bytes:
        """Lê Content-Length normal e também Transfer-Encoding: chunked."""
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer_encoding:
            chunks = []
            while True:
                size_line = self.rfile.readline()
                if not size_line:
                    break
                size_text = size_line.strip().split(b";", 1)[0]
                if not size_text:
                    continue
                size = int(size_text, 16)
                if size == 0:
                    # Descarta trailers até a linha vazia.
                    while True:
                        trailer = self.rfile.readline()
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                chunks.append(self.rfile.read(size))
                # CRLF após cada chunk.
                self.rfile.read(2)
            return b"".join(chunks)

        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length > 0 else b""

    def _read_json_body(self) -> dict:
        data = self._read_body()
        if not data:
            return {}
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("O corpo JSON deve ser um objeto.")
        return payload

    def _authorize_openai(self) -> bool:
        if not OPENAI_COMPAT_API_KEY:
            return True

        auth = self.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            self.send_openai_error(
                401,
                "API key ausente.",
                error_type="authentication_error",
                error_code="invalid_api_key",
            )
            return False

        supplied = auth[7:].strip()
        if not hmac.compare_digest(supplied, OPENAI_COMPAT_API_KEY):
            self.send_openai_error(
                401,
                "API key inválida.",
                error_type="authentication_error",
                error_code="invalid_api_key",
            )
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            path = self._path()

            # ------------------------------------------------------------------
            # OpenAI-compatible TTS
            # ------------------------------------------------------------------
            if path == "/v1/images/generations":
                # função
                return

            if path == "/v1/images/edits":
                # função
                return

            if path == "/v1/images/variations":
                # função
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logging.info("[HTTP] Cliente desconectou durante a resposta.")
        except Exception as exc:
            logging.exception("Erro durante requisição POST HTTP.")
            path = self._path()
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        path = self._path()

        # Endpoint recomendado para descoberta de modelos em clientes
        # OpenAI-compatible. Neste servidor dedicado, listamos apenas TTS.
        if path == "/v1/models":
            if not self._authorize_openai():
                return
            self.send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "gpt-image-1",
                            "object": "model",
                            "owned_by": "local",
                        }
                    ],
                },
            )
            return

        self.send_json(404, {"ok": False, "ver": 2})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def run_stt_server():
    logging.info("Servidor HTTP TTS rodando em http://%s:%d", HOST, PORT)
    logging.info("Endpoint OpenAI TTS: http://%s:%s/v1/audio/speech", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), HTTPServer)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            server.server_close()
        except Exception:
            pass

        os._exit(0)

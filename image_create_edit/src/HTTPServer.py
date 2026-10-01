from __future__ import annotations

import base64
import hmac
import json
import logging
import mimetypes
import time
import uuid
from urllib.parse import urlsplit

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .ImageManager import IMAGE_MANAGER, OpenAIImageRequestError, decode_data_url
from .ComfyUIClient import ComfyUIError
from .config import (
    HOST,
    PORT,
    OPENAI_COMPAT_API_KEY,
    OPENAI_IMAGE_MODEL_ID,
    PUBLIC_BASE_URL,
    OUTPUT_CACHE_DIR,
    OUTPUT_CACHE_TTL_SECONDS,
)
from .multipart_utils import parse_multipart, extension_for_content_type


def _cleanup_output_cache() -> None:
    now = time.time()
    try:
        for path in OUTPUT_CACHE_DIR.iterdir():
            if path.is_file() and now - path.stat().st_mtime > OUTPUT_CACHE_TTL_SECONDS:
                try:
                    path.unlink()
                except OSError:
                    pass
    except Exception:
        logging.exception("[IMAGE CACHE] Falha ao limpar arquivos expirados.")


def _cache_image(image_bytes: bytes, extension: str = ".png") -> str:
    extension = extension if extension.startswith(".") else f".{extension}"
    token = f"{uuid.uuid4().hex}{extension}"
    (OUTPUT_CACHE_DIR / token).write_bytes(image_bytes)
    return token


class HTTPServer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Requested-With",
        )

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
                    while True:
                        trailer = self.rfile.readline()
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                chunks.append(self.rfile.read(size))
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

    def _public_base_url(self) -> str:
        if PUBLIC_BASE_URL:
            return PUBLIC_BASE_URL
        proto = (
            self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip() or "http"
        )
        host = self.headers.get("Host") or f"{HOST}:{PORT}"
        return f"{proto}://{host}".rstrip("/")

    def _send_image_response(
        self, images: list[bytes], *, response_format: str = "b64_json"
    ):
        response_format = (response_format or "b64_json").strip().lower()
        if response_format not in {"b64_json", "url"}:
            self.send_openai_error(
                400,
                "response_format deve ser 'b64_json' ou 'url'.",
                param="response_format",
            )
            return

        _cleanup_output_cache()
        data = []
        if response_format == "url":
            base_url = self._public_base_url()
            for image_bytes in images:
                token = _cache_image(image_bytes, ".png")
                data.append({"url": f"{base_url}/v1/images/files/{token}"})
        else:
            for image_bytes in images:
                data.append({"b64_json": base64.b64encode(image_bytes).decode("ascii")})

        self.send_json(200, {"created": int(time.time()), "data": data})

    def _read_edit_or_variation(self):
        content_type = self.headers.get("Content-Type", "")
        body = self._read_body()

        if content_type.lower().startswith("multipart/form-data"):
            return parse_multipart(content_type, body)

        if content_type.lower().startswith("application/json"):
            payload = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(payload, dict):
                raise OpenAIImageRequestError("O corpo JSON deve ser um objeto.")
            fields = {
                str(k): str(v)
                for k, v in payload.items()
                if k not in {"image", "mask"} and v is not None
            }
            files = {}

            image_value = payload.get("image")
            image_values = (
                image_value
                if isinstance(image_value, list)
                else ([image_value] if image_value is not None else [])
            )
            image_files = []
            for index, value in enumerate(image_values):
                data, mime = decode_data_url(value)
                image_files.append(
                    {
                        "filename": f"image_{index}{extension_for_content_type(mime)}",
                        "content_type": mime,
                        "data": data,
                    }
                )
            if image_files:
                files["image"] = image_files

            if payload.get("mask"):
                data, mime = decode_data_url(payload["mask"])
                files["mask"] = [
                    {
                        "filename": f"mask{extension_for_content_type(mime)}",
                        "content_type": mime,
                        "data": data,
                    }
                ]
            return fields, files

        raise OpenAIImageRequestError("Use multipart/form-data ou application/json.")

    @staticmethod
    def _first_file(files: dict, field: str, *, required: bool):
        items = files.get(field) or files.get(f"{field}[]") or []
        if not items:
            if required:
                raise OpenAIImageRequestError(
                    f"O arquivo '{field}' é obrigatório.", param=field
                )
            return None
        return items[0]

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        path = self._path()
        try:
            if not self._authorize_openai():
                return

            if path == "/v1/images/generations":
                try:
                    payload = self._read_json_body()
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    self.send_openai_error(400, f"JSON inválido: {exc}")
                    return
                logging.info(
                    "[IMAGE] Requisição de geração de imagem recebida. payload=%s",
                    payload,
                )
                images = IMAGE_MANAGER.generate(payload)
                self._send_image_response(
                    images, response_format=payload.get("response_format", "b64_json")
                )
                return

            if path == "/v1/images/edits":
                logging.info(
                    "[IMAGE] Requisição de edição de imagem recebida. payload=%s",
                    self.headers,
                )
                fields, files = self._read_edit_or_variation()
                image = self._first_file(files, "image", required=True)
                mask = self._first_file(files, "mask", required=False)
                images = IMAGE_MANAGER.edit(fields=fields, image=image, mask=mask)
                self._send_image_response(
                    images, response_format=fields.get("response_format", "b64_json")
                )
                return

            if path == "/v1/images/variations":
                logging.info("[IMAGE] Requisição de variação de imagem recebida.")
                fields, files = self._read_edit_or_variation()
                image = self._first_file(files, "image", required=True)
                images = IMAGE_MANAGER.variation(fields=fields, image=image)
                self._send_image_response(
                    images, response_format=fields.get("response_format", "b64_json")
                )
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})
            return

        except OpenAIImageRequestError as exc:
            self.send_openai_error(exc.status, str(exc), param=exc.param)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logging.info("[HTTP] Cliente desconectou durante a resposta.")
        except (ComfyUIError, TimeoutError) as exc:
            logging.exception("[IMAGE] Falha no ComfyUI.")
            self.send_openai_error(
                500,
                str(exc),
                error_type="server_error",
                error_code="image_generation_error",
            )
        except Exception as exc:
            logging.exception("[IMAGE] Erro durante requisição POST HTTP.")
            self.send_openai_error(
                500,
                str(exc),
                error_type="server_error",
                error_code="image_generation_error",
            )

    def do_GET(self):
        path = self._path()

        if path == "/v1/models":
            logging.info("[IMAGE] Requisição de listagem de modelos recebida.")
            if not self._authorize_openai():
                return
            self.send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": OPENAI_IMAGE_MODEL_ID,
                            "object": "model",
                            "created": 0,
                            "owned_by": "local",
                        }
                    ],
                },
            )
            return

        if path == "/health":
            logging.info("[IMAGE] Requisição de verificação de saúde recebida.")
            try:
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "comfyui": True,
                        "model_alias": OPENAI_IMAGE_MODEL_ID,
                        "system_stats": IMAGE_MANAGER.health(),
                    },
                )
            except Exception as exc:
                self.send_json(503, {"ok": False, "comfyui": False, "error": str(exc)})
            return

        if path.startswith("/v1/images/files/"):
            logging.info("[IMAGE] Requisição de arquivo de imagem recebida.")
            token = path[len("/v1/images/files/") :]
            if not token or "/" in token or "\\" in token or ".." in token:
                self.send_json(404, {"ok": False})
                return
            file_path = OUTPUT_CACHE_DIR / token
            if not file_path.is_file():
                self.send_json(404, {"ok": False})
                return
            data = file_path.read_bytes()
            content_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_json(404, {"ok": False, "ver": 3})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def run_image_server():
    logging.info("Servidor HTTP IMAGE rodando em http://%s:%d", HOST, PORT)
    logging.info(
        "Endpoint OpenAI Images: http://%s:%s/v1/images/generations", HOST, PORT
    )
    server = ThreadingHTTPServer((HOST, PORT), HTTPServer)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor de imagens...")
    finally:
        try:
            server.server_close()
        except Exception:
            pass

import hmac
import base64
import json
import os
import sys
import time
import re

from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .TTSManager import TTSManager
from .STTManager import STTManager, SATState
from .ICEManager import ICEManager, OpenAIImageRequestError, decode_data_url
from .state import TRIGGER_EVENT, LOCK
from .PiaOverlay import get_overlay, get_state_machine

from .utils import clean_text, parse_multipart, extension_for_content_type
from .config import (
    logging,
    HOST,
    PORT,
    OPENAI_COMPAT_API_KEY,
    OPENAI_COMPAT_MAX_UPLOAD_BYTES,
    PUBLIC_BASE_URL,
    TTS_DEFAULT_SPEED,
    logger_tts,
)

from .ComfyUIClient import ComfyUIError

STT_MANAGER = STTManager()
TTS_MANAGER = TTSManager()
ICE_MANAGER = ICEManager()

from .InactivityBufferManager import InactivityBufferManager

BUFFER_MANAGER = InactivityBufferManager(inactivity_timeout=3.0)

"""Simple HTTP server that exposes /trigger, /start, /stop and /status endpoints (src)."""


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

    # ==============================================================================
    # Request helpers
    # ==============================================================================
    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Requested-With",
        )

    def _send(
        self, code: int, body: bytes, content_type: str, extra_headers: dict = None
    ) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            logging.debug("[HTTP] Cliente desconectou antes de receber a resposta.")

    def send_json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _authorize_openai_request(self) -> bool:
        """Optional Bearer token check for /v1 compatibility routes.

        When OPENAI_COMPAT_API_KEY is empty, authentication is intentionally
        disabled. This is convenient for a local-only service and lets Open WebUI
        use any non-empty placeholder key it requires in its settings UI.
        """
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

    def _parse_multipart(self, body: bytes) -> tuple[dict[str, str], dict[str, dict]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise ValueError("Content-Type must be multipart/form-data.")

        # The stdlib email parser understands MIME multipart boundaries well and,
        # unlike the deprecated cgi module, remains available on modern Python.
        mime_message = BytesParser(policy=email_policy).parsebytes(
            (f"Content-Type: {content_type}\r\n" "MIME-Version: 1.0\r\n" "\r\n").encode(
                "utf-8"
            )
            + body
        )

        if not mime_message.is_multipart():
            raise ValueError("Invalid multipart/form-data body.")

        fields: dict[str, str] = {}
        files: dict[str, dict] = {}

        for part in mime_message.iter_parts():
            disposition = part.get("Content-Disposition", "")
            if "form-data" not in disposition.lower():
                continue

            name = part.get_param("name", header="content-disposition")
            if not name:
                continue

            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()

            if filename is not None:
                files[name] = {
                    "filename": filename,
                    "content_type": part.get_content_type(),
                    "data": payload,
                }
            else:
                charset = part.get_content_charset() or "utf-8"
                fields[name] = payload.decode(charset, errors="replace")

        return fields, files

    def _read_body(self) -> bytes | None:
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()

        # aiohttp/Open WebUI may stream multipart file uploads using HTTP chunked
        # transfer encoding, in which case Content-Length is intentionally absent.
        if "chunked" in transfer_encoding:
            chunks: list[bytes] = []
            total = 0

            try:
                while True:
                    size_line = self.rfile.readline()
                    if not size_line:
                        raise ValueError("Unexpected end of chunked request body.")

                    size_token = size_line.split(b";", 1)[0].strip()
                    if not size_token:
                        continue
                    chunk_size = int(size_token, 16)

                    if chunk_size == 0:
                        # Consume optional trailer headers up to the terminating CRLF.
                        while True:
                            trailer = self.rfile.readline()
                            if trailer in (b"\r\n", b"\n", b""):
                                break
                        break

                    total += chunk_size
                    if total > OPENAI_COMPAT_MAX_UPLOAD_BYTES:
                        self.send_openai_error(
                            413,
                            f"Request body exceeds the configured limit of {OPENAI_COMPAT_MAX_UPLOAD_BYTES} bytes.",
                            error_type="request_too_large",
                        )
                        return {}

                    chunk = self.rfile.read(chunk_size)
                    if len(chunk) != chunk_size:
                        raise ValueError("Incomplete HTTP chunk in request body.")
                    chunks.append(chunk)

                    # Every HTTP chunk is followed by CRLF.
                    terminator = self.rfile.read(2)
                    if terminator != b"\r\n":
                        raise ValueError("Invalid HTTP chunk terminator.")

                data = b"".join(chunks)
                payload = json.loads(data.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("O corpo JSON deve ser um objeto.")
                return payload

            except (ValueError, OSError) as exc:
                self.send_openai_error(400, f"Invalid chunked request body: {exc}")
                return {}

        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self.send_openai_error(411, "Content-Length header is required.")
            return {}

        try:
            content_length = int(raw_length)
        except ValueError:
            self.send_openai_error(400, "Invalid Content-Length header.")
            return {}

        if content_length < 0:
            self.send_openai_error(400, "Invalid Content-Length header.")
            return {}

        if content_length > OPENAI_COMPAT_MAX_UPLOAD_BYTES:
            self.send_openai_error(
                413,
                f"Request body exceeds the configured limit of {OPENAI_COMPAT_MAX_UPLOAD_BYTES} bytes.",
                error_type="request_too_large",
            )
            return {}

        data = self.rfile.read(content_length)
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("O corpo JSON deve ser um objeto.")
        return payload

    def _read_json_body(self) -> dict:
        data = self._read_body()
        if not data:
            return {}
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("O corpo JSON deve ser um objeto.")
        return payload

    def send_openai_error(
        self,
        code: int,
        message: str,
        *,
        error_type: str = "invalid_request_error",
        param: str | None = None,
        error_code: str | None = None,
    ) -> None:
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

        ICE_MANAGER._cleanup_output_cache()
        data = []
        if response_format == "url":
            base_url = PUBLIC_BASE_URL
            for image_bytes in images:
                token = ICE_MANAGER._cache_image(image_bytes, ".png")
                data.append({"url": f"{base_url}/v1/images/files/{token}"})
        else:
            for image_bytes in images:
                data.append({"b64_json": base64.b64encode(image_bytes).decode("ascii")})

        self.send_json(200, {"created": int(time.time()), "data": data})

    def _handle_hud_action(self, path, delta):
        state_machine = get_state_machine()
        if path == "/ove/thinking":
            state_machine.adjust_counter("thinking", delta)
        elif path == "/ove/processing":
            state_machine.adjust_counter("processing", delta)
        elif path == "/ove/speaking":
            state_machine.adjust_counter("speaking", delta)
        elif path == "/ove/silent":
            state_machine.adjust_counter("speaking", delta)
        elif path == "/ove/listening":
            state_machine.adjust_counter("listening", delta)
        elif path == "/ove/pulse":
            state_machine.adjust_counter("pulse", delta)
        self.send_json(200, {"ok": True, "state": path})

    def do_OPTIONS(self) -> None:
        self._send(204, b"", "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        path = self._path()

        # ======================================================================
        # OpenAI-compatible
        # ======================================================================
        if path.startswith("/v1/"):
            # region (collapsed) Authorization
            if not self._authorize_openai_request():
                return
            # endregion
            if path == "/v1/models":
                logging.info("[IMAGE] Requisição de listagem de modelos recebida.")
                models = (
                    TTS_MANAGER.models() + STT_MANAGER.models() + ICE_MANAGER.models()
                )
                self.send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": model_id,
                                "object": "model",
                                "created": 0,
                                "owned_by": "local",
                            }
                            for model_id in models
                        ],
                    },
                )
                return

            if path == "/v1/audio/voices":
                voices = TTS_MANAGER.get_voices()
                self.send_json(200, voices)
                return

            if path.startswith("/v1/images/files/"):
                logging.info("[IMAGE] Requisição de arquivo de imagem recebida.")

                token = path[len("/v1/images/files/") :]
                if not token or "/" in token or "\\" in token or ".." in token:
                    self.send_json(404, {"ok": False})
                    return

                content_type, data = ICE_MANAGER.getImage(token)

                if not data:
                    self.send_json(404, {"ok": False})
                    return

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, max-age=300")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
                return

        # ======================================================================
        # START / STATUS e/ou STREAM / STOP
        # ======================================================================
        if path == "/stt/start":
            logging.info("[GET /stt/start] Iniciando gravação...")
            STT_MANAGER.start()
            self.send_json(
                200 if STT_MANAGER.status == SATState.RECORDING else 409,
                STT_MANAGER.get_status_payload(),
            )
            return

        if path == "/stt/stop":
            logging.info("[GET /stt/stop] Pausando gravação.")
            STT_MANAGER.stop()
            self.send_json(200, STT_MANAGER.get_status_payload())
            return

        if path == "/stt/status":
            logging.info("[GET /stt/status] Verificando status do Worker STT...")

            payload = STT_MANAGER.get_status_payload()
            text_chunks = STT_MANAGER.get_status_queue()

            self.send_json(
                200,
                {
                    **payload,
                    "text_chunks": text_chunks,
                },
            )
            return

        if path == "/stt/status/stream":
            logging.info(
                "[GET /stt/status/stream] Iniciando stream SSE para status do Worker STT..."
            )

            client_queue = STT_MANAGER.add_stream_queue()

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
                    payload = STT_MANAGER.get_status_payload()
                    text_chunks = STT_MANAGER.get_stream_queue(client_queue)

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
                logging.info("[SSE /stt/status/stream] Cliente desconectado.")

            finally:
                STT_MANAGER.remove_stream_queue(client_queue)

            return

        if path == "/tts/status":
            logging.info("[GET /tts/status] Verificando status do Worker TTS...")
            with TTS_MANAGER.lock:
                status = TTS_MANAGER.status
            self.send_json(
                200,
                {
                    "status": status,
                    "model_loaded": TTS_MANAGER.is_loaded(),
                },
            )
            return

        if path == "/tts/status/stream":
            logging.info(
                "[GET /tts/status/stream] Iniciando stream SSE para status do Worker TTS..."
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, Authorization"
            )
            self.end_headers()

            last_status = None
            try:
                while True:
                    with TTS_MANAGER.lock:
                        current_status = TTS_MANAGER.status

                    if current_status != last_status:
                        payload = json.dumps({"status": current_status})
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last_status = current_status

                    time.sleep(0.1)
            except Exception:
                pass
            return

        if path == "/tts/help":
            logging.info("[GET /tts/help] Exibindo página de ajuda do TTS...")
            help_file_path = os.path.join(os.path.dirname(__file__), "help.html")

            if os.path.exists(help_file_path):
                with open(help_file_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header(
                    "Access-Control-Allow-Headers", "Content-Type, Authorization"
                )
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_json(
                    404, {"ok": False, "error": "Arquivo help.html não encontrado."}
                )
            return

        if path == "/ove/status":
            from . import state as _state

            with _state.LOCK:
                active = _state.SESSION_ACTIVE
            self.send_json(200, {"ok": True, "active": active})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def do_POST(self) -> None:
        try:
            path = self._path()
            body = self._read_body()

            # ======================================================================
            # OpenAI-compatible
            # ======================================================================
            if path.startswith("/v1/"):
                # region (collapsed) Authorization
                if not self._authorize_openai_request():
                    return
                # endregion

                # ======================================================================
                # Audio
                # ======================================================================

                if path == "/v1/audio/speech":
                    # region (collapsed) text (input)
                    text = body.get("input", "")
                    if not isinstance(text, str) or not text.strip():
                        self.send_openai_error(
                            400,
                            "O campo 'input' deve conter texto.",
                            param="input",
                        )
                        return

                    if len(text) > 4096:
                        self.send_openai_error(
                            400,
                            "O campo 'input' excede o limite de 4096 caracteres.",
                            param="input",
                        )
                        return
                    # endregion
                    # region (collapsed) model
                    model = body.get("model") or "tts-1"
                    if not isinstance(model, str):
                        self.send_openai_error(
                            400, "O campo 'model' deve ser texto.", param="model"
                        )
                        return
                    # endregion
                    # region (collapsed) speed
                    try:
                        speed = float(body.get("speed", 1.0))
                    except (TypeError, ValueError):
                        self.send_openai_error(
                            400, "O campo 'speed' é inválido.", param="speed"
                        )
                        return

                    if not 0.25 <= speed <= 4.0:
                        self.send_openai_error(
                            400,
                            "O campo 'speed' deve estar entre 0.25 e 4.0.",
                            param="speed",
                        )
                        return
                    # endregion
                    # region (collapsed) response_format
                    response_format = (
                        str(body.get("response_format", "mp3")).lower().strip()
                    )
                    if response_format not in TTS_MANAGER.formats():
                        self.send_openai_error(
                            400,
                            "response_format deve ser mp3, opus, aac, flac, wav ou pcm.",
                            param="response_format",
                        )
                        return
                    # endregion
                    # region (collapsed) stream_format
                    stream_format = (
                        str(body.get("stream_format", "audio")).lower().strip()
                    )
                    if stream_format not in ("audio", ""):
                        self.send_openai_error(
                            400,
                            "Este backend local suporta stream_format='audio'; SSE ainda não é suportado.",
                            param="stream_format",
                        )
                        return
                    # endregion
                    # region (collapsed) instructions / style
                    instructions = body.get("instructions")
                    style = (
                        instructions
                        if isinstance(instructions, str) and instructions.strip()
                        else None
                    )
                    if style is None:
                        # Extensão retrocompatível com seu endpoint próprio.
                        local_style = body.get("style")
                        style = (
                            local_style
                            if isinstance(local_style, str) and local_style.strip()
                            else None
                        )
                    # endregion
                    # region (collapsed) voice
                    voice = body.get("voice")
                    voice = TTS_MANAGER.resolve_voice(voice, style)
                    # endregion

                    text = clean_text(text)

                    if not text.strip():
                        self.send_openai_error(
                            400,
                            "O texto ficou vazio após a normalização.",
                            param="input",
                        )
                        return

                    logger_tts.info(text)
                    logging.info(
                        "[OPENAI TTS] model=%s voice=%s format=%s speed=%s style=%s",
                        model,
                        voice,
                        response_format,
                        speed,
                        bool(style),
                    )

                    audio_data = TTS_MANAGER.generate(
                        text,
                        voice,
                        speed,
                        style=style,
                        job_name="OpenAI-compatible /v1/audio/speech",
                        output_format=response_format,
                    )

                    mime = TTS_MANAGER.formats()[response_format]
                    extra = {
                        "Content-Disposition": f'inline; filename="speech.{response_format}"'
                    }
                    self._send(200, audio_data, mime, extra_headers=extra)

                    return

                if path == "/v1/audio/transcriptions":
                    # se o objeto for vazio da return
                    if not body:
                        self.send_openai_error(400, "Corpo JSON vazio.")
                        return

                    content_type = self.headers.get("Content-Type", "").lower()

                    if content_type.startswith("application/json"):
                        # Non-standard but explicitly supported by Open WebUI's OpenAI STT
                        # connector when Request Format is set to JSON Base64.
                        try:
                            input_audio = body.get("input_audio") or {}
                            encoded_audio = input_audio.get("data")
                            if not encoded_audio:
                                raise ValueError("Missing input_audio.data.")

                            audio_bytes = base64.b64decode(encoded_audio, validate=True)
                            audio_format = str(input_audio.get("format") or "bin")
                            file_part = {
                                "filename": f"audio.{audio_format}",
                                "content_type": "application/octet-stream",
                                "data": audio_bytes,
                            }
                            fields = {
                                key: str(value)
                                for key, value in body.items()
                                if key != "input_audio" and value is not None
                            }
                        except (
                            ValueError,
                            TypeError,
                            UnicodeDecodeError,
                            json.JSONDecodeError,
                            binascii.Error,
                        ) as exc:
                            self.send_openai_error(
                                400, f"Invalid JSON audio request: {exc}"
                            )
                            return
                    else:
                        try:
                            fields, files = self._parse_multipart(body)
                        except ValueError as exc:
                            self.send_openai_error(400, str(exc))
                            return
                        except Exception:
                            logging.exception(
                                "[POST /v1/audio/transcriptions] Multipart inválido."
                            )
                            self.send_openai_error(
                                400, "Invalid multipart/form-data request body."
                            )
                            return

                        file_part = files.get("file")
                        if not file_part:
                            self.send_openai_error(
                                400,
                                "Missing required multipart field: file.",
                                param="file",
                            )
                            return

                    audio_bytes = file_part["data"]
                    if not audio_bytes:
                        self.send_openai_error(
                            400, "Uploaded audio file is empty.", param="file"
                        )
                        return

                    # The OpenAI API requires a model field. We accept it for wire
                    # compatibility but map every alias to the locally configured STT_MODEL.
                    requested_model = (fields.get("model") or "whisper-1").strip()
                    language = fields.get("language")
                    prompt = (fields.get("prompt") or "").strip() or None
                    response_format = (
                        (fields.get("response_format") or "json").strip().lower()
                    )

                    temperature = None
                    if "temperature" in fields and fields["temperature"].strip():
                        try:
                            temperature = float(fields["temperature"])
                        except ValueError:
                            self.send_openai_error(
                                400,
                                "temperature must be a number.",
                                param="temperature",
                            )
                            return

                    if response_format not in {"json", "text", "verbose_json"}:
                        self.send_openai_error(
                            400,
                            "This local server supports response_format=json, text, or verbose_json.",
                            param="response_format",
                        )
                        return

                    logging.info(
                        "[OPENAI STT] arquivo=%s tipo=%s modelo_solicitado=%s idioma=%s bytes=%d",
                        file_part.get("filename"),
                        file_part.get("content_type"),
                        requested_model,
                        language or "auto",
                        len(audio_bytes),
                    )

                    result = STT_MANAGER.transcribe_request(
                        audio_bytes,
                        language=language,
                        prompt=prompt,
                        temperature=temperature,
                    )

                    if not result.get("ok"):
                        logging.error("[OPENAI STT] Falha: %s", result.get("error"))
                        self.send_openai_error(
                            500,
                            result.get("error") or "Transcription failed.",
                            error_type="server_error",
                        )
                        return

                    text = result.get("text") or ""

                    if response_format == "text":
                        self._send(
                            200, text.encode("utf-8"), "text/plain; charset=utf-8"
                        )
                        return

                    if response_format == "verbose_json":
                        self.send_json(
                            200,
                            {
                                "task": "transcribe",
                                "language": language or "auto",
                                "duration": None,
                                "text": text,
                                "segments": [],
                            },
                        )
                        return

                    # Standard OpenAI-compatible response used by Open WebUI.
                    self.send_json(200, {"text": text})
                    return

                if path == "/v1/audio/translations":
                    self.send_openai_error(
                        501,
                        "This local server does not support audio translation.",
                        error_type="not_implemented",
                    )
                    return

                # curl https://api.openai.com/v1/audio/voice_consents \
                # -X POST \
                # -H "Authorization: Bearer $OPENAI_API_KEY" \
                # -F "name=John Doe" \
                # -F "language=en-US" \
                # -F "recording=@$HOME/consent_recording.wav;type=audio/x-wav"
                # {
                #     "id": "cons_1234",
                #     "created_at": 0,
                #     "language": "language",
                #     "name": "name",
                #     "object": "audio.voice_consent"
                # }

                if path == "/v1/audio/voice_consents":
                    self.send_openai_error(
                        501,
                        "This local server does not support voice consent management.",
                        error_type="not_implemented",
                    )
                    return

                # ======================================================================
                # Image
                # ======================================================================

                if path == "/v1/images/generations":
                    try:
                        payload = self._read_json_body()
                    except (
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                        ValueError,
                    ) as exc:
                        self.send_openai_error(400, f"JSON inválido: {exc}")
                        return
                    logging.info(
                        "[IMAGE] Requisição de geração de imagem recebida. payload=%s",
                        payload,
                    )
                    images = ICE_MANAGER.generate(payload)
                    self._send_image_response(
                        images,
                        response_format=payload.get("response_format", "b64_json"),
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
                    images = ICE_MANAGER.edit(fields=fields, image=image, mask=mask)
                    self._send_image_response(
                        images,
                        response_format=fields.get("response_format", "b64_json"),
                    )
                    return

                if path == "/v1/images/variations":
                    logging.info("[IMAGE] Requisição de variação de imagem recebida.")
                    fields, files = self._read_edit_or_variation()
                    image = self._first_file(files, "image", required=True)
                    images = ICE_MANAGER.variation(fields=fields, image=image)
                    self._send_image_response(
                        images,
                        response_format=fields.get("response_format", "b64_json"),
                    )
                    return

                if path == "/v1/chat/completions":
                    try:
                        content_length = int(self.headers.get("Content-Length", 0))
                        raw_body = self.rfile.read(content_length).decode("utf-8")

                        # Log separado e dedicado das entradas da LLM/APIVocê está me escutando bem?
                        llm_logger = logging.getLogger("llm_trace")
                        llm_logger.info("[LLM INPUT] %s", raw_body)

                        data = json.loads(raw_body)

                        messages = data.get("messages", [])
                        user_text = (
                            messages[-1].get("content", "").strip() if messages else ""
                        )

                        if not user_text:
                            error_payload = (
                                {
                                    "error": {
                                        "message": "Texto ou mensagens ausentes.",
                                        "type": "invalid_request_error",
                                    }
                                }
                                if "v1" in self.path
                                else {"ok": False, "error": "Texto ausente."}
                            )
                            self.send_json(400, error_payload)
                            return

                        is_stream = data.get("stream", False)
                        model_name = data.get("model", "gemini-local")
                        chunk_id = f"chatcmpl-{int(time.time())}"

                        if is_stream:
                            self.send_response(200)
                            self.send_header(
                                "Content-Type", "text/event-stream; charset=utf-8"
                            )
                            self.send_header("Cache-Control", "no-cache")
                            self.send_header("Connection", "keep-alive")
                            self.end_headers()

                            full_response = ""
                            try:
                                for (
                                    chunk_text
                                ) in BUFFER_MANAGER.agent_manager.process_stream(
                                    user_text
                                ):
                                    if not chunk_text:
                                        continue
                                    full_response += chunk_text

                                    chunk_payload = {
                                        "id": chunk_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model_name,
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {"content": chunk_text},
                                                "finish_reason": None,
                                            }
                                        ],
                                    }
                                    self.wfile.write(
                                        f"data: {json.dumps(chunk_payload, ensure_ascii=False)}\n\n".encode(
                                            "utf-8"
                                        )
                                    )
                                    self.wfile.flush()
                            except Exception as ex:
                                error_chunk = f"Erro no stream do agente: {ex}"
                                full_response += error_chunk

                            # Encerramento do stream
                            end_payload = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model_name,
                                "choices": [
                                    {"index": 0, "delta": {}, "finish_reason": "stop"}
                                ],
                            }
                            self.wfile.write(
                                f"data: {json.dumps(end_payload, ensure_ascii=False)}\n\n".encode(
                                    "utf-8"
                                )
                            )
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()

                            llm_logger.info(
                                "[LLM OUTPUT STREAM] Resposta enviada com sucesso: %s",
                                full_response,
                            )

                        else:
                            try:
                                agent_response = BUFFER_MANAGER.agent_manager.process(
                                    user_text
                                )
                            except Exception as ex:
                                agent_response = f"Erro ao executar agente: {ex}"

                            response_payload = {
                                "id": chunk_id,
                                "object": "chat.completion",
                                "created": int(time.time()),
                                "model": model_name,
                                "choices": [
                                    {
                                        "index": 0,
                                        "message": {
                                            "role": "assistant",
                                            "content": agent_response,
                                        },
                                        "finish_reason": "stop",
                                    }
                                ],
                            }
                            llm_logger.info(
                                "[LLM OUTPUT] %s",
                                json.dumps(response_payload, ensure_ascii=False),
                            )
                            self.send_json(200, response_payload)

                    except Exception as e:
                        logging.error("[HTTP ERRO]: %s", e)
                        self.send_json(500, {"ok": False, "error": str(e)})
                    return

            # ======================================================================
            # Endpoints locais existentes
            # ======================================================================
            if path == "/tts/speak":
                text = body.get("text", "")
                speed = float(body.get("speed", TTS_DEFAULT_SPEED))
                device = body.get("device", None)
                style = body.get("style", None)

                # region (collapsed) voice
                voice = body.get("voice")
                voice = TTS_MANAGER.resolve_voice(voice, style)
                # endregion

                # Remove o bloco de metadados <t>...</t> quando estiver
                # no início do texto, com ou sem ** de Markdown.
                # Exemplos removidos:
                # <t>Hora: 10:11 | Data: Jun 17</t>
                # **<t>Hora: 10:11 | Data: Jun 17</t>**
                # Espaços e quebras de linha anteriores também são ignorados.
                text = re.sub(
                    r"^\s*(?:\*\*\s*)?<t>.*?</t>\s*(?:\*\*)?\s*",
                    "",
                    text,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL,
                )

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

            # Rota personalizada para leitura de jogos de rpg escritos
            if path == "/tts/storytelling":
                # rota parecida com /tts/speak, mas textos entre " são lidas com voz diferente
                # (Qwen CustomVoice)
                # Por padrão le os textos como pm_santa e textos entre " com pm_alex
                # Se antes das " tiver identificado interlocutor como por exemplo:
                # 'Texto narrado pm_santa [NomeInterlocutor] "Fala interlocutor." outro exemplo de pm_santa'
                # Utiliza classe especial de registro e classificação de voz para interlocutores.
                # E envia cada trexo de texto para TTS_MANAGER com a voz correta do qwen.

                text = body.get("text", "")
                speed = float(body.get("speed", TTS_DEFAULT_SPEED))
                device = body.get("device", None)

                if not isinstance(text, str) or not text.strip():
                    self.send_json(
                        400,
                        {
                            "ok": False,
                            "error": "Texto vazio.",
                        },
                    )
                    return

                text = clean_text(text)

                if not text.strip():
                    self.send_json(
                        400,
                        {
                            "ok": False,
                            "error": "Texto vazio após normalização.",
                        },
                    )
                    return

                segments = TTS_MANAGER.parse_storytelling_text(text)

                if not segments:
                    self.send_json(
                        400,
                        {
                            "ok": False,
                            "error": "Nenhum trecho válido encontrado.",
                        },
                    )
                    return

                text_cute_name = text[:30] + "..." if len(text) > 30 else text

                queued = []

                story_id = time.time_ns()

                for i, segment in enumerate(segments, start=1):
                    segment_text = segment["text"].strip()
                    voice = segment["voice"]
                    character = segment["character"]
                    segment_style = segment.get("style")

                    if not segment_text:
                        continue

                    logger_tts.info(segment_text)

                    job_name = (
                        f"Storytelling ({i} de {len(segments)}) "
                        f"{character or 'Narrador'} "
                        f"[{voice}] "
                        f"{text_cute_name}"
                    )

                    TTS_MANAGER.add_tts_job(
                        text=segment_text,
                        voice=voice,
                        speed=speed,
                        style=segment_style,
                        device=device,
                        job_name=job_name,
                        story_id=story_id,
                        story_index=i,
                        story_total=len(segments),
                    )

                    queued.append(
                        {
                            "index": i,
                            "character": character,
                            "voice": voice,
                            "style": segment_style,
                            "text": segment_text,
                        }
                    )

                logging.info(
                    "[STORYTELLING] %d trecho(s) enfileirado(s).",
                    len(queued),
                )

                self.send_json(
                    200,
                    {
                        "ok": True,
                        "status": "queued",
                        "segments": queued,
                    },
                )
                return

            # Rota eventstream que recebe trechos do texto organiza em frases e envia para o tts reproduzir.
            # O tts le o texto com pm_santa mas os trechos entre " se antes do texto tiver um
            # identificador de interlocutor entre [], ele envia todo o contexto para a llm decidir
            # se o interlocutor é homem ou mulher, armazena o sexo dele no arquivo de selectedVoices.json.
            # interlocutores identificados como homem usam a voz pm_alex e mulher usa a voz pf_dora
            if path == "/tts/stream_text":
                chunk = body.get("text", "")
                flush = body.get(
                    "flush", False
                )  # Se True, força o processamento do resto do buffer

                if not chunk and not flush:
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                with TTS_MANAGER.text_buffer_lock:
                    TTS_MANAGER.text_buffer += chunk

                    # Usa expressões regulares para separar por pontuações de final de frase
                    # Isso garante que só vamos mandar para o TTS quando a frase concluir
                    sentences = re.split(r"(?<=[.!?\n])\s+", TTS_MANAGER.text_buffer)

                    if flush:
                        # Processa tudo, esvazia o buffer
                        text_to_process = " ".join(sentences).strip()
                        TTS_MANAGER.text_buffer = ""
                        if text_to_process:
                            TTS_MANAGER.add_tts_job_storytelling(text_to_process)
                    else:
                        # Deixa o último item no buffer, pois pode ser uma frase incompleta
                        TTS_MANAGER.text_buffer = (
                            sentences.pop() if len(sentences) > 0 else ""
                        )

                        # Processa as frases completas
                        for sentence in sentences:
                            sentence = sentence.strip()
                            if sentence:
                                TTS_MANAGER.add_tts_job_storytelling(sentence)

                self.send_json(
                    200, {"ok": True, "status": "chunk_received_and_processed"}
                )
                return

            if path == "/tts/stop":
                TTS_MANAGER.stop_tts_queue()
                TTS_MANAGER.stop()
                logging.info("[STOP] Leitura e filas de TTS/Áudio interrompidas.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if path == "/tts/generate":
                text = body.get("text", "")

                style = body.get("style", None)

                # region (collapsed) voice
                voice = body.get("voice")
                voice = TTS_MANAGER.resolve_voice(voice, style)
                # endregion

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                text = clean_text(text)

                logger_tts.info(text)
                logging.info("[GENERATE] Gerando WAV via Worker Process...")
                wav_data = TTS_MANAGER.generate(
                    text,
                    voice,
                    speed=float(body.get("speed", TTS_DEFAULT_SPEED)),
                    style=style,
                    job_name="Personal /tts/generate",
                    output_format="wav",
                )

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header(
                    "Access-Control-Allow-Headers", "Content-Type, Authorization"
                )
                self.end_headers()
                self.wfile.write(wav_data)
                return

            if path == "/ove/start":
                TRIGGER_EVENT.set()
                self.send_json(200, {"ok": True, "status": "triggered"})
                return

            if path == "/ove/stop":
                with LOCK:
                    from . import state as _state

                    _state.SESSION_ACTIVE = False

                overlay = get_overlay()
                if overlay:
                    overlay.set_thinking(False)
                    overlay.set_speaking(False)
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if path in [
                "/ove/thinking",
                "/ove/processing",
                "/ove/speaking",
                "/ove/listening",
                "/ove/pulse",
            ]:
                self._handle_hud_action(path, 1)
                return

            if path == "/ove/blink":
                state_machine.trigger_blink()
                self.send_json(200, {"ok": True, "state": path})
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

        except OpenAIImageRequestError as exc:
            self.send_openai_error(exc.status, str(exc), param=exc.param)
        except (ComfyUIError, TimeoutError) as exc:
            logging.exception("[IMAGE] Falha no ComfyUI.")
            self.send_openai_error(
                500,
                str(exc),
                error_type="server_error",
                error_code="image_generation_error",
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logging.info("[HTTP] Cliente desconectou durante a resposta.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.send_json(400, {"ok": False, "error": f"JSON inválido: {exc}"})
            return
        except Exception as exc:
            logging.exception("Erro durante requisição POST HTTP.")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_DELETE(self):
        try:
            path = self._path()

            if path in [
                "/ove/thinking",
                "/ove/processing",
                "/ove/speaking",
                "/ove/listening",
                "/ove/pulse",
            ]:
                self._handle_hud_action(path, -1)
                return

            self.send_json(404, {"ok": False, "error": "Endpoint não encontrado."})
        except Exception as exc:
            logging.exception("Erro em DELETE")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt, *args) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)


# ==============================================================================
# INICIALIZAÇÃO DO SERVIDOR
# ==============================================================================
def run_http_server():
    logging.info("Servidor HTTP rodando em http://%s:%s", HOST, PORT)

    server = STTThreadingHTTPServer((HOST, PORT), HTTPServer)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        try:
            TTS_MANAGER.shutdown()
        except Exception:
            logging.exception("Erro durante shutdown da aplicação. TTS")
        try:
            STT_MANAGER.shutdown()
        except Exception:
            logging.exception("Erro durante shutdown da aplicação. STT")

        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        os._exit(0)

"""HTTP server for recorder controls and an OpenAI-compatible STT endpoint."""

import hmac
import base64
import binascii
import json
import os
import sys
import io
import shutil
import time
import subprocess
import wave
import re
import threading


from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .AppState import SATState, get_app_state
from .config import (
    logging,
    HOST,
    PORT,
    OPENAI_COMPAT_API_KEY,
    OPENAI_COMPAT_MAX_UPLOAD_BYTES,
    OPENAI_COMPAT_TIMEOUT_SECONDS,
    STT_MODEL,
    DEFAULT_VOICE,
    DEFAULT_SPEED,
    logger_tts,
    BASE_DIR,
    LLM_URL,
    LLM_MODEL,
)


from .AudioPlayer import AudioPlayer
from .TTSManager import TTSManager
from .StoryVoiceRegistry import StoryVoiceRegistry
from .utils import clean_text

import urllib.request

# Buffer global para acumular trechos de texto vindos do eventstream/chunk POST
STREAM_TEXT_BUFFER = ""
STREAM_BUFFER_LOCK = threading.RLock()

APP = get_app_state()

OPENAI_TTS_MODELS = (
    # tts
    "tts-1",
    "tts-1-hd",
    "gpt-4o-mini-tts",
    "gpt-4o-mini-tts-2025-12-15",
    # stt
    "gpt-transcribe",
    "whisper-1",
)

PLAYER = AudioPlayer()
TTS_MANAGER = TTSManager(PLAYER)
STORY_VOICE_REGISTRY = StoryVoiceRegistry(voices=TTS_MANAGER.qwen_voices())

RESPONSE_FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


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

    def _send_bytes(self, code: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Authorization, Content-Type"
            )
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            logging.debug("[HTTP] Cliente desconectou antes de receber a resposta.")

    def send_json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(code, body, "application/json; charset=utf-8")

    def send_text(self, code: int, text: str) -> None:
        self._send_bytes(code, text.encode("utf-8"), "text/plain; charset=utf-8")

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

    @staticmethod
    def resolve_interlocutor_voice(character: str, context: str) -> str:
        """Consulta o cache ou a LLM para decidir a voz (homem = pm_alex, mulher = pf_dora)"""
        cache_file = BASE_DIR / "logs" / "selectedVoices.json"
        cache = {}

        # 1. Tenta carregar do cache
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception as e:
                logging.error(f"[STREAM TTS] Erro ao ler cache: {e}")

        char_key = character.strip().lower()
        if char_key in cache:
            return cache[char_key].get("voice", "pm_alex")

        # 2. Se não está no cache, pergunta para a LLM
        prompt = (
            f"Baseado na fala: '{context}', o personagem '{character}' é homem ou mulher?\n"
            "Responda SOMENTE com 'male' para homem ou 'female' para mulher."
        )

        request_payload = {
            "messages": [
                {
                    "role": "system",
                    "content": "Você classifica gênero de personagens para TTS. Responda apenas com a palavra male ou female.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 10,
        }

        if LLM_MODEL:
            request_payload["model"] = LLM_MODEL

        voice = "pm_alex"  # Fallback padrão homem
        try:
            req = urllib.request.Request(
                LLM_URL.rstrip("/") + "/v1/chat/completions",
                data=json.dumps(request_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))

            content = result["choices"][0]["message"]["content"].strip().lower()

            if "female" in content or "mulher" in content:
                voice = "pf_dora"
            else:
                voice = "pm_alex"

        except Exception as e:
            logging.error(f"[STREAM TTS] Falha ao consultar LLM para {character}: {e}")

        # 3. Salva no cache
        cache[char_key] = {
            "name": character,
            "voice": voice,
            "gender": "female" if voice == "pf_dora" else "male",
        }

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"[STREAM TTS] Erro ao salvar cache: {e}")

        return voice

    @staticmethod
    def process_and_queue_sentences(text: str):
        """Extrai partes de narração e interlocutores e enfileira no TTS"""
        # Procura pelo padrão: [Nome] "Fala" ou apenas "Fala" ou texto normal
        token_re = re.compile(
            r'\[([^\[\]\r\n]+)\]\s*"([^"]+)"'  # [Interlocutor] "fala"
            r"|"
            r'"([^"]+)"',  # "fala sem nome"
            re.MULTILINE,
        )

        cursor = 0
        for match in token_re.finditer(text):
            # Texto de narração (antes das aspas)[cite: 6]
            between = text[cursor : match.start()].strip()
            if between:
                TTS_MANAGER.add_tts_job(
                    text=between,
                    voice="pm_santa",
                    speed=DEFAULT_SPEED,
                    job_name="Narrador (pm_santa)",
                )

            character = match.group(1)

            # Se tem [Personagem]
            if character:
                speech = match.group(2).strip()
                voice = resolve_interlocutor_voice(character, speech)
                if speech:
                    TTS_MANAGER.add_tts_job(
                        text=speech,
                        voice=voice,
                        speed=DEFAULT_SPEED,
                        job_name=f"[{character}] ({voice})",
                    )
            else:
                # Fala sem personagem definido na tag, pode continuar com pm_santa ou outra lógica
                speech = match.group(3).strip()
                if speech:
                    TTS_MANAGER.add_tts_job(
                        text=speech,
                        voice="pm_santa",
                        speed=DEFAULT_SPEED,
                        job_name="Fala Anônima (pm_santa)",
                    )

            cursor = match.end()

        # Sobra da narração no final
        if cursor < len(text):
            narration = text[cursor:].strip()
            if narration:
                TTS_MANAGER.add_tts_job(
                    text=narration,
                    voice="pm_santa",
                    speed=DEFAULT_SPEED,
                    job_name="Narrador (pm_santa)",
                )

    # --------------------------------------------------------------------------
    # Request helpers
    # --------------------------------------------------------------------------
    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def send_audio(self, audio_bytes: bytes, response_format: str):
        mime = RESPONSE_FORMAT_MIME[response_format]
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(audio_bytes)))
        self.send_header(
            "Content-Disposition", f'inline; filename="speech.{response_format}"'
        )
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(audio_bytes)

    def _read_json_body(self) -> dict:
        data = self._read_body()
        if not data:
            return {}
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("O corpo JSON deve ser um objeto.")
        return payload

    @staticmethod
    def _resolve_voice(voice, style):
        """Converte vozes padrão OpenAI em aliases do backend local."""
        if isinstance(voice, dict):
            voice = voice.get("id")

        if not isinstance(voice, str) or not voice.strip():
            return None if style else DEFAULT_VOICE

        voice = voice.strip()
        if voice.lower() in TTS_MANAGER.get_voices():
            # Qwen CustomVoice já possui fallback interno para Ryan quando voice=None.
            return None if style else DEFAULT_VOICE

        return voice

    @staticmethod
    def _convert_wav(wav_data: bytes, response_format: str) -> bytes:
        """Converte o WAV gerado localmente para formatos aceitos pela OpenAI."""
        if response_format == "wav":
            return wav_data

        if response_format == "pcm":
            with wave.open(io.BytesIO(wav_data), "rb") as wf:
                if wf.getsampwidth() != 2:
                    raise RuntimeError("PCM bruto requer áudio PCM16 no backend local.")
                return wf.readframes(wf.getnframes())

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                f"response_format='{response_format}' requer ffmpeg no PATH. "
                "Instale ffmpeg ou use response_format='wav'."
            )

        format_args = {
            "mp3": ["-f", "mp3"],
            "opus": ["-c:a", "libopus", "-f", "opus"],
            "aac": ["-c:a", "aac", "-f", "adts"],
            "flac": ["-f", "flac"],
        }[response_format]

        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                *format_args,
                "pipe:1",
            ],
            input=wav_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            error = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Falha ao converter áudio com ffmpeg: {error}")
        return proc.stdout

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
                        return None

                    chunk = self.rfile.read(chunk_size)
                    if len(chunk) != chunk_size:
                        raise ValueError("Incomplete HTTP chunk in request body.")
                    chunks.append(chunk)

                    # Every HTTP chunk is followed by CRLF.
                    terminator = self.rfile.read(2)
                    if terminator != b"\r\n":
                        raise ValueError("Invalid HTTP chunk terminator.")

                return b"".join(chunks)

            except (ValueError, OSError) as exc:
                self.send_openai_error(400, f"Invalid chunked request body: {exc}")
                return None

        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self.send_openai_error(411, "Content-Length header is required.")
            return None

        try:
            content_length = int(raw_length)
        except ValueError:
            self.send_openai_error(400, "Invalid Content-Length header.")
            return None

        if content_length < 0:
            self.send_openai_error(400, "Invalid Content-Length header.")
            return None

        if content_length > OPENAI_COMPAT_MAX_UPLOAD_BYTES:
            self.send_openai_error(
                413,
                f"Request body exceeds the configured limit of {OPENAI_COMPAT_MAX_UPLOAD_BYTES} bytes.",
                error_type="request_too_large",
            )
            return None

        return self.rfile.read(content_length)

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

    @staticmethod
    def _normalize_language(language: str | None) -> str | None:
        if language is None:
            return None
        value = language.strip()
        if not value:
            return None
        # Open WebUI may expose locale-style values such as pt-BR. faster-whisper
        # expects a language code such as pt, en, es, etc.
        return value.replace("_", "-").split("-", 1)[0].lower()

    def do_OPTIONS(self) -> None:
        self._send_bytes(204, b"", "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        path = self._path()

        # ------------------------------------------------------------------
        # OpenAI-compatible
        # ------------------------------------------------------------------
        if path == "/v1/models":
            if not self._authorize_openai_request():
                return

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
                        for model_id in OPENAI_TTS_MODELS
                    ],
                },
            )
            return

        # ======================================================================
        # WARMUP
        # ======================================================================
        if path == "/stt/warmup":
            logging.info("[GET /warmup] Aquecendo Worker STT antecipadamente...")
            APP.warmup()
            self.send_json(200, APP.get_status_payload())
            return

        if path == "/tts/warmup":
            logging.info("[GET /tts/warmup] Aquecendo Workers TTS antecipadamente...")

            TTS_MANAGER.ensure_worker_running("kokoro")
            TTS_MANAGER.ensure_worker_running("qwen")

            self.send_json(
                200,
                {
                    "ok": True,
                    "status": "warmed_up",
                    "workers": [
                        "kokoro",
                        "qwen",
                    ],
                },
            )
            return

        # ======================================================================
        # START / STATUS e/ou STREAM / STOP
        # ======================================================================
        if path == "/stt/start":
            logging.info("[GET /stt/start] Iniciando gravação...")
            APP.start()
            self.send_json(
                200 if APP.status == SATState.RECORDING else 409,
                APP.get_status_payload(),
            )
            return

        if path == "/stt/status":
            logging.info("[GET /stt/status] Verificando status do Worker STT...")

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

        if path == "/stt/status/stream":
            logging.info(
                "[GET /stt/status/stream] Iniciando stream SSE para status do Worker STT..."
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

        if path == "/stt/stop":
            logging.info("[GET /stt/stop] Pausando gravação.")
            APP.stop()
            self.send_json(200, APP.get_status_payload())
            return

        if path == "/stt/insert/start":
            logging.info("[GET /stt/insert/start] Ativando inserção no cursor...")
            APP.start_cursor_insert()
            self.send_json(200, APP.get_status_payload())
            return

        if path == "/stt/insert/stop":
            logging.info("[GET /stt/insert/stop] Desativando inserção no cursor...")
            APP.stop_cursor_insert()
            self.send_json(200, APP.get_status_payload())
            return

        if path == "/tts/status":
            logging.info("[GET /tts/status] Verificando status do Worker TTS...")
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
                import time

                while True:
                    with PLAYER.lock:
                        current_status = PLAYER.status

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

        if path == "/tts/voices":
            voices = TTS_MANAGER.get_voices()
            self.send_json(200, {"voices": voices})
            return

        self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

    def do_POST(self) -> None:
        try:
            path = self._path()
            try:
                payload = self._read_json_body()
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                if path == "/v1/audio/speech":
                    self.send_openai_error(400, f"JSON inválido: {exc}")
                else:
                    self.send_json(400, {"ok": False, "error": f"JSON inválido: {exc}"})
                return

            # ------------------------------------------------------------------
            # OpenAI-compatible
            # ------------------------------------------------------------------
            if path == "/v1/audio/transcriptions":
                if not self._authorize_openai_request():
                    return

                body = self._read_body()
                if body is None:
                    return

                content_type = self.headers.get("Content-Type", "").lower()

                if content_type.startswith("application/json"):
                    # Non-standard but explicitly supported by Open WebUI's OpenAI STT
                    # connector when Request Format is set to JSON Base64.
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        input_audio = payload.get("input_audio") or {}
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
                            for key, value in payload.items()
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
                language = self._normalize_language(fields.get("language"))
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
                    "[OPENAI STT] arquivo=%s tipo=%s modelo_solicitado=%s modelo_local=%s idioma=%s bytes=%d",
                    file_part.get("filename"),
                    file_part.get("content_type"),
                    requested_model,
                    STT_MODEL,
                    language or "auto",
                    len(audio_bytes),
                )

                result = APP.stt_manager.transcribe_request(
                    audio_bytes,
                    language=language,
                    prompt=prompt,
                    temperature=temperature,
                    timeout=OPENAI_COMPAT_TIMEOUT_SECONDS,
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
                    self.send_text(200, text)
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

            if path == "/v1/audio/speech":
                if not self._authorize_openai_request():
                    return

                text = payload.get("input", "")
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

                model = payload.get("model") or "tts-1"
                if not isinstance(model, str):
                    self.send_openai_error(
                        400, "O campo 'model' deve ser texto.", param="model"
                    )
                    return

                try:
                    speed = float(payload.get("speed", 1.0))
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

                response_format = (
                    str(payload.get("response_format", "mp3")).lower().strip()
                )
                if response_format not in RESPONSE_FORMAT_MIME:
                    self.send_openai_error(
                        400,
                        "response_format deve ser mp3, opus, aac, flac, wav ou pcm.",
                        param="response_format",
                    )
                    return

                stream_format = (
                    str(payload.get("stream_format", "audio")).lower().strip()
                )
                if stream_format not in ("audio", ""):
                    self.send_openai_error(
                        400,
                        "Este backend local suporta stream_format='audio'; SSE ainda não é suportado.",
                        param="stream_format",
                    )
                    return

                # A API OpenAI chama esse controle de "instructions". No seu backend,
                # o conceito equivalente já existe como "style" e seleciona o Qwen-TTS.
                instructions = payload.get("instructions")
                style = (
                    instructions
                    if isinstance(instructions, str) and instructions.strip()
                    else None
                )
                if style is None:
                    # Extensão retrocompatível com seu endpoint próprio.
                    local_style = payload.get("style")
                    style = (
                        local_style
                        if isinstance(local_style, str) and local_style.strip()
                        else None
                    )

                voice = self._resolve_voice(payload.get("voice"), style)
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

                wav_data = TTS_MANAGER.generate_wav(
                    text,
                    voice,
                    speed,
                    style=style,
                    job_name="OpenAI-compatible /v1/audio/speech",
                )
                audio_data = self._convert_wav(wav_data, response_format)
                self.send_audio(audio_data, response_format)

                return

            # ------------------------------------------------------------------
            # Endpoints locais existentes
            # ------------------------------------------------------------------
            if path == "/tts/speak":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                device = payload.get("device", None)
                style = payload.get("style", None)

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

                text = payload.get("text", "")
                speed = float(payload.get("speed", DEFAULT_SPEED))
                device = payload.get("device", None)

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

                segments = STORY_VOICE_REGISTRY.parse_storytelling_text(text)

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
                global STREAM_TEXT_BUFFER

                chunk = payload.get("text", "")
                flush = payload.get(
                    "flush", False
                )  # Se True, força o processamento do resto do buffer

                if not chunk and not flush:
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                with STREAM_BUFFER_LOCK:
                    STREAM_TEXT_BUFFER += chunk

                    # Usa expressões regulares para separar por pontuações de final de frase
                    # Isso garante que só vamos mandar para o TTS quando a frase concluir
                    sentences = re.split(r"(?<=[.!?\n])\s+", STREAM_TEXT_BUFFER)

                    if flush:
                        # Processa tudo, esvazia o buffer
                        text_to_process = " ".join(sentences).strip()
                        STREAM_TEXT_BUFFER = ""
                        if text_to_process:
                            HTTPServer.process_and_queue_sentences(text_to_process)
                    else:
                        # Deixa o último item no buffer, pois pode ser uma frase incompleta
                        STREAM_TEXT_BUFFER = (
                            sentences.pop() if len(sentences) > 0 else ""
                        )

                        # Processa as frases completas
                        for sentence in sentences:
                            sentence = sentence.strip()
                            if sentence:
                                HTTPServer.process_and_queue_sentences(sentence)

                self.send_json(
                    200, {"ok": True, "status": "chunk_received_and_processed"}
                )
                return

            if path == "/tts/stop":
                TTS_MANAGER.stop_tts_queue()
                PLAYER.stop()
                logging.info("[STOP] Leitura e filas de TTS/Áudio interrompidas.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if path == "/tts/generate":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                style = payload.get("style", None)

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                text = clean_text(text)

                logger_tts.info(text)
                logging.info("[GENERATE] Gerando WAV via Worker Process...")
                wav_data = TTS_MANAGER.generate_wav(
                    text,
                    voice,
                    speed,
                    style=style,
                    job_name="Personal /tts/generate",
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

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logging.info("[HTTP] Cliente desconectou durante a resposta.")
        except Exception as exc:
            logging.exception("Erro durante requisição POST HTTP.")
            path = self._path()
            if path == "/v1/audio/speech":
                self.send_openai_error(
                    500,
                    str(exc),
                    error_type="server_error",
                    error_code="tts_generation_error",
                )
            else:
                self.send_json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt, *args) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)


# ==============================================================================
# INICIALIZAÇÃO DO SERVIDOR
# ==============================================================================
def run_sat_server():
    logging.info("Servidor HTTP SAT rodando em http://%s:%s", HOST, PORT)
    logging.info(
        "Endpoint OpenAI SAT: http://%s:%s/v1/audio/transcriptions", HOST, PORT
    )
    server = STTThreadingHTTPServer((HOST, PORT), HTTPServer)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        PLAYER.stop()
        TTS_MANAGER.stop_worker()

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

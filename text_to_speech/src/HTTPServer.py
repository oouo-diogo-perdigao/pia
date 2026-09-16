import hmac
import io
import json
import os
import shutil
import subprocess
import wave
from urllib.parse import urlsplit

from .AudioPlayer import AudioPlayer
from .TTSManager import TTSManager
from .utils import clean_text

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import (
    HOST,
    PORT,
    DEFAULT_VOICE,
    DEFAULT_SPEED,
    OPENAI_COMPAT_API_KEY,
    logging,
    logger_tts,
)

PLAYER = AudioPlayer()
TTS_MANAGER = TTSManager(PLAYER)

# Nomes aceitos pela API OpenAI. O backend local não possui necessariamente
# vozes com esses IDs; por isso eles funcionam como aliases da voz local padrão.
OPENAI_BUILTIN_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
}

OPENAI_TTS_MODELS = (
    "tts-1",
    "tts-1-hd",
    "gpt-4o-mini-tts",
    "gpt-4o-mini-tts-2025-12-15",
)

RESPONSE_FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


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

    @staticmethod
    def _resolve_voice(voice, style):
        """Converte vozes padrão OpenAI em aliases do backend local."""
        if isinstance(voice, dict):
            voice = voice.get("id")

        if not isinstance(voice, str) or not voice.strip():
            return None if style else DEFAULT_VOICE

        voice = voice.strip()
        if voice.lower() in OPENAI_BUILTIN_VOICES:
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

    def _handle_openai_speech(self, payload: dict):
        if not self._authorize_openai():
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
            self.send_openai_error(400, "O campo 'speed' é inválido.", param="speed")
            return

        if not 0.25 <= speed <= 4.0:
            self.send_openai_error(
                400,
                "O campo 'speed' deve estar entre 0.25 e 4.0.",
                param="speed",
            )
            return

        response_format = str(payload.get("response_format", "mp3")).lower().strip()
        if response_format not in RESPONSE_FORMAT_MIME:
            self.send_openai_error(
                400,
                "response_format deve ser mp3, opus, aac, flac, wav ou pcm.",
                param="response_format",
            )
            return

        stream_format = str(payload.get("stream_format", "audio")).lower().strip()
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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
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
            # OpenAI-compatible TTS
            # ------------------------------------------------------------------
            if path == "/v1/audio/speech":
                self._handle_openai_speech(payload)
                return

            # ------------------------------------------------------------------
            # Endpoints locais existentes
            # ------------------------------------------------------------------
            if path == "/speak":
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

            if path == "/stop":
                TTS_MANAGER.stop_tts_queue()
                PLAYER.stop()
                logging.info("[STOP] Leitura e filas de TTS/Áudio interrompidas.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if path == "/generate":
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
                wav_data = TTS_MANAGER.generate_wav(text, voice, speed, style=style)

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_cors_headers()
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
                            "id": model,
                            "object": "model",
                            "created": 0,
                            "owned_by": "local",
                        }
                        for model in OPENAI_TTS_MODELS
                    ],
                },
            )
            return

        if path == "/warmup":
            logging.info("[WARMUP] Aquecendo Worker do TTS antecipadamente...")
            TTS_MANAGER.ensure_worker_running()
            self.send_json(200, {"ok": True, "status": "warmed_up"})
            return

        if path == "/status":
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

        # Abordagem Server-Sent Events (SSE) do status local.
        if path == "/status/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_cors_headers()
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

        if path == "/help":
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
        PLAYER.stop()
        TTS_MANAGER.stop_worker()
        try:
            server.server_close()
        except Exception:
            pass

        os._exit(0)

import io
import json
import logging
import os
import queue
import re
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch
from kokoro import KModel, KPipeline

# Carrega as variáveis do arquivo .env
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT", 8765))
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "pm_santa").strip()
DEFAULT_SPEED = float(os.getenv("DEFAULT_SPEED", "1.00").strip())
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "24000").strip())
IDLE_TIMEOUT = int(
    os.getenv("IDLE_TIMEOUT", "600").strip()
)  # Tempo de inatividade (10 min) para liberar VRAM da GPU

DEVICE = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu").strip()

# ==============================================================================
# CONFIGURAÇÃO DE LOGS (LOG PRINCIPAL + LOG SECUNDÁRIO DE TEXTOS)
# ==============================================================================
log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# 1. Configuração do Log Geral da Aplicação
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            log_dir / "tts_agent.log",
            encoding="utf-8",
        ),
    ],
)

# 2. Logger Exclusivo para os Textos Enviados (TTS)
tts_text_logger = logging.getLogger("tts_text_logger")
tts_text_logger.setLevel(logging.INFO)
tts_text_logger.propagate = False  # Não duplica as mensagens no tts_agent.log

tts_text_handler = logging.FileHandler(
    log_dir / "tts_texts.log",
    encoding="utf-8",
)
# Formatador limpo: apenas a mensagem, sem prefixos, níveis ou timestamps
tts_text_handler.setFormatter(logging.Formatter("%(message)s"))
tts_text_logger.addHandler(tts_text_handler)


# Função utilitária para salvar no log secundário
def log_tts_text(text: str):
    """Registra o texto enviado no arquivo de log secundário (tts_texts.log)."""
    if text and text.strip():
        # Substitui quebras de linha internas para manter cada envio em um único registro no log
        clean_entry = text.strip().replace("\r\n", " ").replace("\n", " ")
        tts_text_logger.info(clean_entry)


# ==============================================================================

MODEL = None
PIPELINE = None
MODEL_LOCK = threading.Lock()

LAST_USED = time.monotonic()


def get_pipeline():
    """Carrega o modelo Kokoro sob demanda (Lazy Loading)."""
    global MODEL, PIPELINE, LAST_USED
    with MODEL_LOCK:
        LAST_USED = time.monotonic()
        if PIPELINE is None:
            logging.info("Carregando Kokoro no dispositivo: %s", DEVICE)
            MODEL = KModel().to(DEVICE).eval()
            PIPELINE = KPipeline(lang_code="p", model=MODEL)
            logging.info("Kokoro carregado com sucesso!")
        return PIPELINE


def unload_model():
    """Libera o modelo da memória RAM/VRAM se ficar inativo."""
    global MODEL, PIPELINE
    with MODEL_LOCK:
        if PIPELINE is not None or MODEL is not None:
            logging.info("Descarregando Kokoro da GPU/RAM por inatividade...")
            PIPELINE = None
            MODEL = None

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass
            logging.info("Memória liberada! Servidor continua em espera.")


# PLAYER LOCAL PARA O AHK
class AudioPlayer:
    def __init__(self):
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.status = "idle"
        self.worker_thread = None
        self.audio_stream = None

    def add_job(self, text, voice, speed):
        with self.lock:
            self.queue.put({"text": text, "voice": voice, "speed": speed})
            if self.worker_thread is None or not self.worker_thread.is_alive():
                self.worker_thread = threading.Thread(
                    target=self._play_loop, daemon=True
                )
                self.worker_thread.start()

    def stop(self):
        with self.lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break

            if self.audio_stream is not None:
                try:
                    self.audio_stream.abort()
                except Exception:
                    pass

            self.status = "idle"

    def _play_loop(self):
        pipeline = get_pipeline()
        try:
            with sd.OutputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=2048
            ) as stream:
                with self.lock:
                    self.audio_stream = stream

                while True:
                    try:
                        item = self.queue.get(timeout=1.0)
                    except queue.Empty:
                        break

                    text, voice, speed = item["text"], item["voice"], item["speed"]

                    with self.lock:
                        self.status = "playing"

                    chunks = split_text(clean_text(text))
                    for chunk in chunks:
                        generator = pipeline(
                            chunk, voice=voice, speed=speed, split_pattern=r"\n+"
                        )
                        for _, _, audio in generator:
                            audio_data = np.asarray(audio, dtype=np.float32)
                            position = 0
                            while position < len(audio_data):
                                end = min(position + 2048, len(audio_data))
                                stream.write(audio_data[position:end].reshape(-1, 1))
                                position = end
        except Exception:
            logging.exception("Erro no player de áudio AHK.")
        finally:
            with self.lock:
                self.audio_stream = None
                self.status = "idle"


PLAYER = AudioPlayer()


# SÍNTESE DE ÁUDIO EM BUFFER PARA O SILLYTAVERN
def generate_audio_wav(text, voice, speed):
    pipeline = get_pipeline()
    cleaned = clean_text(text)
    chunks = split_text(cleaned)

    audio_segments = []
    for chunk in chunks:
        generator = pipeline(chunk, voice=voice, speed=speed, split_pattern=r"\n+")
        for _, _, audio in generator:
            audio_data = np.asarray(audio, dtype=np.float32)
            audio_segments.append(audio_data)

    if not audio_segments:
        return None

    full_audio = np.concatenate(audio_segments)
    audio_pcm16 = (full_audio * 32767).clip(-32768, 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_pcm16.tobytes())

    return buffer.getvalue()


def clean_text(text):
    # Remove caracteres nulos
    text = text.replace("\x00", " ")
    # TRATAMENTO DE QUEBRA DE LINHA: Converte parágrafos e quebras simples em pontuação de pausa
    text = re.sub(r"\r\n|\r|\n", ". ", text)
    # Normaliza quebras de linha
    text = re.sub(r"\r\n?", "\n", text)
    # Remove links Markdown, mantendo apenas o texto visível.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove blocos de código Markdown.
    text = re.sub(r"```(?:\w+)?\s*([\s\S]*?)```", r"\1", text)
    # Remove código inline.
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove negrito e itálico Markdown.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text)
    # Remove cabeçalhos Markdown.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    # Remove citações Markdown.
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    # Remove marcadores de listas.
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    # Remove marcadores de checkbox.
    text = re.sub(r"(?m)^\s*\[[ xX]\]\s*", "", text)
    # Remove linhas horizontais Markdown.
    text = re.sub(r"(?m)^\s*([-*_])(?:\s*\1){2,}\s*$", "", text)
    # Remove espaços repetidos.
    text = re.sub(r"[ \t]+", " ", text)
    # Reduz excesso de linhas vazias.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text, max_chars=420):
    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    chunks = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) > max_chars:
            if current:
                chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


class Handler(BaseHTTPRequestHandler):
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
        """Responde às requisições preflight do navegador liberando o CORS."""
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(data.decode("utf-8"))

            # ROTA AHK: Reprodução local nas caixas de som
            if self.path == "/speak":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)

                try:
                    speed = float(payload.get("speed", DEFAULT_SPEED))
                except (ValueError, TypeError):
                    speed = DEFAULT_SPEED

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                # REGISTRA NO LOG SECUNDÁRIO DE TEXTOS LIDOS
                log_tts_text(text)
                logging.info("[SPEAK] Recebido novo texto para leitura local.")

                # Adiciona o trabalho à fila
                PLAYER.add_job(text, voice, speed)
                self.send_json(
                    200,
                    {"ok": True, "status": "queued", "voice": voice, "speed": speed},
                )
                return

            # ROTA AHK: Parar áudio local
            if self.path == "/stop":
                PLAYER.stop()
                logging.info("[STOP] Reprodução interrompida via solicitação.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            # ROTA SILLYTAVERN: Retorna o áudio WAV via resposta HTTP
            if self.path == "/generate":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                try:
                    speed = float(payload.get("speed", DEFAULT_SPEED))
                except (ValueError, TypeError):
                    speed = DEFAULT_SPEED

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                # REGISTRA NO LOG SECUNDÁRIO DE TEXTOS LIDOS
                log_tts_text(text)
                logging.info("[GENERATE] Recebido novo texto para geração de WAV.")

                wav_data = generate_audio_wav(text, voice, speed)
                if not wav_data:
                    self.send_json(500, {"ok": False, "error": "Falha na síntese."})
                    return

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(wav_data)
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})
        except Exception as exc:
            logging.exception("Erro HTTP.")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        if self.path == "/status":
            with PLAYER.lock:
                status = PLAYER.status
            model_loaded = PIPELINE is not None
            self.send_json(
                200,
                {
                    "ok": True,
                    "status": status,
                    "device": DEVICE,
                    "model_loaded": model_loaded,
                },
            )
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def inactivity_monitor():
    """Monitora a inatividade após a última fala e limpa o modelo se necessário."""
    while True:
        time.sleep(5)
        with MODEL_LOCK:
            if PIPELINE is None:
                continue
            elapsed = time.monotonic() - LAST_USED

        if elapsed >= IDLE_TIMEOUT:
            unload_model()


def main():
    logging.info("Servidor TTS iniciado na porta %d (%s)", PORT, DEVICE)
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    monitor_thread = threading.Thread(target=inactivity_monitor, daemon=True)
    monitor_thread.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Encerrando servidor...")
    finally:
        PLAYER.stop()
        unload_model()
        try:
            server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

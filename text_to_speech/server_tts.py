import io
import json
import logging
import multiprocessing as mp
import os
import queue
import re
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT", 8765))
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "pm_santa").strip()
DEFAULT_SPEED = float(os.getenv("DEFAULT_SPEED", "1.00").strip())
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "24000").strip())
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "600").strip())

# ==============================================================================
# CONFIGURAÇÃO DE LOGS
# ==============================================================================
log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "tts_agent.log", encoding="utf-8"),
    ],
)

tts_text_logger = logging.getLogger("tts_text_logger")
tts_text_logger.setLevel(logging.INFO)
tts_text_logger.propagate = False
tts_text_handler = logging.FileHandler(log_dir / "tts_texts.log", encoding="utf-8")
tts_text_handler.setFormatter(logging.Formatter("%(message)s"))
tts_text_logger.addHandler(tts_text_handler)


def log_tts_text(text: str):
    if text and text.strip():
        clean_entry = text.strip().replace("\r\n", " ").replace("\n", " ")
        tts_text_logger.info(clean_entry)


# ==============================================================================
# TRATAMENTO DE TEXTO (Isolado no processo leve)
# ==============================================================================
def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n|\r|\n", ". ", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"```(?:\w+)?\s*([\s\S]*?)```", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\[[ xX]\]\s*", "", text)
    text = re.sub(r"(?m)^\s*([-*_])(?:\s*\1){2,}\s*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
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


# ==============================================================================
# WORKER (ISOLADO): O PyTorch, NumPy e Kokoro só existem AQUI
# ==============================================================================
def tts_worker_process(task_queue, result_queue):
    """Processo separado responsável por carregar o Kokoro/PyTorch e gerar os áudios."""
    import numpy as np
    import torch
    from kokoro import KModel, KPipeline

    device = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu").strip()
    logging.info("[WORKER] Inicializando PyTorch e Kokoro no dispositivo: %s", device)

    model = KModel().to(device).eval()
    pipeline = KPipeline(lang_code="p", model=model)
    logging.info("[WORKER] Modelo carregado e pronto.")

    last_used = time.monotonic()

    while True:
        try:
            # Aguarda tarefas na fila com timeout curto para checar inatividade
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            if time.monotonic() - last_used >= IDLE_TIMEOUT:
                logging.info(
                    "[WORKER] Timeout de inatividade atingido (%ds). Encerrando worker...",
                    IDLE_TIMEOUT,
                )
                break
            continue

        cmd = task.get("cmd")

        if cmd == "SHUTDOWN":
            logging.info("[WORKER] Recebido comando de encerramento manual.")
            break

        if cmd == "GENERATE":
            last_used = time.monotonic()
            req_id = task["req_id"]
            text = task["text"]
            voice = task["voice"]
            speed = task["speed"]

            try:
                cleaned = clean_text(text)
                chunks = split_text(cleaned)
                audio_segments = []

                for chunk in chunks:
                    generator = pipeline(
                        chunk, voice=voice, speed=speed, split_pattern=r"\n+"
                    )
                    for _, _, audio in generator:
                        audio_data = np.asarray(audio, dtype=np.float32)
                        audio_segments.append(audio_data)

                if audio_segments:
                    full_audio = np.concatenate(audio_segments)
                    audio_pcm16 = (
                        (full_audio * 32767).clip(-32768, 32767).astype(np.int16)
                    )

                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(SAMPLE_RATE)
                        wf.writeframes(audio_pcm16.tobytes())

                    result_queue.put(
                        {"req_id": req_id, "ok": True, "wav_data": buffer.getvalue()}
                    )
                else:
                    result_queue.put(
                        {"req_id": req_id, "ok": False, "error": "Sem áudio gerado."}
                    )
            except Exception as e:
                logging.exception("[WORKER] Erro na geração de áudio.")
                result_queue.put({"req_id": req_id, "ok": False, "error": str(e)})

    # Limpeza final ao morrer
    del pipeline, model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logging.info(
        "[WORKER] Processo filho finalizado. Memória RAM e VRAM totalmente liberadas pelo SO."
    )


# ==============================================================================
# GERENCIADOR DO WORKER NO SERVIDOR PRINCIPAL
# ==============================================================================
class TTSManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.worker_process = None
        self.task_queue = None
        self.result_queue = None
        self.req_counter = 0

    def _ensure_worker_running(self):
        with self.lock:
            if self.worker_process is None or not self.worker_process.is_alive():
                logging.info("[MANAGER] Criando novo Worker Process para TTS...")

                # Garante que o processo filho use o mesmo executável Python (venv) do processo pai
                ctx = mp.get_context("spawn")
                ctx.set_executable(sys.executable)

                self.task_queue = ctx.Queue()
                self.result_queue = ctx.Queue()
                self.worker_process = ctx.Process(
                    target=tts_worker_process,
                    args=(self.task_queue, self.result_queue),
                    daemon=True,
                )
                self.worker_process.start()

    def generate_wav(self, text, voice, speed, timeout=60):
        self._ensure_worker_running()

        with self.lock:
            self.req_counter += 1
            req_id = self.req_counter

        self.task_queue.put(
            {
                "cmd": "GENERATE",
                "req_id": req_id,
                "text": text,
                "voice": voice,
                "speed": speed,
            }
        )

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                res = self.result_queue.get(timeout=0.5)
                if res.get("req_id") == req_id:
                    if res["ok"]:
                        return res["wav_data"]
                    raise Exception(res.get("error", "Erro desconhecido"))
                else:
                    # Devolve pra fila se for resposta de outra requisição concorrente
                    self.result_queue.put(res)
            except queue.Empty:
                # Checa se o worker morreu inesperadamente
                if not self.worker_process.is_alive():
                    raise Exception(
                        "O processo do modelo foi encerrado inesperadamente."
                    )

        raise TimeoutError(
            "Tempo limite excedido aguardando resposta da geração de áudio."
        )

    def stop_worker(self):
        with self.lock:
            if self.worker_process and self.worker_process.is_alive():
                self.task_queue.put({"cmd": "SHUTDOWN"})
                self.worker_process.join(timeout=3)
                if self.worker_process.is_alive():
                    self.worker_process.terminate()
                self.worker_process = None

    def is_loaded(self):
        return self.worker_process is not None and self.worker_process.is_alive()


TTS_MANAGER = TTSManager()


# ==============================================================================
# PLAYER AUDIO LOCAL PARA AHK (Roda usando sounddevice isoladamente)
# ==============================================================================
class AudioPlayer:
    def __init__(self):
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.status = "idle"
        self.worker_thread = None
        self._stop_event = threading.Event()

    def add_job(self, text, voice, speed, device=None):  # <--- Novo parâmetro
        with self.lock:
            self._stop_event.clear()
            # Adiciona 'device' ao item da fila
            self.queue.put(
                {"text": text, "voice": voice, "speed": speed, "device": device}
            )
            self.status = "playing"
            if self.worker_thread is None or not self.worker_thread.is_alive():
                self.worker_thread = threading.Thread(
                    target=self._play_loop, daemon=True
                )
                self.worker_thread.start()

    def stop(self):
        import sounddevice as sd

        with self.lock:
            self._stop_event.set()

            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break

            try:
                sd.stop()
            except Exception:
                pass

            self.status = "idle"

    def _play_loop(self):
        import sounddevice as sd

        while not self._stop_event.is_set():
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                with self.lock:
                    self.status = "idle"
                break

            # Extrai o 'device' do item
            text, voice, speed, device = (
                item["text"],
                item["voice"],
                item["speed"],
                item.get("device"),
            )

            try:
                if self._stop_event.is_set():
                    break

                wav_bytes = TTS_MANAGER.generate_wav(text, voice, speed)

                if self._stop_event.is_set() or not wav_bytes:
                    continue

                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    data = wf.readframes(wf.getnframes())
                    audio_data = (
                        int.from_bytes(data[i : i + 2], "little", signed=True) / 32768.0
                        for i in range(0, len(data), 2)
                    )
                    import numpy as np

                    arr = np.fromiter(audio_data, dtype=np.float32)

                    # Resolve o nome/alias para o dispositivo correto
                    target_device = resolve_output_device(device)

                    # Executa o áudio no dispositivo encontrado (ou no padrão se for None)
                    sd.play(arr, samplerate=wf.getframerate(), device=target_device)
                    sd.wait()

            except Exception:
                logging.exception("Erro durante a reprodução local.")
            finally:
                if self.queue.empty() or self._stop_event.is_set():
                    with self.lock:
                        self.status = "idle"


PLAYER = AudioPlayer()


# ==============================================================================
# SERVIDOR HTTP
# ==============================================================================
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
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(data.decode("utf-8"))

            if self.path == "/speak":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))
                device = payload.get("device", None)  # <--- Extrai o novo parâmetro

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                log_tts_text(text)
                logging.info("[SPEAK] Novo texto enviado para a fila local.")
                PLAYER.add_job(text, voice, speed, device=device)  # <--- Passa o device
                self.send_json(200, {"ok": True, "status": "queued"})
                return

            if self.path == "/stop":
                PLAYER.stop()
                logging.info("[STOP] Leitura interrompida.")
                self.send_json(200, {"ok": True, "status": "stopped"})
                return

            if self.path == "/generate":
                text = payload.get("text", "")
                voice = payload.get("voice", DEFAULT_VOICE)
                speed = float(payload.get("speed", DEFAULT_SPEED))

                if not isinstance(text, str) or not text.strip():
                    self.send_json(400, {"ok": False, "error": "Texto vazio."})
                    return

                log_tts_text(text)
                logging.info("[GENERATE] Gerando WAV via Worker Process...")
                wav_data = TTS_MANAGER.generate_wav(text, voice, speed)

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(wav_data)
                return

            self.send_json(404, {"ok": False, "error": "Endpoint inexistente."})
        except Exception as exc:
            logging.exception("Erro durante requisição POST HTTP.")
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        if self.path == "/status":
            with PLAYER.lock:
                status = PLAYER.status
            self.send_json(
                200,
                {
                    "ok": True,
                    "status": status,
                    "model_loaded": TTS_MANAGER.is_loaded(),
                },
            )
            return

        self.send_json(404, {"ok": False})

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)


def resolve_output_device(device_param):
    """
    Resolve o alias amigável para o nome real do dispositivo de SAÍDA.
    Se device_param for None ou "default", retorna None (usa o padrão do Windows).
    """
    if not device_param or str(device_param).strip().lower() in [
        "default",
        "padrao",
        "padrão",
    ]:
        return None

    # Mapeamento de apelidos simples para buscas no nome do dispositivo
    aliases = {
        "alexa": "echo dot",
        "echo": "echo dot",
        "fone": "h510-pro",
        "headset": "h510-pro",
        "caixa": "usb2.0 speaker",
    }

    # Normaliza a busca
    search_term = str(device_param).lower()
    search_term = aliases.get(search_term, search_term)

    import sounddevice as sd

    # Filtra apenas dispositivos que aceitam saída (max_output_channels > 0)
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev["max_output_channels"] > 0:
            if search_term in dev["name"].lower():
                return (
                    idx  # Retorna o ID numérico do primeiro dispositivo correspondente
                )

    # Se não encontrar nada, cai no dispositivo padrão
    return None


def main():
    # Define o método de spawn para compatibilidade multiplataforma (Windows/Linux)
    mp.set_start_method("spawn", force=True)

    logging.info("Servidor HTTP leve iniciado em http://%s:%d", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)

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


if __name__ == "__main__":
    main()

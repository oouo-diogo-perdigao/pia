import threading
import multiprocessing as mp
import sys
import time
import queue
import os
import re
import wave
import io
import warnings
from .config import logging, IDLE_TIMEOUT, MODEL_DIR

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

MODELS_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx"
MODELS_VOICES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin"


# ==============================================================================
# WORKER (ISOLADO): O PyTorch, NumPy e Kokoro só existem AQUI
# ==============================================================================
def tts_worker_process(task_queue, result_queue):
    import numpy as np

    kokoro = None
    qwen_model = None
    last_used = time.monotonic()

    while True:
        try:
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            if time.monotonic() - last_used >= IDLE_TIMEOUT:
                if kokoro is not None or qwen_model is not None:
                    logging.info(
                        "[WORKER] Timeout de 10 minutos atingido. Descarregando modelos da memória..."
                    )
                    if kokoro:
                        del kokoro
                        kokoro = None
                        logging.info("[WORKER] Modelo Kokoro descarregado.")
                    if qwen_model:
                        del qwen_model
                        qwen_model = None
                        logging.info("[WORKER] Modelo Qwen3-TTS descarregado.")
                break
            continue
        except (KeyboardInterrupt, EOFError):
            break

        cmd = task.get("cmd")
        if cmd == "SHUTDOWN":
            break

        if cmd == "GENERATE":
            last_used = time.monotonic()
            req_id = task["req_id"]
            text = task["text"]
            voice = task["voice"]
            speed = task["speed"]
            style = task.get("style")
            job_name = task.get("job_name", "")

            try:
                samples = None

                if style:
                    logging.info(
                        f"[WORKER] [{job_name}] Iniciando processamento com Qwen-TTS (estilo: '{style}')..."
                    )
                    if qwen_model is None:
                        import torch
                        from qwen_tts import Qwen3TTSModel

                        logging.info(
                            "[WORKER] Carregando Qwen3-TTS na memória (GPU)..."
                        )
                        qwen_model = Qwen3TTSModel.from_pretrained(
                            "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                            torch_dtype=torch.float16,
                            device_map="cuda",
                        )
                        logging.info("[WORKER] Qwen3-TTS carregado com sucesso.")

                    wavs, SAMPLE_RATE = qwen_model.generate_custom_voice(
                        text=text,
                        language="Portuguese",
                        speaker=voice if voice else "Ryan",
                        instruct=style,
                    )
                    samples = wavs[0]
                else:
                    logging.info(
                        f"[WORKER] [{job_name}] Iniciando processamento com Kokoro..."
                    )
                    if kokoro is None:
                        from kokoro_onnx import Kokoro

                        os.makedirs(MODEL_DIR, exist_ok=True)
                        onnx_path = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
                        voices_path = os.path.join(MODEL_DIR, "voices-v1.0.bin")

                        if os.path.exists(onnx_path) and os.path.exists(voices_path):
                            logging.info(
                                "[WORKER] Arquivos do modelo Kokoro já estão baixados no disco."
                            )
                        else:
                            import urllib.request

                            logging.info(
                                "[WORKER] Baixando arquivos do modelo Kokoro para o disco..."
                            )
                            if not os.path.exists(onnx_path):
                                urllib.request.urlretrieve(MODELS_KOKORO, onnx_path)
                            if not os.path.exists(voices_path):
                                urllib.request.urlretrieve(MODELS_VOICES, voices_path)
                            logging.info(
                                "[WORKER] Download dos arquivos do Kokoro concluído com sucesso."
                            )

                        logging.info(
                            "[WORKER] Carregando Kokoro via ONNX Runtime na memória..."
                        )
                        kokoro = Kokoro(onnx_path, voices_path)
                        logging.info("[WORKER] Kokoro carregado com sucesso.")

                    samples, SAMPLE_RATE = kokoro.create(
                        text, voice=voice, speed=speed, lang="pt-br"
                    )

                if len(samples) > 0:
                    logging.info(
                        f"[WORKER] [{job_name}] Processamento terminado com sucesso."
                    )
                    audio_pcm16 = (samples * 32767).clip(-32768, 32767).astype(np.int16)

                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(SAMPLE_RATE)
                        wf.writeframes(audio_pcm16.tobytes())

                    result_queue.put(
                        {
                            "req_id": req_id,
                            "ok": True,
                            "wav_data": buffer.getvalue(),
                        }
                    )
                else:
                    result_queue.put(
                        {"req_id": req_id, "ok": False, "error": "Sem áudio gerado."}
                    )
            except Exception as e:
                logging.exception(f"[WORKER] [{job_name}] Erro na geração de áudio.")
                result_queue.put({"req_id": req_id, "ok": False, "error": str(e)})

    if kokoro:
        del kokoro
    if qwen_model:
        del qwen_model
    logging.info("[WORKER] Processo filho e modelos descarregados.")


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
# GERENCIADOR DO WORKER NO SERVIDOR PRINCIPAL
# ==============================================================================
class TTSManager:
    def __init__(self, audio_player=None):
        self.lock = threading.Lock()
        self.worker_process = None
        self.task_queue = None
        self.result_queue = None
        self.req_counter = 0

        self.audio_player = audio_player
        self.tts_job_queue = queue.Queue()
        self.tts_thread = None
        self._stop_event = threading.Event()

    def add_tts_job(self, text, voice, speed, style=None, device=None, job_name=None):
        with self.lock:
            self._stop_event.clear()
            self.tts_job_queue.put(
                {
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "style": style,
                    "device": device,
                    "job_name": job_name,
                }
            )
            if self.tts_thread is None or not self.tts_thread.is_alive():
                self.tts_thread = threading.Thread(
                    target=self._tts_consumer_loop, daemon=True
                )
                self.tts_thread.start()

    def stop_tts_queue(self):
        self._stop_event.set()
        with self.lock:
            while not self.tts_job_queue.empty():
                try:
                    self.tts_job_queue.get_nowait()
                except queue.Empty:
                    break

    def _tts_consumer_loop(self):
        while not self._stop_event.is_set():
            try:
                job = self.tts_job_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._stop_event.is_set():
                break

            try:
                text = job["text"]
                voice = job["voice"]
                speed = job["speed"]
                style = job["style"]
                device = job["device"]
                job_name = job["job_name"]

                # Gera o WAV da parte atual usando o processo worker isolado
                wav_bytes = self.generate_wav(
                    text, voice, speed, style=style, job_name=job_name
                )

                if not self._stop_event.is_set() and self.audio_player and wav_bytes:
                    # Envia o áudio concluído para a fila do AudioPlayer
                    self.audio_player.add_audio_job(job_name, wav_bytes, device=device)
            except Exception:
                logging.exception("[TTSManager] Erro processando parte na fila do TTS.")

    def ensure_worker_running(self):
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

    def generate_wav(self, text, voice, speed, style=None, timeout=180, job_name=None):
        self.ensure_worker_running()

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
                "style": style,
                "job_name": job_name,
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

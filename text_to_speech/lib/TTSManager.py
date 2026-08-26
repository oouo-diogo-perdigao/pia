import threading
import multiprocessing as mp
import sys
import time
import queue
import os
import re
import wave
import io
import logging
import warnings

IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "600").strip())
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "24000").strip())

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("kokoro").setLevel(logging.ERROR)


# ==============================================================================
# WORKER (ISOLADO): O PyTorch, NumPy e Kokoro só existem AQUI
# ==============================================================================
def tts_worker_process(task_queue, result_queue):
    import numpy as np

    # Variáveis dos modelos começam vazias (não consomem memória até serem chamados)
    kokoro = None
    qwen_model = None

    last_used = time.monotonic()

    while True:
        try:
            task = task_queue.get(timeout=1.0)
        except queue.Empty:
            if time.monotonic() - last_used >= IDLE_TIMEOUT:
                logging.info(
                    "[WORKER] Timeout de inatividade atingido. Encerrando worker..."
                )
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

            try:
                cleaned = clean_text(text)
                samples = None
                sample_rate = 24000

                if style:
                    # --- CAMINHO QWEN-TTS (Carrega apenas se houver style) ---
                    logging.info(
                        f"[WORKER] Usando Qwen-TTS com instrução de estilo: '{style}'"
                    )
                    if qwen_model is None:
                        import torch
                        from qwen_tts import Qwen3TTSModel

                        logging.info(
                            "[WORKER] Carregando Qwen3-TTS (1.7B) na GPU (RTX 3080)..."
                        )
                        qwen_model = Qwen3TTSModel.from_pretrained(
                            "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                            torch_dtype=torch.float16,
                            device_map="cuda",
                        )

                    wavs, sample_rate = qwen_model.generate_custom_voice(
                        text=cleaned,
                        language="Portuguese",
                        speaker=voice if voice else "Ryan",
                        instruct=style,
                    )
                    samples = wavs[0]
                else:
                    # --- CAMINHO KOKORO (Carrega apenas se NÃO houver style) ---
                    if kokoro is None:
                        from kokoro_onnx import Kokoro

                        model_dir = os.getenv(
                            "MODEL_DIR", "./models_cache/Kokoro-82M"
                        ).strip()
                        os.makedirs(model_dir, exist_ok=True)
                        onnx_path = os.path.join(model_dir, "kokoro-v1.0.onnx")
                        voices_path = os.path.join(model_dir, "voices-v1.0.bin")

                        import urllib.request

                        if not os.path.exists(onnx_path):
                            onnx_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
                            urllib.request.urlretrieve(onnx_url, onnx_path)
                        if not os.path.exists(voices_path):
                            voices_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
                            urllib.request.urlretrieve(voices_url, voices_path)

                        logging.info(
                            "[WORKER] Inicializando Kokoro via ONNX Runtime sob demanda..."
                        )
                        kokoro = Kokoro(onnx_path, voices_path)

                    logging.info("[WORKER] Usando Kokoro (Modo Padrão)...")
                    samples, sample_rate = kokoro.create(
                        cleaned, voice=voice, speed=speed, lang="pt-br"
                    )

                if len(samples) > 0:
                    logging.info("[WORKER] Processamento terminado.")
                    audio_pcm16 = (samples * 32767).clip(-32768, 32767).astype(np.int16)

                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
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
                logging.exception("[WORKER] Erro na geração de áudio.")
                result_queue.put({"req_id": req_id, "ok": False, "error": str(e)})

    if kokoro:
        del kokoro
    if qwen_model:
        del qwen_model
    logging.info("[WORKER] Processo filho finalizado.")


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

    def generate_wav(self, text, voice, speed, style=None, timeout=180):
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
                "style": style,  # <--- Repassa o style para o worker
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

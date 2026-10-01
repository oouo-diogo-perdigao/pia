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
from .config import logging, IDLE_TIMEOUT_KOKORO, IDLE_TIMEOUT_QWEN, MODEL_DIR
import logging as py_logging

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

MODELS_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx"
MODELS_VOICES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin"


# ==============================================================================
# WORKER (ISOLADO): O PyTorch, NumPy e Kokoro só existem AQUI
# ==============================================================================
def tts_worker_process(task_queue, result_queue, backend):
    import numpy as np

    kokoro = None
    qwen_model = None
    last_used = time.monotonic()

    while True:
        try:
            task = task_queue.get(timeout=1.0)

        except queue.Empty:
            idle_time = time.monotonic() - last_used

            if backend == "qwen":
                if idle_time >= IDLE_TIMEOUT_QWEN:
                    if qwen_model is not None:
                        logging.info(
                            "[WORKER QWEN] Timeout atingido. "
                            "Descarregando Qwen3-TTS da memória..."
                        )
                        del qwen_model
                        qwen_model = None
                        logging.info("[WORKER QWEN] Modelo Qwen3-TTS descarregado.")

                    break

            else:
                if idle_time >= IDLE_TIMEOUT_KOKORO:
                    if kokoro is not None:
                        logging.info(
                            "[WORKER KOKORO] Timeout atingido. "
                            "Descarregando Kokoro da memória..."
                        )
                        del kokoro
                        kokoro = None
                        logging.info("[WORKER KOKORO] Modelo Kokoro descarregado.")

                    break

            continue

        except (KeyboardInterrupt, EOFError):
            break

        cmd = task.get("cmd")

        if cmd == "SHUTDOWN":
            break

        if cmd != "GENERATE":
            continue

        last_used = time.monotonic()

        req_id = task["req_id"]
        text = task["text"]
        voice = task["voice"]
        speed = task["speed"]
        style = task.get("style")
        job_name = task.get("job_name", "")

        try:
            samples = None

            # ==========================================================
            # QWEN
            # ==========================================================

            if backend == "qwen":
                logging.info(
                    f"[WORKER QWEN] [{job_name}] "
                    f"Iniciando processamento com Qwen-TTS "
                    f"(estilo: '{style}')..."
                )

                logging.info(f"[WORKER QWEN] [{job_name}] Texto: {text}")

                if qwen_model is None:
                    import torch
                    from qwen_tts import Qwen3TTSModel

                    py_logging.getLogger("qwen_tts").setLevel(py_logging.ERROR)

                    py_logging.getLogger("transformers").setLevel(py_logging.ERROR)

                    logging.info(
                        "[WORKER QWEN] Carregando Qwen3-TTS " "na memória (GPU)..."
                    )

                    qwen_model = Qwen3TTSModel.from_pretrained(
                        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                        dtype=torch.float16,
                        device_map="cuda",
                    )

                    logging.info("[WORKER QWEN] Qwen3-TTS carregado com sucesso.")

                wavs, SAMPLE_RATE = qwen_model.generate_custom_voice(
                    text=text,
                    language="Portuguese",
                    speaker=voice if voice else "Ryan",
                    instruct=style,
                )

                samples = wavs[0]

            # ==========================================================
            # KOKORO
            # ==========================================================

            else:
                if voice not in TTSManager.kokoro_voices():
                    voice = TTSManager.kokoro_voices()[0]

                logging.info(
                    f"[WORKER KOKORO] [{job_name}] "
                    "Iniciando processamento com Kokoro..."
                )

                if kokoro is None:
                    from kokoro_onnx import Kokoro

                    os.makedirs(MODEL_DIR, exist_ok=True)

                    onnx_path = os.path.join(
                        MODEL_DIR,
                        "kokoro-v1.0.onnx",
                    )

                    voices_path = os.path.join(
                        MODEL_DIR,
                        "voices-v1.0.bin",
                    )

                    if os.path.exists(onnx_path) and os.path.exists(voices_path):
                        logging.info(
                            "[WORKER KOKORO] Arquivos do modelo "
                            "já estão baixados no disco."
                        )

                    else:
                        import urllib.request

                        logging.info(
                            "[WORKER KOKORO] Baixando arquivos "
                            "do modelo Kokoro para o disco..."
                        )

                        if not os.path.exists(onnx_path):
                            urllib.request.urlretrieve(
                                MODELS_KOKORO,
                                onnx_path,
                            )

                        if not os.path.exists(voices_path):
                            urllib.request.urlretrieve(
                                MODELS_VOICES,
                                voices_path,
                            )

                        logging.info(
                            "[WORKER KOKORO] Download dos arquivos "
                            "do Kokoro concluído com sucesso."
                        )

                    logging.info(
                        "[WORKER KOKORO] Carregando Kokoro "
                        "via ONNX Runtime na memória..."
                    )

                    kokoro = Kokoro(
                        onnx_path,
                        voices_path,
                    )

                    logging.info("[WORKER KOKORO] Kokoro carregado com sucesso.")

                samples, SAMPLE_RATE = kokoro.create(
                    text,
                    voice=voice,
                    speed=speed,
                    lang="pt-br",
                )

            if len(samples) > 0:
                logging.info(
                    f"[WORKER {backend.upper()}] [{job_name}] "
                    "Processamento terminado com sucesso."
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
                    {
                        "req_id": req_id,
                        "ok": False,
                        "error": "Sem áudio gerado.",
                    }
                )

        except Exception as e:
            logging.exception(
                f"[WORKER {backend.upper()}] " f"[{job_name}] Erro na geração de áudio."
            )

            result_queue.put(
                {
                    "req_id": req_id,
                    "ok": False,
                    "error": str(e),
                }
            )

    if kokoro:
        del kokoro

    if qwen_model:
        del qwen_model

    logging.info(
        f"[WORKER {backend.upper()}] " "Processo filho e modelo descarregados."
    )


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

        self.generation_locks = {
            "kokoro": threading.Lock(),
            "qwen": threading.Lock(),
        }

        self.worker_processes = {
            "kokoro": None,
            "qwen": None,
        }

        self.task_queues = {
            "kokoro": None,
            "qwen": None,
        }

        self.result_queues = {
            "kokoro": None,
            "qwen": None,
        }

        self.req_counter = 0

        self.audio_player = audio_player

        # Uma fila por backend permite Kokoro e Qwen processarem
        # simultaneamente, mantendo cada modelo sequencial consigo mesmo.
        self.tts_job_queues = {
            "kokoro": queue.Queue(),
            "qwen": queue.Queue(),
        }

        self.tts_threads = {
            "kokoro": None,
            "qwen": None,
        }

        self._stop_event = threading.Event()

        # Resultados de storytelling que terminaram fora de ordem.
        self.story_results = {}
        self.story_lock = threading.Lock()

    @staticmethod
    def qwen_voices():
        return {
            "ryan": "male",
            "aiden": "male",
            "dylan": "male",
            "eric": "male",
            "ono_anna": "female",
            "serena": "female",
            "sohee": "female",
            "uncle_fu": "male",
            "vivian": "female",
        }

    @staticmethod
    def kokoro_voices():
        return {
            "pm_santa": "male",  # default voice
            "pm_alex": "male",
            "pf_dora": "female",
        }

    def get_voices(self):
        # Retorna uma lista de vozes disponíveis
        return {**self.kokoro_voices(), **self.qwen_voices()}

    def add_tts_job(
        self,
        text,
        voice,
        speed,
        style=None,
        device=None,
        job_name=None,
        story_id=None,
        story_index=None,
        story_total=None,
    ):
        backend = "qwen" if voice in self.qwen_voices() else "kokoro"

        with self.lock:
            self._stop_event.clear()

            self.tts_job_queues[backend].put(
                {
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "style": style,
                    "device": device,
                    "job_name": job_name,
                    "story_id": story_id,
                    "story_index": story_index,
                    "story_total": story_total,
                }
            )

            thread = self.tts_threads[backend]

            if thread is None or not thread.is_alive():
                thread = threading.Thread(
                    target=self._tts_consumer_loop,
                    args=(backend,),
                    daemon=True,
                )

                self.tts_threads[backend] = thread
                thread.start()

    def stop_tts_queue(self):
        self._stop_event.set()

        for job_queue in self.tts_job_queues.values():
            while True:
                try:
                    job_queue.get_nowait()
                    job_queue.task_done()

                except queue.Empty:
                    break

    def _tts_consumer_loop(self, backend):
        job_queue = self.tts_job_queues[backend]

        while not self._stop_event.is_set():
            try:
                job = job_queue.get(timeout=0.1)

            except queue.Empty:
                continue

            if self._stop_event.is_set():
                job_queue.task_done()
                break

            try:
                text = job["text"]
                voice = job["voice"]
                speed = job["speed"]
                style = job["style"]
                device = job["device"]
                job_name = job["job_name"]

                story_id = job.get("story_id")
                story_index = job.get("story_index")
                story_total = job.get("story_total")

                wav_bytes = self.generate_wav(
                    text,
                    voice,
                    speed,
                    style=style,
                    job_name=job_name,
                )

                if self._stop_event.is_set() or not wav_bytes or not self.audio_player:
                    continue

                # ----------------------------------------------------------
                # STORYTELLING
                # ----------------------------------------------------------
                #
                # Kokoro e Qwen podem terminar fora de ordem.
                # Nesse caso guardamos o resultado e liberamos para o player
                # apenas quando todos os trechos anteriores estiverem prontos.
                # ----------------------------------------------------------

                if (
                    story_id is not None
                    and story_index is not None
                    and story_total is not None
                ):
                    self._add_story_result(
                        story_id=story_id,
                        story_index=story_index,
                        story_total=story_total,
                        job_name=job_name,
                        wav_bytes=wav_bytes,
                        device=device,
                    )

                # ----------------------------------------------------------
                # TTS NORMAL
                # ----------------------------------------------------------

                else:
                    self.audio_player.add_audio_job(
                        job_name,
                        wav_bytes,
                        device=device,
                    )

                    logging.info(
                        "[TTSManager] [%s] " "Áudio enviado para fila de reprodução.",
                        job_name,
                    )

            except Exception:
                logging.exception(
                    "[TTSManager] Erro processando parte " "na fila %s.",
                    backend,
                )

            finally:
                job_queue.task_done()

    def _add_story_result(
        self,
        story_id,
        story_index,
        story_total,
        job_name,
        wav_bytes,
        device,
    ):
        with self.story_lock:
            story = self.story_results.setdefault(
                story_id,
                {
                    "next_index": 1,
                    "total": story_total,
                    "results": {},
                },
            )

            story["results"][story_index] = {
                "job_name": job_name,
                "wav_bytes": wav_bytes,
                "device": device,
            }

            logging.info(
                "[STORYTELLING] Parte %d de %d pronta.",
                story_index,
                story_total,
            )

            self._flush_story_results(story_id, story)

    def _flush_story_results(self, story_id, story):
        while story["next_index"] in story["results"]:
            index = story["next_index"]
            result = story["results"].pop(index)

            self.audio_player.add_audio_job(
                result["job_name"],
                result["wav_bytes"],
                device=result["device"],
            )

            logging.info(
                "[STORYTELLING] Parte %d de %d enviada " "para fila de reprodução.",
                index,
                story["total"],
            )

            story["next_index"] += 1

        # Todas as partes já foram despachadas.
        # Remove o estado para não acumular lixo na memória.
        if story["next_index"] > story["total"]:
            self.story_results.pop(
                story_id,
                None,
            )

            logging.info(
                "[STORYTELLING] Todas as %d partes foram " "enviadas para reprodução.",
                story["total"],
            )

    def ensure_worker_running(self, backend=None):
        # Quando chamado sem backend, mantém o comportamento esperado
        # pelas chamadas antigas, garantindo os dois workers.
        if backend is None:
            self.ensure_worker_running("kokoro")
            self.ensure_worker_running("qwen")
            return

        if backend not in ("kokoro", "qwen"):
            raise ValueError(f"Backend TTS inválido: {backend}")

        with self.lock:
            process = self.worker_processes[backend]

            if process is None or not process.is_alive():
                logging.info(
                    "[MANAGER] Criando novo Worker Process para %s...",
                    backend.upper(),
                )

                ctx = mp.get_context("spawn")
                ctx.set_executable(sys.executable)

                task_queue = ctx.Queue()
                result_queue = ctx.Queue()

                process = ctx.Process(
                    target=tts_worker_process,
                    args=(
                        task_queue,
                        result_queue,
                        backend,
                    ),
                    daemon=True,
                )

                process.start()

                self.task_queues[backend] = task_queue
                self.result_queues[backend] = result_queue
                self.worker_processes[backend] = process

    def generate_wav(
        self,
        text,
        voice,
        speed,
        style=None,
        timeout=180,
        job_name=None,
    ):
        backend = "qwen" if voice in self.qwen_voices() else "kokoro"

        with self.generation_locks[backend]:
            self.ensure_worker_running(backend)

            with self.lock:
                self.req_counter += 1
                req_id = self.req_counter

                task_queue = self.task_queues[backend]
                result_queue = self.result_queues[backend]
                worker_process = self.worker_processes[backend]

            task_queue.put(
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
                    res = result_queue.get(timeout=0.5)

                    if res.get("req_id") != req_id:
                        logging.warning(
                            "[MANAGER %s] Resultado inesperado "
                            "req_id=%s; aguardado=%s.",
                            backend.upper(),
                            res.get("req_id"),
                            req_id,
                        )
                        continue

                    if res["ok"]:
                        return res["wav_data"]

                    raise Exception(
                        res.get(
                            "error",
                            "Erro desconhecido",
                        )
                    )

                except queue.Empty:
                    if not worker_process.is_alive():
                        raise Exception(
                            f"O processo do modelo {backend} "
                            "foi encerrado inesperadamente."
                        )

            raise TimeoutError(
                f"Tempo limite excedido aguardando resposta "
                f"da geração de áudio {backend}."
            )

    def stop_worker(self):
        with self.lock:
            for backend in ("kokoro", "qwen"):
                process = self.worker_processes[backend]
                task_queue = self.task_queues[backend]

                if process and process.is_alive():
                    task_queue.put({"cmd": "SHUTDOWN"})

                    process.join(timeout=3)

                    if process.is_alive():
                        process.terminate()

                self.worker_processes[backend] = None
                self.task_queues[backend] = None
                self.result_queues[backend] = None

    def is_loaded(self):
        return any(
            process is not None and process.is_alive()
            for process in self.worker_processes.values()
        )

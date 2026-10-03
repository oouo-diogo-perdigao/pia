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
import shutil
import subprocess
import json

import logging as py_logging

from .config import (
    logging,
    IDLE_TIMEOUT_KOKORO,
    IDLE_TIMEOUT_QWEN,
    KOKORO_MODEL,
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    BASE_DIR,
    LLM_URL,
    LLM_MODEL,
)

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

                import torch
                from qwen_tts import Qwen3TTSModel

                logging.info(f"[WORKER QWEN] [{job_name}] Texto: {text}")

                if qwen_model is None:

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

                    os.makedirs(KOKORO_MODEL, exist_ok=True)

                    onnx_path = os.path.join(
                        KOKORO_MODEL,
                        "kokoro-v1.0.onnx",
                    )

                    voices_path = os.path.join(
                        KOKORO_MODEL,
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
    CACHE_FILE = BASE_DIR / "logs" / "selectedVoices.json"

    # Acima deste número, consideramos que a voz já está
    # razoavelmente consolidada naquele personagem.
    CONSOLIDATED_SPEECH_COUNT = 10

    def __init__(self):
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

        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.status = "idle"
        self.worker_thread = None
        self._stop_event = threading.Event()

        voices = self.qwen_voices()
        self.voice_genders = {
            str(voice).strip().lower(): str(gender).strip().lower()
            for voice, gender in voices.items()
            if str(voice).strip()
        }

        # Lista das vozes que REALMENTE existem no Qwen.
        self.available_voices = [
            str(voice).strip().lower() for voice in voices if str(voice).strip()
        ]

        self.llm_url = LLM_URL.rstrip("/")
        self.llm_model = LLM_MODEL
        self.lock = threading.RLock()

        # personagem normalizado -> dados persistentes
        self.characters: dict[str, dict] = {}

        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

        self.text_buffer = ""
        self.text_buffer_lock = threading.RLock()

    def models(self):
        return (
            # tts
            "tts-1",
            "tts-1-hd",
            "gpt-4o-mini-tts",
            "gpt-4o-mini-tts-2025-12-15",
        )

    def formats(self):
        return {
            "mp3": "audio/mpeg",
            "opus": "audio/ogg",
            "aac": "audio/aac",
            "flac": "audio/flac",
            "wav": "audio/wav",
            "pcm": "audio/pcm",
        }

    @staticmethod
    def qwen_voices():
        return {
            "ryan": {"name": "Ryan", "gender": "male"},
            "aiden": {"name": "Aiden", "gender": "male"},
            "dylan": {"name": "Dylan", "gender": "male"},
            "eric": {"name": "Eric", "gender": "male"},
            "ono_anna": {"name": "Ono Anna", "gender": "female"},
            "serena": {"name": "Serena", "gender": "female"},
            "sohee": {"name": "Sohee", "gender": "female"},
            "uncle_fu": {"name": "Uncle Fu", "gender": "male"},
            "vivian": {"name": "Vivian", "gender": "female"},
        }

    @staticmethod
    def kokoro_voices():
        return {
            "pm_santa": {"name": "Santa", "gender": "male"},
            "pm_alex": {"name": "Alex", "gender": "male"},
            "pf_dora": {"name": "Dora", "gender": "female"},
        }

    def get_voices(self):
        voices = {
            **self.kokoro_voices(),
            **self.qwen_voices(),
        }

        return {
            "object": "list",
            "data": [
                {
                    "id": voice_id,
                    "name": voice["name"],
                    "gender": voice["gender"],
                }
                for voice_id, voice in voices.items()
            ],
        }

    def resolve_voice(self, voice, style):
        """Converte vozes padrão OpenAI em aliases do backend local."""
        if isinstance(voice, dict):
            voice = voice.get("id")

        if not isinstance(voice, str) or not voice.strip():
            return None if style else DEFAULT_VOICE

        voice = voice.strip()
        if voice.lower() in self.get_voices():
            # Qwen CustomVoice já possui fallback interno para Ryan quando voice=None.
            return None if style else DEFAULT_VOICE

        return voice

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

    def add_tts_job_storytelling(self, text: str):
        """Extrai partes de narração e interlocutores e enfileira no TTS"""
        # Procura pelo padrão: [-Nome] "Fala", [*Nome] "Fala", [Nome] "Fala" ou apenas "Fala"
        token_re = re.compile(
            r'\[([-*])?([^\[\]\r\n]+)\]\s*"([^"]+)"'  # [-Interlocutor] ou [*Interlocutor] "fala"
            r"|"
            r'"([^"]+)"',  # "fala sem nome"
            re.MULTILINE,
        )

        cursor = 0
        for match in token_re.finditer(text):
            # Texto de narração (antes das aspas)
            between = text[cursor : match.start()].strip()
            if between:
                self.add_tts_job(
                    text=between,
                    voice="pm_santa",
                    speed=DEFAULT_SPEED,
                    job_name="Narrador (pm_santa)",
                )

            character = match.group(2)

            # Se a tag de Personagem foi encontrada
            if character:
                character = character.strip()  # Remove possíveis espaços extras no nome
                gender_prefix = match.group(1)
                speech = match.group(3).strip()

                # Define a voz baseado no prefixo * (Feminino) ou - (Masculino)
                if gender_prefix == "*":
                    voice = "pf_dora"
                else:
                    voice = (
                        "pm_alex"  # Padrão masculino para '-' ou quando vem sem prefixo
                    )

                if speech:
                    self.add_tts_job(
                        text=speech,
                        voice=voice,
                        speed=DEFAULT_SPEED,
                        job_name=f"[{character}] ({voice})",
                    )
            else:
                # Fala sem personagem definido na tag
                speech = match.group(4).strip()
                if speech:
                    self.add_tts_job(
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
                self.add_tts_job(
                    text=narration,
                    voice="pm_santa",
                    speed=DEFAULT_SPEED,
                    job_name="Narrador (pm_santa)",
                )

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

                wav_bytes = self.generate(
                    text,
                    voice,
                    speed,
                    style=style,
                    job_name=job_name,
                )

                if self._stop_event.is_set() or not wav_bytes:
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
                    self.add_audio_job(
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

            self.add_audio_job(
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

    def _convert_format(self, wav_data: bytes, response_format: str) -> bytes:
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

    def generate(
        self,
        text,
        voice,
        speed,
        style=None,
        timeout=180,
        job_name=None,
        output_format="wav",
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
                        if output_format != "wav":
                            return self._convert_format(res["wav_data"], output_format)
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

    def add_audio_job(self, jobName, wav_bytes, device=None):
        with self.lock:
            self._stop_event.clear()
            self.queue.put(
                {
                    "jobName": jobName,
                    "wav_bytes": wav_bytes,
                    "device": device,
                }
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
        import numpy as np

        try:
            while not self._stop_event.is_set():
                try:
                    item = self.queue.get(timeout=0.1)
                except queue.Empty:
                    if self._stop_event.is_set():
                        break
                    continue
                if not item:
                    continue

                wav_bytes = item["wav_bytes"]
                device = item["device"]
                job_name = item["jobName"]

                if self._stop_event.is_set() or not wav_bytes:
                    continue

                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    data = wf.readframes(wf.getnframes())
                    audio_data = (
                        int.from_bytes(data[i : i + 2], "little", signed=True) / 32768.0
                        for i in range(0, len(data), 2)
                    )
                    arr = np.fromiter(audio_data, dtype=np.float32)
                    target_device = self._resolve_output_device(device)

                    logging.info(
                        f"[PLAYER] [{job_name}] Iniciando reprodução do áudio..."
                    )
                    sd.play(arr, samplerate=wf.getframerate(), device=target_device)

                    while sd.get_stream().active and not self._stop_event.is_set():
                        threading.Event().wait(0.05)

                    logging.info(f"[PLAYER] [{job_name}] Reprodução concluída.")

                with self.lock:
                    if self.queue.empty():
                        self.status = "idle"
        except Exception:
            logging.exception("Erro durante a reprodução local.")
        finally:
            with self.lock:
                if self.queue.empty():
                    self.status = "idle"

    def _resolve_output_device(self, device_param):
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
                    return idx  # Retorna o ID numérico do primeiro dispositivo correspondente

        # Se não encontrar nada, cai no dispositivo padrão
        return None

    # ==============================================================
    # PARSER
    # ==============================================================
    def parse_storytelling_text(self, text: str) -> list[dict]:
        """
        Divide uma história em segmentos TTS.

        Regras:
        narração                   -> pm_santa
        "fala sem personagem"      -> pm_alex
        [Personagem] "fala"        -> voz Qwen

        Falas consecutivas do MESMO personagem, sem narração real
        entre elas, são fundidas em um único segmento.
        """

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

        token_re = re.compile(
            # [Personagem] "fala" {speech manner opcional}
            r'\[([^\[\]\r\n]+)\]\s*"([^"]+)"(?:\s*\{([^{}\r\n]+)\})?' r"|"
            # "fala anônima" {speech manner opcional}
            r'"([^"]+)"(?:\s*\{([^{}\r\n]+)\})?',
            re.MULTILINE,
        )

        raw_segments = []
        cursor = 0

        for match in token_re.finditer(text):

            between = text[cursor : match.start()]

            # ----------------------------------------------------------
            # Existe texto entre o último token e este.
            # ----------------------------------------------------------

            if between:
                narration = between.strip()

                # Markdown ** isolado ao redor do bloco inicial não deve
                # virar narração.
                narration = re.sub(r"^\*{1,2}\s*", "", narration)
                narration = re.sub(r"\s*\*{1,2}$", "", narration)
                narration = narration.strip()

                if narration:
                    raw_segments.append(
                        {
                            "type": "narration",
                            "text": narration,
                            "character": None,
                        }
                    )

            character = match.group(1)

            # ----------------------------------------------------------
            # [Personagem] "fala"
            # ----------------------------------------------------------
            if character is not None:
                speech = match.group(2).strip()
                speech_manner = match.group(3).strip() if match.group(3) else None

                character = self._normalize_character(character)

                if speech:
                    raw_segments.append(
                        {
                            "type": "character",
                            "text": speech,
                            "character": character,
                            "style": speech_manner,
                        }
                    )

            # ----------------------------------------------------------
            # "fala sem personagem"
            # ----------------------------------------------------------
            else:
                speech = match.group(4).strip()
                speech_manner = match.group(5).strip() if match.group(5) else None

                if speech:
                    raw_segments.append(
                        {
                            "type": "anonymous",
                            "text": speech,
                            "character": None,
                            "style": speech_manner,
                        }
                    )

            cursor = match.end()

        # --------------------------------------------------------------
        # Narração final
        # --------------------------------------------------------------

        if cursor < len(text):
            narration = text[cursor:].strip()

            narration = re.sub(r"^\*{1,2}\s*", "", narration)
            narration = re.sub(r"\s*\*{1,2}$", "", narration)
            narration = narration.strip()

            if narration:
                raw_segments.append(
                    {
                        "type": "narration",
                        "text": narration,
                        "character": None,
                    }
                )

        # ==============================================================
        # FUNDE FALAS CONSECUTIVAS DO MESMO PERSONAGEM
        # ==============================================================

        merged_segments = []

        for segment in raw_segments:
            if (
                merged_segments
                and segment["type"] == "character"
                and merged_segments[-1]["type"] == "character"
                and (
                    self._character_key(segment["character"])
                    == self._character_key(merged_segments[-1]["character"])
                )
                and segment.get("style") == merged_segments[-1].get("style")
            ):
                merged_segments[-1]["text"] = (
                    merged_segments[-1]["text"].rstrip()
                    + " "
                    + segment["text"].lstrip()
                )

                continue

            merged_segments.append(segment)

        # ==============================================================
        # RESOLVE AS VOZES SOMENTE DEPOIS DA FUSÃO
        # ==============================================================

        segments = []

        for segment in merged_segments:

            if segment["type"] == "narration":
                segments.append(
                    {
                        "text": segment["text"],
                        "voice": "pm_santa",
                        "character": None,
                        "style": None,
                    }
                )

            elif segment["type"] == "anonymous":
                segments.append(
                    {
                        "text": segment["text"],
                        "voice": "pm_alex",
                        "character": None,
                        "style": None,
                    }
                )

            else:
                character = segment["character"]
                speech = segment["text"]

                voice = self.get_voice(
                    character,
                    speech=speech,
                )

                segments.append(
                    {
                        "text": speech,
                        "voice": voice,
                        "character": character,
                        "style": segment.get("style"),
                    }
                )

        return segments

    # ==============================================================
    # NORMALIZAÇÃO
    # ==============================================================
    @staticmethod
    def _normalize_character(name: str) -> str:
        return re.sub(r"\s+", " ", name.strip())

    @classmethod
    def _character_key(cls, name: str) -> str:
        return cls._normalize_character(name).casefold()

    # ==============================================================
    # CACHE
    # ==============================================================
    def _load_cache(self):
        with self.lock:
            self.characters.clear()

            if not self.CACHE_FILE.exists():
                logging.info(
                    "[STORY VOICE] Cache ainda não existe: %s",
                    self.CACHE_FILE,
                )
                return

            try:
                with self.CACHE_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    raise ValueError("selectedVoices.json deve conter um objeto JSON.")

                for raw_key, raw_entry in data.items():
                    if not isinstance(raw_entry, dict):
                        continue

                    name = self._normalize_character(
                        str(raw_entry.get("name") or raw_key)
                    )

                    voice = str(raw_entry.get("voice") or "").strip().lower()

                    try:
                        speech_count = max(
                            0,
                            int(raw_entry.get("speech_count", 0)),
                        )
                    except (TypeError, ValueError):
                        speech_count = 0

                    # Não aceitamos no cache uma voz que já não exista
                    # no Qwen configurado atualmente.
                    if not name or voice not in self.available_voices:
                        logging.warning(
                            "[STORY VOICE] Entrada inválida ignorada: %s -> %s",
                            name,
                            voice,
                        )
                        continue

                    key = self._character_key(name)

                    self.characters[key] = {
                        "name": name,
                        "voice": voice,
                        "speech_count": speech_count,
                    }

                logging.info(
                    "[STORY VOICE] %d personagem(ns) carregado(s) do cache.",
                    len(self.characters),
                )

            except Exception:
                logging.exception("[STORY VOICE] Erro lendo cache de vozes.")

    def _save_cache(self):
        """
        Salva atomicamente o JSON.

        Primeiro escreve em .tmp e depois substitui o arquivo real.
        Assim uma interrupção durante a escrita tem menos chance de
        transformar o cache numa oferenda aos deuses da corrupção de dados.
        """

        temp_file = self.CACHE_FILE.with_suffix(".tmp")

        ordered_data = dict(
            sorted(
                self.characters.items(),
                key=lambda item: item[1]["name"].casefold(),
            )
        )

        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(
                ordered_data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        temp_file.replace(self.CACHE_FILE)

    # ==============================================================
    # VOZ
    # ==============================================================
    def get_voice(
        self,
        character: str,
        *,
        speech: str | None = None,
    ) -> str:
        """
        Retorna a voz do personagem.

        Se já existe:
            - reutiliza a voz;
            - incrementa speech_count.

        Se não existe:
            - pede ao LLM uma voz considerando personagens existentes;
            - cria o registro;
            - speech_count começa em 1.
        """

        character = self._normalize_character(character)

        if not character:
            return "ryan"

        key = self._character_key(character)

        # ----------------------------------------------------------
        # Personagem existente
        # ----------------------------------------------------------

        with self.lock:
            cached = self.characters.get(key)

            if cached:
                cached["speech_count"] += 1
                self._save_cache()

                logging.info(
                    "[STORY VOICE] Cache: %s -> %s | falas=%d",
                    cached["name"],
                    cached["voice"],
                    cached["speech_count"],
                )

                return cached["voice"]

        # ----------------------------------------------------------
        # Personagem novo
        # ----------------------------------------------------------

        voice, gender = self._classify_voice(
            character,
            speech=speech,
        )

        with self.lock:
            # Verificação dupla.
            #
            # Outra thread pode ter registrado o personagem enquanto
            # estávamos esperando o LLM responder.
            existing = self.characters.get(key)

            if existing:
                existing["speech_count"] += 1
                self._save_cache()
                return existing["voice"]

            self.characters[key] = {
                "name": character,
                "gender": gender,
                "voice": voice,
                "speech_count": 1,
            }

            self._save_cache()

        logging.info(
            "[STORY VOICE] Nova classificação: %s -> %s | falas=1",
            character,
            voice,
        )

        return voice

    # ==============================================================
    # INFORMAÇÕES PARA CLASSIFICAÇÃO
    # ==============================================================
    def _build_voice_usage_summary(self) -> str:
        """
        Produz para o LLM algo como:

        ryan:
          - Asta: 84 falas [CONSOLIDADO]

        serena:
          - Raegis: 4 falas

        vivian:
          - não utilizada
        """

        with self.lock:
            snapshot = {key: value.copy() for key, value in self.characters.items()}

        voice_usage = {voice: [] for voice in self.available_voices}

        for data in snapshot.values():
            voice = data["voice"]

            if voice not in voice_usage:
                continue

            voice_usage[voice].append(data)

        lines = []

        for voice in self.available_voices:
            entries = voice_usage[voice]

            if not entries:
                gender = self.voice_genders.get(voice, "unknown")
                lines.append(f"- {voice} [{gender}]: NÃO UTILIZADA")
                continue

            # Mais consolidados primeiro.
            entries = sorted(
                entries,
                key=lambda item: item["speech_count"],
                reverse=True,
            )

            descriptions = []

            for entry in entries:
                count = entry["speech_count"]

                consolidated = (
                    " [CONSOLIDADO]" if count >= self.CONSOLIDATED_SPEECH_COUNT else ""
                )

                descriptions.append(f'{entry["name"]}: {count} fala(s){consolidated}')

            gender = self.voice_genders.get(voice, "unknown")

            lines.append(f"- {voice} [{gender}]: " + "; ".join(descriptions))

        return "\n".join(lines)

    # ==============================================================
    # CLASSIFICAÇÃO LLM
    # ==============================================================
    def _classify_voice(
        self,
        character: str,
        *,
        speech: str | None = None,
    ) -> tuple[str, str]:

        usage_summary = self._build_voice_usage_summary()

        speech_context = (
            speech.strip()
            if isinstance(speech, str) and speech.strip()
            else "(nenhuma fala disponível)"
        )

        voice_catalog = "\n".join(
            f"- {voice}: {self.voice_genders.get(voice, 'unknown')}"
            for voice in self.available_voices
        )

        prompt = f"""
    Você atribui vozes TTS a personagens.

    Determine:
    1. o gênero mais provável do personagem;
    2. a voz mais apropriada e compatível.

    VOZES:
    {voice_catalog}

    PERSONAGEM:
    {character}

    FALA:
    {speech_context}

    USO ATUAL DAS VOZES:
    {usage_summary}

    REGRAS:

    - Gênero deve ser: male, female ou unknown.
    - Use principalmente o nome e contexto para inferir gênero.
    - female deve usar SOMENTE voz female.
    - male deve usar SOMENTE voz male.
    - unknown pode usar qualquer voz.
    - Compatibilidade de gênero tem prioridade sobre uso.
    - Entre vozes compatíveis, prefira as menos utilizadas.
    - Evite vozes de personagens [CONSOLIDADO].
    - Não invente vozes.

    Responda SOMENTE:
    gender|voice

    Exemplo:
    female|serena
    """.strip()

        request_payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classifique gênero e voz para personagens de TTS. "
                        "Responda somente no formato gender|voice."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0,
            "max_tokens": 20,
        }

        if self.llm_model:
            request_payload["model"] = self.llm_model

        data = json.dumps(
            request_payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.llm_url + "/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))

            content = str(result["choices"][0]["message"]["content"]).strip().lower()

            # ESSENCIAL PARA DIAGNÓSTICO
            logging.info(
                "[STORY VOICE] Resposta bruta do LLM para %s: %r",
                character,
                content,
            )

            # ----------------------------------------------------------
            # Procura male|voice, female|voice ou unknown|voice
            # mesmo que o modelo tenha acrescentado porcaria em volta.
            # ----------------------------------------------------------

            match = re.search(
                r"\b(male|female|unknown)\s*\|\s*" r"([a-zA-Z0-9_-]+)\b",
                content,
            )

            if not match:
                raise ValueError(
                    f"Resposta do LLM fora do formato esperado: {content!r}"
                )

            gender = match.group(1).lower()
            voice = match.group(2).lower()

            # ----------------------------------------------------------
            # Voz existe?
            # ----------------------------------------------------------

            if voice not in self.available_voices:
                logging.warning(
                    "[STORY VOICE] Voz inexistente retornada para %s: %s",
                    character,
                    voice,
                )

                return (
                    self._fallback_voice(gender=gender),
                    gender,
                )

            # ----------------------------------------------------------
            # Gênero da voz
            # ----------------------------------------------------------

            voice_gender = self.voice_genders.get(
                voice,
                "unknown",
            )

            # ----------------------------------------------------------
            # Impede combinação incompatível
            # ----------------------------------------------------------

            if gender in {"male", "female"} and voice_gender != gender:
                logging.warning(
                    "[STORY VOICE] Voz incompatível para %s: "
                    "personagem=%s, voz=%s (%s). "
                    "Aplicando fallback por gênero.",
                    character,
                    gender,
                    voice,
                    voice_gender,
                )

                voice = self._fallback_voice(gender=gender)

            logging.info(
                "[STORY VOICE] Classificação final: " "%s -> gênero=%s | voz=%s",
                character,
                gender,
                voice,
            )

            return voice, gender

        except Exception:
            logging.exception(
                "[STORY VOICE] Falha classificando personagem %s.",
                character,
            )

            # Aqui não conhecemos o gênero com segurança.
            return self._fallback_voice(), "unknown"

    # ==============================================================
    # FALLBACK
    # ==============================================================
    def _fallback_voice(
        self,
        gender: str | None = None,
    ) -> str:

        with self.lock:
            usage_count = {voice: 0 for voice in self.available_voices}

            for data in self.characters.values():
                voice = data["voice"]

                if voice in usage_count:
                    usage_count[voice] += data["speech_count"]

        if gender in {"male", "female"}:
            candidates = [
                voice
                for voice in self.available_voices
                if self.voice_genders.get(voice) == gender
            ]
        else:
            candidates = list(self.available_voices)

        if not candidates:
            candidates = list(self.available_voices)

        if not candidates:
            return "ryan"

        selected = min(
            candidates,
            key=lambda voice: usage_count.get(voice, 0),
        )

        logging.warning(
            "[STORY VOICE] Fallback de menor utilização: " "%s | gênero=%s | peso=%d",
            selected,
            gender or "unknown",
            usage_count.get(selected, 0),
        )

        return selected

    def shutdown(self) -> None:
        logging.info("[APP] Shutdown requested. Stopping recording and TTS worker.")
        try:
            self.stop()
        finally:
            self.stop_worker()

import multiprocessing as mp
import queue
import threading
import time
import uuid
from pathlib import Path

from .config import UNLOAD_TIMEOUT_SECONDS, logging


# ==============================================================================
# GERENCIADOR DO WORKER NO PROCESSO PRINCIPAL
# ==============================================================================
class STTWorkerManager:
    def __init__(self, models_dir=None):
        """Manage a separate process that runs the heavy STT model.

        Args:
            models_dir: Path to the models directory (optional).
        """
        self.lock = threading.Lock()
        self.api_lock = threading.Lock()
        self.worker_process = None
        self.audio_chunk_queue = None
        self.text_result_queue = None
        self.api_result_queue = None
        self.models_dir = models_dir

    def ensure_worker_running(self):
        with self.lock:
            if self.worker_process is None or not self.worker_process.is_alive():
                logging.info("[MANAGER STT] Subindo novo worker isolado para STT...")
                self.audio_chunk_queue = mp.Queue()
                self.text_result_queue = mp.Queue()
                self.api_result_queue = mp.Queue()
                models_dir = self.models_dir
                self.worker_process = mp.Process(
                    target=stt_worker_process,
                    args=(
                        self.audio_chunk_queue,
                        self.text_result_queue,
                        self.api_result_queue,
                        models_dir,
                    ),
                    daemon=True,
                )
                self.worker_process.start()

    def send_chunk(self, chunk):
        """Queue a recorder chunk and preserve the existing async interface."""
        self.ensure_worker_running()
        self.audio_chunk_queue.put(
            {
                "kind": "stream",
                "audio": chunk,
                # Preserve the old recorder behavior: Portuguese is explicit.
                "language": "pt",
            }
        )

    def get_result(self, timeout=0.1):
        if self.text_result_queue is None:
            return None
        try:
            return self.text_result_queue.get(timeout=timeout)
        except Exception:
            # mp.Queue may raise different exceptions depending on platform;
            # treat any exception as no result within timeout.
            return None

    def transcribe_request(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        timeout: float = 180.0,
    ) -> dict:
        """Synchronously transcribe one OpenAI-compatible API request.

        API requests are serialized because the underlying Whisper worker processes
        one item at a time anyway. Recorder results use a separate result queue, so
        microphone transcription and Open WebUI cannot accidentally consume each
        other's responses.
        """
        if not audio_bytes:
            return {"ok": False, "error": "Arquivo de áudio vazio."}

        request_id = uuid.uuid4().hex

        with self.api_lock:
            self.ensure_worker_running()
            request_queue = self.audio_chunk_queue
            result_queue = self.api_result_queue

            request_queue.put(
                {
                    "kind": "api",
                    "request_id": request_id,
                    "audio": audio_bytes,
                    "language": language or None,
                    "prompt": prompt or None,
                    "temperature": temperature,
                }
            )

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {
                        "ok": False,
                        "error": "Tempo limite excedido durante a transcrição.",
                    }

                try:
                    result = result_queue.get(timeout=remaining)
                except queue.Empty:
                    return {
                        "ok": False,
                        "error": "Tempo limite excedido durante a transcrição.",
                    }
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}

                if result.get("request_id") == request_id:
                    return result

                # A previous timed-out request may finish later. Discard that stale
                # response rather than handing it to the next HTTP caller.
                logging.warning(
                    "[MANAGER STT] Descartando resposta API antiga (%s).",
                    result.get("request_id"),
                )

    def stop_worker(self):
        with self.lock:
            if self.worker_process and self.worker_process.is_alive():
                self.audio_chunk_queue.put("SHUTDOWN")
                self.worker_process.join(timeout=3)
                if self.worker_process.is_alive():
                    self.worker_process.terminate()
                    self.worker_process.join(timeout=1)

            self.worker_process = None
            self.audio_chunk_queue = None
            self.text_result_queue = None
            self.api_result_queue = None


# ==============================================================================
# WORKER PROCESS (ISOLADO): O VoiceAgent / PyTorch rodam EXCLUSIVAMENTE aqui
# ==============================================================================
def stt_worker_process(
    audio_chunk_queue: mp.Queue,
    text_result_queue: mp.Queue,
    api_result_queue: mp.Queue,
    models_dir: Path,
):
    """Processo isolado para transcrição. O encerramento deste processo devolve 100% da RAM/VRAM, e encaminha os resultados por chamador."""
    # Importações pesadas acontecem APENAS dentro do processo filho.
    from src.VoiceAgent import VoiceAgent

    logging.info("[WORKER STT] Inicializando modelo de IA no processo filho...")
    agent = VoiceAgent(models_dir)
    logging.info("[WORKER STT] Modelo pronto para transcrição.")

    last_used = time.monotonic()

    while True:
        try:
            # Aguarda novo chunk de áudio para transcrição
            item = audio_chunk_queue.get(timeout=1.0)
        except (queue.Empty, KeyboardInterrupt):
            if time.monotonic() - last_used >= UNLOAD_TIMEOUT_SECONDS:
                logging.info(
                    "[WORKER STT] Inatividade de %ds atingida. Finalizando processo e liberando memória...",
                    UNLOAD_TIMEOUT_SECONDS,
                )
                break
            continue

        if item == "SHUTDOWN":
            logging.info("[WORKER STT] Comando de shutdown recebido.")
            break

        # Backward compatibility if an older caller still pushes raw bytes.
        if isinstance(item, (bytes, bytearray)):
            task = {
                "kind": "stream",
                "audio": bytes(item),
                "language": "pt",
            }
        else:
            task = item

        kind = task.get("kind", "stream")
        request_id = task.get("request_id")
        chunk = task.get("audio", b"")
        language = task.get("language")
        prompt = task.get("prompt")
        temperature = task.get("temperature")
        target_queue = api_result_queue if kind == "api" else text_result_queue

        last_used = time.monotonic()

        try:
            text = agent.transcribe_chunk(
                chunk,
                language=language,
                prompt=prompt,
                temperature=temperature,
            )
            target_queue.put(
                {
                    "ok": True,
                    "text": text or None,
                    "request_id": request_id,
                }
            )
        except Exception as exc:
            logging.exception("[WORKER STT] Erro durante transcrição.")
            target_queue.put(
                {
                    "ok": False,
                    "error": str(exc),
                    "request_id": request_id,
                }
            )

    logging.info(
        "[WORKER STT] Processo encerrado. Toda a memória VRAM/RAM foi devolvida ao sistema."
    )

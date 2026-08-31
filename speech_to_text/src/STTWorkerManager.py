import threading
import multiprocessing as mp
import time
import queue
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
        self.worker_process = None
        self.audio_chunk_queue = None
        self.text_result_queue = None
        self.models_dir = models_dir

    def ensure_worker_running(self):
        with self.lock:
            if self.worker_process is None or not self.worker_process.is_alive():
                logging.info("[MANAGER STT] Subindo novo worker isolado para STT...")
                self.audio_chunk_queue = mp.Queue()
                self.text_result_queue = mp.Queue()
                models_dir = self.models_dir
                self.worker_process = mp.Process(
                    target=stt_worker_process,
                    args=(self.audio_chunk_queue, self.text_result_queue, models_dir),
                    daemon=True,
                )
                self.worker_process.start()

    def send_chunk(self, chunk):
        self.ensure_worker_running()
        self.audio_chunk_queue.put(chunk)

    def get_result(self, timeout=0.1):
        if self.text_result_queue is None:
            return None
        try:
            return self.text_result_queue.get(timeout=timeout)
        except Exception:
            # mp.Queue may raise different exceptions depending on platform;
            # treat any exception as no result within timeout.
            return None

    def stop_worker(self):
        with self.lock:
            if self.worker_process and self.worker_process.is_alive():
                self.audio_chunk_queue.put("SHUTDOWN")
                self.worker_process.join(timeout=3)
                if self.worker_process.is_alive():
                    self.worker_process.terminate()
                self.worker_process = None


# ==============================================================================
# WORKER PROCESS (ISOLADO): O VoiceAgent / PyTorch rodam EXCLUSIVAMENTE aqui
# ==============================================================================
def stt_worker_process(
    audio_chunk_queue: mp.Queue, text_result_queue: mp.Queue, models_dir: Path
):
    """Processo isolado para transcrição. O encerramento deste processo devolve 100% da RAM/VRAM ao SO."""
    # Importações pesadas acontecem APENAS dentro do processo filho
    from src.agent import VoiceAgent

    logging.info("[WORKER STT] Inicializando modelo de IA no processo filho...")
    agent = VoiceAgent(models_dir)
    logging.info("[WORKER STT] Modelo pronto para transcrição.")

    last_used = time.monotonic()

    while True:
        try:
            # Aguarda novo chunk de áudio para transcrição
            item = audio_chunk_queue.get(timeout=1.0)
        except queue.Empty:
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

        chunk = item
        last_used = time.monotonic()

        try:
            text = agent.transcribe_chunk(chunk)
            if text:
                text_result_queue.put({"ok": True, "text": text})
            else:
                text_result_queue.put({"ok": True, "text": None})
        except Exception as e:
            logging.error("[WORKER STT] Erro durante transcrição: %s", e)
            text_result_queue.put({"ok": False, "error": str(e)})

    logging.info(
        "[WORKER STT] Processo encerrado. Toda a memória VRAM/RAM foi devolvida ao sistema."
    )

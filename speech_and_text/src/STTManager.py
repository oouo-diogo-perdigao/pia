import multiprocessing as mp
import queue
import threading
import time
import uuid
from pathlib import Path
from enum import Enum

from .config import (
    UNLOAD_TIMEOUT_SECONDS,
    logging,
    MODELS_DIR,
    OPENAI_COMPAT_TIMEOUT_SECONDS,
)
from .AudioRecorder import AudioRecorder, worker_audio_bridge
from .utils import play_sound_async, insert_text_at_cursor

SOUNDS_DIR = Path(__file__).parent / ".." / ".." / "sounds"
END_SOUND = SOUNDS_DIR / "end.mp3"
START_SOUND = SOUNDS_DIR / "start.mp3"


class SATState(Enum):
    # Parado, memoria descarregada
    IDLE = "IDLE"
    # Gravando audios
    RECORDING = "RECORDING"
    # Gravador parou, aguardando esvaziar último buffer/transcrição
    STOPPING = "STOPPING"
    # Finalizado
    FINISHED = "FINISHED"


# ==============================================================================
# GERENCIADOR DO WORKER NO PROCESSO PRINCIPAL
# ==============================================================================
class STTManager:
    """
    Holds shared objects and controls background workers.

    Responsibilities:
    - create and expose the AudioRecorder
    - create STTManager
    - manage background bridge thread lifecycle and text distribution queues
    """

    def __init__(self):
        """Manage a separate process that runs the heavy STT model."""
        self.lock = threading.Lock()
        self.api_lock = threading.Lock()
        self.worker_process = None
        self.audio_chunk_queue = None
        self.text_result_queue = None
        self.api_result_queue = None
        self.models_dir = MODELS_DIR

        self.recorder = AudioRecorder()

        # 1. Fila central onde o worker_audio_bridge despeja os textos novos
        self.transcribed_texts: queue.Queue = queue.Queue()
        # 2. Fila do /status tradicional (máx 200)
        self.status_queue: queue.Queue = queue.Queue(maxsize=200)
        # 3. Fila de inserção de texto no cursor (opcional, controlada por /insert)
        self.insert_queue: queue.Queue | None = None
        # 4. Lista de filas individuais para cada cliente SSE conectado
        self.stream_queues = []

        self.is_transcribing_event = threading.Event()
        self.stop_bridge_event = threading.Event()
        self.bridge_thread: threading.Thread | None = None
        self.state_lock = threading.RLock()

        self.status: SATState = SATState.IDLE
        self.insert_at_cursor: bool = True  # Controlado pela rota POST /insert

        self.STT_INSERT_THREAD = None

        # Thread central que despacha os textos da fila bruta para o status_queue e SSEs
        self.text_dispatcher = threading.Thread(
            target=self._text_dispatcher, daemon=True
        )
        self.text_dispatcher.start()
        self.timeout = OPENAI_COMPAT_TIMEOUT_SECONDS

    def models(self):
        return (
            # stt
            "gpt-transcribe",
            "whisper-1",
        )

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

        language = self._normalize_language(language)

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

            deadline = time.monotonic() + self.timeout
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

    def _normalize_language(self, language: str | None) -> str | None:
        if language is None:
            return None
        value = language.strip()
        if not value:
            return None
        # Open WebUI may expose locale-style values such as pt-BR. faster-whisper
        # expects a language code such as pt, en, es, etc.
        return value.replace("_", "-").split("-", 1)[0].lower()

    def get_status_payload(self) -> dict:
        # Determina se ainda há relevância/atividade aguardando processamento
        is_active = (
            self.status in (SATState.RECORDING, SATState.STOPPING)
            or self.is_transcribing_event.is_set()
            or not self.transcribed_texts.empty()
        )
        return {
            "status": self.status.value,
            "is_speaking": self.recorder.is_speaking,
            "is_transcribing": self.is_transcribing_event.is_set(),
            "insert_at_cursor": self.insert_at_cursor,
            "is_active": is_active,  # Informa ao client se o canal ainda tem utilidade
        }

    def _clear_status_queue(self) -> None:
        """Esvazia a fila de status com segurança sem manipular o mutex interno."""
        while not self.status_queue.empty():
            try:
                self.status_queue.get_nowait()
            except queue.Empty:
                break

    def start(self) -> None:
        with self.state_lock:
            if self.status == SATState.RECORDING:
                return

            # Garante que a thread anterior terminou antes de iniciar outra
            if self.bridge_thread and self.bridge_thread.is_alive():
                logging.info(
                    "[APP] Aguardando encerramento da thread de bridge anterior..."
                )
                self.stop_bridge_event.set()
                self.bridge_thread.join(timeout=2.0)
            logging.info("[APP] Iniciando gravação e resetando filas de status...")

            self._clear_status_queue()

            # Garante thread e fila de inserção ativas caso o cursor esteja habilitado
            self._ensure_insert_worker_locked()

            self.recorder.start()
            self.stop_bridge_event.clear()
            self.bridge_thread = threading.Thread(
                target=worker_audio_bridge,
                args=(
                    self.recorder,
                    self,
                    self.transcribed_texts,
                    self.is_transcribing_event,
                    self.stop_bridge_event,
                ),
                daemon=True,
            )
            self.bridge_thread.start()
            # warm up STT in background
            threading.Thread(target=self.ensure_worker_running, daemon=True).start()
            self.status = SATState.RECORDING
            play_sound_async(START_SOUND)

    def get_status_queue(self) -> list[str]:
        """Return the queue of transcribed texts."""
        text_list = []
        with self.state_lock:
            while not self.status_queue.empty():
                try:
                    text = self.status_queue.get_nowait()
                    if text is not None:
                        text_list.append(text)
                except queue.Empty:
                    break
        return text_list

    # region stream
    def add_stream_queue(self) -> queue.Queue:
        """Cria e registra uma nova fila para um cliente de stream SSE."""
        logging.info("[APP] Adicionando nova fila de stream SSE.")
        client_queue = queue.Queue()
        with self.state_lock:
            self.stream_queues.append(client_queue)
        return client_queue

    def remove_stream_queue(self, client_queue: queue.Queue) -> None:
        """Remove a fila de um cliente SSE desconectado."""
        logging.info("[APP] Removendo fila de stream SSE de cliente desconectado.")
        with self.state_lock:
            if client_queue in self.stream_queues:
                self.stream_queues.remove(client_queue)

    def get_stream_queue(self, client_queue: queue.Queue) -> list[str]:
        """Coleta os chunks acumulados da fila específica do cliente e monta o payload."""
        text_chunks = []
        while not client_queue.empty():
            try:
                text_chunks.append(client_queue.get_nowait())
            except Exception:
                break

        return text_chunks

    # endregion

    def stop(self) -> None:
        with self.state_lock:
            if self.status != SATState.RECORDING:
                return
            logging.info("[APP] Parando gravador...")
            self.recorder.stop()

            # Sinaliza a parada para a thread de bridge
            self.stop_bridge_event.set()
            self.status = SATState.STOPPING

            # injeta none na fila principal
            self.transcribed_texts.put(None)

    # region insert
    def _stt_insert_worker_loop(self, target_queue: queue.Queue):
        logging.info("[STT] Worker de inserção ativo.")
        while True:
            try:
                text = target_queue.get(block=True)

                if text is None:
                    target_queue.task_done()
                    break

                if self.insert_at_cursor and text and text.strip():
                    insert_text_at_cursor(text)

                target_queue.task_done()

            except Exception:
                logging.exception("[STT] Erro no worker de inserção.")

        with self.state_lock:
            if self.insert_queue is target_queue:
                self.insert_queue = None

        play_sound_async(END_SOUND)
        logging.info("[STT] Worker de inserção finalizado.")

    # endregion

    def _text_dispatcher(self):
        """Distribui os chunks recebidos para status, SSEs e fila de inserção no cursor."""
        while True:
            # 1. ETAPA DE CAPTURA (Sem try/finally para não misturar contadores)
            try:
                chunk = self.transcribed_texts.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception:
                logging.exception(
                    "[Dispatcher] Erro inesperado ao obter item da fila principal."
                )
                time.sleep(0.1)
                continue

            # A partir deste ponto, TEMOS um item retirado da fila.
            # O task_done() ocorrerá obrigatoriamente no finally deste bloco.
            try:
                if chunk is None:
                    # Sinal de término propagado para o worker de inserção
                    with self.state_lock:
                        if self.insert_queue:
                            try:
                                self.insert_queue.put_nowait(None)
                            except Exception:
                                pass
                        # Quando a gravação para e o lote é limpo, ajustamos o status de volta para IDLE/FINISHED
                        if self.status == SATState.STOPPING:
                            self.status = SATState.FINISHED
                else:
                    # Distribuição normal do texto
                    with self.state_lock:
                        # 2. Envia para o /status (com limite de 200)
                        try:
                            self.status_queue.put_nowait(chunk)
                        except queue.Full:
                            try:
                                self.status_queue.get_nowait()
                                self.status_queue.put_nowait(chunk)
                            except Exception:
                                pass

                        # 3. Envia para os streams SSE ativos
                        for q in self.stream_queues:
                            try:
                                q.put_nowait(chunk)
                            except Exception:
                                pass

                        # 4. Envia para o worker de inserção no cursor
                        if self.insert_queue:
                            try:
                                self.insert_queue.put_nowait(chunk)
                            except Exception:
                                pass

            except Exception:
                logging.exception(
                    "[Dispatcher] Erro ao processar/despachar o chunk de texto."
                )
            finally:
                # Executado exatamente uma vez por item retirado da fila principal
                self.transcribed_texts.task_done()

    def _ensure_insert_worker_locked(self) -> None:
        """Garante que a fila e a thread de inserção no cursor estejam ativas (deve ser chamado com o state_lock adquirido)."""
        if not self.insert_at_cursor:
            return

        if self.insert_queue is None:
            self.insert_queue = queue.Queue()

        if self.STT_INSERT_THREAD is None or not self.STT_INSERT_THREAD.is_alive():
            logging.info("[APP] Reiniciando worker de inserção de texto no cursor...")
            current_q = self.insert_queue
            self.STT_INSERT_THREAD = threading.Thread(
                target=self._stt_insert_worker_loop,
                args=(current_q,),
                daemon=True,
                name="STTInsertWorker",
            )
            self.STT_INSERT_THREAD.start()

    def shutdown(self) -> None:
        logging.info("[APP] Shutdown requested. Stopping recording and STT worker.")
        try:
            self.stop()
        finally:
            self.stop_worker()


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

from __future__ import annotations

import threading
import queue
import time
from pathlib import Path

from .AudioRecorder import AudioRecorder, worker_audio_bridge
from .STTWorkerManager import STTWorkerManager
from .config import logging
from utils import play_sound_async, insert_text_at_cursor
from enum import Enum

SOUNDS_DIR = Path(__file__).parent / ".." / ".." / "sounds"
END_SOUND = SOUNDS_DIR / "end.mp3"
START_SOUND = SOUNDS_DIR / "start.mp3"
MODELS_DIR = Path(__file__).parent.parent / "models_cache"


class STTState(Enum):
    # Parado, memoria descarregada
    IDLE = "IDLE"
    # Parado, memoria carregada, aguardando iniciar gravação
    WARMUP = "WARMUP"
    # Gravando audios
    RECORDING = "RECORDING"
    # Gravador parou, aguardando esvaziar último buffer/transcrição
    STOPPING = "STOPPING"
    # Finalizado
    FINISHED = "FINISHED"


class AppState:
    """Holds shared objects and controls background workers.

    Responsibilities:
    - create and expose the AudioRecorder
    - create STTWorkerManager
    - manage background bridge thread lifecycle and text distribution queues
    """

    def __init__(self):
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

        self.status: STTState = STTState.IDLE
        self.insert_at_cursor: bool = True  # Controlado pela rota POST /insert

        self.stt_manager = STTWorkerManager(models_dir=MODELS_DIR)
        self.STT_INSERT_THREAD = None

        # Thread central que despacha os textos da fila bruta para o status_queue e SSEs
        self.text_dispatcher = threading.Thread(
            target=self._text_dispatcher, daemon=True
        )
        self.text_dispatcher.start()

    def warmup(self) -> None:
        """Warm up the STT worker in a background thread."""
        if self.status == STTState.IDLE:
            logging.info("[APP] Warming up STT worker in background...")
            threading.Thread(
                target=self.stt_manager.ensure_worker_running, daemon=True
            ).start()

    def get_status_payload(self) -> dict:
        # Determina se ainda há relevância/atividade aguardando processamento
        is_active = (
            self.status in (STTState.RECORDING, STTState.STOPPING)
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
            if self.status == STTState.RECORDING:
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
                    self.stt_manager,
                    self.transcribed_texts,
                    self.is_transcribing_event,
                    self.stop_bridge_event,
                ),
                daemon=True,
            )
            self.bridge_thread.start()
            # warm up STT in background
            threading.Thread(
                target=self.stt_manager.ensure_worker_running, daemon=True
            ).start()
            self.status = STTState.RECORDING
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
            if self.status != STTState.RECORDING:
                return
            logging.info("[APP] Parando gravador...")
            self.recorder.stop()

            # Sinaliza a parada para a thread de bridge
            self.stop_bridge_event.set()
            self.status = STTState.STOPPING

            # injeta none na fila principal
            self.transcribed_texts.put(None)

    # region insert
    def start_cursor_insert(self) -> None:
        with self.state_lock:
            self.insert_at_cursor = True
            self._ensure_insert_worker_locked()

    def stop_cursor_insert(self) -> None:
        with self.state_lock:
            self.insert_at_cursor = False
            if self.insert_queue:
                self.insert_queue.put(None)  # Envia sinal para o worker fechar
                self.insert_queue = None
            logging.info("[APP] Inserção de texto no cursor desativada.")

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
                        if self.status == STTState.STOPPING:
                            self.status = STTState.FINISHED
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
            self.stt_manager.stop_worker()


APP_STATE: AppState | None = None


def get_app_state() -> AppState:
    global APP_STATE
    if APP_STATE is None:
        APP_STATE = AppState()
    return APP_STATE

from __future__ import annotations  # Ativa a avaliação adiada de tipagem
import queue
import threading
import wave
import logging
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from TTSManager import TTSManager


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


# ==============================================================================
# PLAYER AUDIO LOCAL PARA AHK (Roda usando sounddevice isoladamente)
# ==============================================================================
class AudioPlayer:
    def __init__(self, tts_manager: TTSManager):
        self.tts_manager = tts_manager
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.status = "idle"
        self.worker_thread = None
        self._stop_event = threading.Event()

    def add_job(
        self, text, voice, speed, device=None, style=None
    ):  # <--- Adicionado style
        with self.lock:
            self._stop_event.clear()
            self.queue.put(
                {
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "device": device,
                    "style": style,  # <--- Guarda o estilo na fila
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

        while not self._stop_event.is_set():
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                with self.lock:
                    self.status = "idle"
                break

            # Extrai os parâmetros do item, incluindo o estilo
            text, voice, speed, device, style = (
                item["text"],
                item["voice"],
                item["speed"],
                item.get("device"),
                item.get("style"),
            )

            try:
                if self._stop_event.is_set():
                    break

                # Passa o style para o manager decidir qual engine acionar
                wav_bytes = self.tts_manager.generate_wav(
                    text, voice, speed, style=style
                )

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

                    logging.info("[PLAYER] Emitindo áudio...")
                    # Executa o áudio no dispositivo encontrado (ou no padrão se for None)
                    sd.play(arr, samplerate=wf.getframerate(), device=target_device)
                    sd.wait()

            except Exception:
                logging.exception("Erro durante a reprodução local.")
            finally:
                if self.queue.empty() or self._stop_event.is_set():
                    with self.lock:
                        self.status = "idle"

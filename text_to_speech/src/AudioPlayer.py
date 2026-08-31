from __future__ import annotations  # Ativa a avaliação adiada de tipagem
import queue
import threading
import wave
import logging
import io


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

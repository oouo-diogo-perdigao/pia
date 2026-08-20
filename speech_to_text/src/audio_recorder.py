from __future__ import annotations

import io
import logging
import queue
import wave
import numpy as np
import sounddevice as sd


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self.is_speaking = False

        self.audio_queue = queue.Queue()
        self._raw_frames = []

        # Configurações do Buffer de Fala (Estilo VTuber)
        self.speech_threshold = 0.0030  # Sensibilidade de captação de voz
        self.silence_chunks_limit = 18  # ~0.55 segundos de silêncio para fechar a frase
        self.silence_counter = 0
        self.has_spoken = False

    def _audio_callback(
        self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags
    ) -> None:
        if status:
            logging.warning("[AUDIO] Status do SoundDevice: %s", status)
        if not self.is_recording:
            return

        rms = float(np.sqrt(np.mean(indata**2)))
        is_above_threshold = rms > self.speech_threshold

        # Detecta se a pessoa está falando
        if is_above_threshold:
            self.is_speaking = True
            self.has_spoken = True
            self.silence_counter = 0
            self._raw_frames.append(indata.copy())
        elif self.has_spoken:
            # A pessoa começou a falar e agora fez uma pausa/silêncio
            self._raw_frames.append(indata.copy())
            self.silence_counter += 1

            # Quando acumula ~0.6s de silêncio APÓS falar, fecha o bloco da frase completa
            if self.silence_counter >= self.silence_chunks_limit:
                concat_data = np.vstack(self._raw_frames)

                # Só envia se a frase tiver pelo menos 0.8s de áudio
                if len(concat_data) >= int(self.sample_rate * 0.8):
                    chunk_rms = float(np.sqrt(np.mean(concat_data**2)))
                    logging.info(
                        "[AUDIO] Frase concluída (RMS: %.4f). Enviando para transcrição...",
                        chunk_rms,
                    )
                    self.audio_queue.put(self._to_wav(concat_data))

                # Reseta os controles
                self._raw_frames = []
                self.silence_counter = 0
                self.has_spoken = False
                self.is_speaking = False

    def _to_wav(self, audio_data: np.ndarray) -> bytes:
        audio_int16 = (audio_data * 32767).astype(np.int16)
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())
        return wav_buffer.getvalue()

    def start(self) -> None:
        if self.is_recording:
            return
        self.is_recording = True
        self.is_speaking = False
        self.has_spoken = False
        self.silence_counter = 0
        self._raw_frames = []

        logging.info("[AUDIO] Abrindo fluxo do microfone (%d Hz)...", self.sample_rate)
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._audio_callback,
            blocksize=1024,
        )
        self.stream.start()
        logging.info("[AUDIO] Microfone ativado. Escutando ambiente...")

    def stop(self) -> None:
        if not self.is_recording:
            return

        # Processa o que sobrou no buffer antes de parar o microfone
        if self.has_spoken and len(self._raw_frames) > 0:
            concat_data = np.vstack(self._raw_frames)
            if len(concat_data) >= int(self.sample_rate * 0.5):
                logging.info("[AUDIO] Enviando último trecho gravado antes de parar...")
                self.audio_queue.put(self._to_wav(concat_data))

        self.is_recording = False
        self.is_speaking = False
        self.has_spoken = False
        self._raw_frames = []

        try:
            if hasattr(self, "stream"):
                self.stream.stop()
                self.stream.close()
                logging.info("[AUDIO] Microfone desativado.")
        except Exception as e:
            logging.error("[AUDIO] Erro ao fechar microfone: %s", e)

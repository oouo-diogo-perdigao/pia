from __future__ import annotations

import io
import queue
import wave
import numpy as np
import sounddevice as sd
import os
import site
from threading import Event

from .config import STT_SAMPLE_RATE, STT_CHANNELS, STT_SPEECH_THRESHOLD, logging

# Configuração de DLLs NVIDIA
venv_path = site.getsitepackages()[0]
nvidia_bin_dir = os.path.join(venv_path, "nvidia")
if os.path.exists(nvidia_bin_dir):
    for root, dirs, files in os.walk(nvidia_bin_dir):
        if "bin" in dirs:
            try:
                os.add_dll_directory(os.path.join(root, "bin"))
            except Exception:
                pass


class AudioRecorder:
    def __init__(self):
        self.sample_rate = STT_SAMPLE_RATE
        self.channels = STT_CHANNELS
        self.is_recording = False
        self.is_speaking = False

        self.audio_queue = queue.Queue()
        self._raw_frames = []

        # Configurações do Buffer de Fala (Estilo VTuber)
        self.speech_threshold = STT_SPEECH_THRESHOLD
        self.silence_chunks_limit = 18  # ~0.55 segundos de silêncio para fechar a frase
        self.silence_counter = 0
        self.has_spoken = False
        self._debug_callback_counter = 0

    def _audio_callback(
        self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags
    ) -> None:
        if status:
            logging.warning("[AUDIO] Status do SoundDevice: %s", status)
        if not self.is_recording:
            return

        rms = float(np.sqrt(np.mean(indata**2)))
        self._debug_callback_counter += 1

        if self._debug_callback_counter >= 15:
            logging.info(
                "[AUDIO DEBUG] RMS=%.6f | threshold=%.6f | speaking=%s",
                rms,
                self.speech_threshold,
                self.is_speaking,
            )
            self._debug_callback_counter = 0

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
                        "[TRANSCRICAO ENTRADA] (RMS: %.4f)",
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

        logging.info(
            "[AUDIO] Abrindo fluxo do microfone (%d Hz, threshold=%.6f)...",
            self.sample_rate,
            self.speech_threshold,
        )
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


# NOTE:
# This module provides the AudioRecorder class. Bridge and higher-level
# orchestration should be done by an external manager to avoid globals.
def worker_audio_bridge(
    recorder: AudioRecorder,
    stt_manager,
    transcribed_texts: queue.Queue,
    is_transcribing_event: Event,
    stop_event: Event,
):
    """Read audio chunks from the recorder and forward them to the STT manager.

    When stop_event is set, the bridge enters drain mode: it keeps forwarding
    audio already queued by AudioRecorder.stop() and waits for every pending STT
    result before emitting the final None sentinel.
    """
    pending_transcriptions = 0

    while True:
        # Continue draining recorder.audio_queue after stop. This is essential
        # because AudioRecorder.stop() places the final utterance in that queue
        # immediately before STTManager sets stop_event.
        if not (stop_event.is_set() and recorder.audio_queue.empty()):
            try:
                chunk = recorder.audio_queue.get(timeout=0.05)
                try:
                    stt_manager.send_chunk(chunk)
                    pending_transcriptions += 1
                    is_transcribing_event.set()
                    logging.info(
                        "[BRIDGE] Chunk enviado ao STT. pendentes=%d",
                        pending_transcriptions,
                    )
                except Exception as e:
                    logging.exception("[BRIDGE] Erro ao enviar chunk para STT: %s", e)
                finally:
                    try:
                        recorder.audio_queue.task_done()
                    except Exception:
                        pass
            except queue.Empty:
                pass
            except Exception:
                logging.exception("[BRIDGE] Erro no repasse de áudio.")

        # Collect one result per loop. Remote providers may answer asynchronously.
        try:
            result = stt_manager.get_result(timeout=0.05)
        except Exception:
            result = None

        if result:
            if pending_transcriptions > 0:
                pending_transcriptions -= 1

            if result.get("ok") and result.get("text"):
                text = result["text"]
                logging.info("[TRANSCRICAO CONCLUIDA]: %s", text)
                transcribed_texts.put(text)
            elif not result.get("ok"):
                logging.error(
                    "[BRIDGE] Transcrição falhou: %s",
                    result.get("error", "erro desconhecido"),
                )

            if pending_transcriptions == 0:
                is_transcribing_event.clear()

        if (
            stop_event.is_set()
            and recorder.audio_queue.empty()
            and pending_transcriptions == 0
        ):
            break

    is_transcribing_event.clear()
    # The dispatcher owns shutdown of status/SSE/insert consumers. Only signal
    # completion after the final transcription result has been delivered.
    transcribed_texts.put(None)
    logging.info("[BRIDGE] Drenagem concluída; bridge finalizada.")

from __future__ import annotations

import io
import json
import time
import warnings
from pathlib import Path

from faster_whisper import WhisperModel, download_model

from .config import (
    logging,
    logger_stt,
    STT_MODEL,
    STT_DEVICE,
    STT_COMPUTE_TYPE,
    STT_CPU_THREADS,
    STT_BEAM_SIZE,
    STT_BEST_OF,
    STT_TEMPERATURE,
)

warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")


class VoiceAgent:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir

        logging.info("[STT] Carregando modelo %s em %s (%s)...", STT_MODEL, STT_DEVICE, STT_COMPUTE_TYPE)
        model_path = download_model(STT_MODEL, output_dir=str(self.models_dir))

        self.model = WhisperModel(
            model_path,
            device=STT_DEVICE,
            compute_type=STT_COMPUTE_TYPE,
            cpu_threads=STT_CPU_THREADS,
        )
        logging.info("[STT] Modelo pronto: dispositivo=%s, precisão=%s.", self.model.model.device, self.model.model.compute_type)

    @staticmethod
    def ensure_model_downloaded(model_size: str, models_dir: Path) -> None:
        models_dir.mkdir(parents=True, exist_ok=True)
        logging.info("[MODELO] Verificando arquivos no disco (%s)...", model_size)
        download_model(model_size, output_dir=str(models_dir))
        logging.info("[MODELO] Arquivos confirmados no disco.")

    def transcribe_chunk(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = "pt",
        prompt: str | None = None,
        temperature: float | None = None,
        return_metadata: bool = False,
    ) -> str | dict:
        """Transcribe an in-memory audio file.

        ``audio_bytes`` may contain WAV, MP3, WebM and other formats supported by
        PyAV/faster-whisper.  The recorder path keeps Portuguese as its default,
        while the OpenAI-compatible HTTP path may pass ``language=None`` to let
        Whisper detect the language automatically.
        """
        if not audio_bytes:
            return ""

        audio_stream = io.BytesIO(audio_bytes)

        transcription_temperature = (
            STT_TEMPERATURE if temperature is None else float(temperature)
        )

        transcribe_kwargs = {
            "language": language or None,
            "beam_size": STT_BEAM_SIZE,
            "best_of": STT_BEST_OF,
            "temperature": transcription_temperature,
            "condition_on_previous_text": False,
            "vad_filter": return_metadata,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }

        if prompt:
            transcribe_kwargs["initial_prompt"] = prompt

        def report(state, processed=0.0, duration=0.0):
            if return_metadata:
                logger_stt.info('[STT_PROGRESS] %s', json.dumps({
                    'state': state, 'processed': processed, 'duration': duration,
                    'percent': min(99.9, processed / duration * 100) if duration > 0 else 0,
                }))

        report('preparing')
        normalized = []
        try:
            segments, info = self.model.transcribe(audio_stream, **transcribe_kwargs)
            report('transcribing', 0, float(info.duration))
            last_report = time.monotonic()
            for i, segment in enumerate(segments):
                if segment.text.strip():
                    normalized.append({'id': i, 'start': float(segment.start),
                                       'end': float(segment.end), 'text': segment.text.strip()})
                if time.monotonic() - last_report >= 1:
                    report('transcribing', float(segment.end), float(info.duration))
                    last_report = time.monotonic()
            report('completed', float(info.duration), float(info.duration))
        except Exception:
            report('error')
            raise
        segments = normalized
        res = " ".join(segment["text"] for segment in segments).strip()

        if res:
            logger_stt.info(res)

        if return_metadata:
            return {"text": res, "segments": segments, "duration": float(info.duration),
                    "language": info.language}
        return res

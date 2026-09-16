from __future__ import annotations

import io
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

        logging.info("[STT] Carregando modelo %s...", STT_MODEL)
        model_path = download_model(STT_MODEL, output_dir=str(self.models_dir))

        self.model = WhisperModel(
            model_path,
            device=STT_DEVICE,
            compute_type=STT_COMPUTE_TYPE,
            cpu_threads=STT_CPU_THREADS,
        )
        logging.info("[STT] Modelo pronto na RAM.")

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
    ) -> str:
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
            "vad_filter": False,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }

        if prompt:
            transcribe_kwargs["initial_prompt"] = prompt

        segments, _ = self.model.transcribe(audio_stream, **transcribe_kwargs)

        text = [segment.text for segment in segments]
        res = " ".join(text).strip()

        if res:
            logger_stt.info(res)

        return res

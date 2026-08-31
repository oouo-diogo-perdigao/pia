from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from faster_whisper import WhisperModel, download_model
from .config import (
    logging,
    STT_MODEL,
    STT_DEVICE,
    STT_COMPUTE_TYPE,
    STT_CPU_THREADS,
    STT_BEAM_SIZE,
    STT_BEST_OF,
    STT_TEMPERATURE,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


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

    def transcribe_chunk(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            return ""

        audio_stream = io.BytesIO(wav_bytes)

        segments, _ = self.model.transcribe(
            audio_stream,
            language="pt",
            beam_size=STT_BEAM_SIZE,
            best_of=STT_BEST_OF,
            temperature=STT_TEMPERATURE,
            condition_on_previous_text=False,
            vad_filter=False,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = [segment.text for segment in segments]
        res = " ".join(text).strip()
        return res

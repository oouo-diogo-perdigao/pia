from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from faster_whisper import WhisperModel, download_model

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class VoiceAgent:
    def __init__(self, models_dir: Path):
        self.model_size = os.getenv("STT_MODEL", "large-v3-turbo")
        self.device = os.getenv("STT_DEVICE", "cpu")
        self.compute_type = os.getenv("STT_COMPUTE_TYPE", "int8")
        self.cpu_threads = int(os.getenv("STT_CPU_THREADS", "6"))
        self.models_dir = models_dir

        logging.info("[STT] Carregando modelo %s...", self.model_size)
        model_path = download_model(self.model_size, output_dir=str(self.models_dir))

        self.model = WhisperModel(
            model_path,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
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
            beam_size=int(os.getenv("STT_BEAM_SIZE", 5)),
            best_of=int(os.getenv("STT_BEST_OF", 5)),
            temperature=float(os.getenv("STT_TEMPERATURE", 0.0)),
            condition_on_previous_text=False,
            vad_filter=False,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = [segment.text for segment in segments]
        res = " ".join(text).strip()
        return res

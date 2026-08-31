"""Configuration and logging for the PIA package (src).

This is the same content as the top-level config but lives under src.
"""

from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT"))

SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", 16_000))
CHANNELS = int(os.getenv("CHANNELS", 1))
UNLOAD_TIMEOUT_SECONDS = int(os.getenv("UNLOAD_TIMEOUT_SECONDS", 600))

BASE_DIR = Path(__file__).resolve().parent
START_SOUND = str(BASE_DIR.parent / "sounds" / "start.mp3")
END_SOUND = str(BASE_DIR.parent / "sounds" / "end.mp3")

STT_MODEL = os.getenv("STT_MODEL", "large-v3-turbo")
STT_DEVICE = os.getenv("STT_DEVICE", "cpu")
STT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")
STT_CPU_THREADS = int(os.getenv("STT_CPU_THREADS", "6"))
STT_BEAM_SIZE = int(os.getenv("STT_BEAM_SIZE", 5))
STT_BEST_OF = int(os.getenv("STT_BEST_OF", 5))
STT_TEMPERATURE = float(os.getenv("STT_TEMPERATURE", 0.0))

# Logging setup
log_dir = BASE_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    rotating_handler = RotatingFileHandler(
        log_dir / "stt.log",
        maxBytes=10 * 1024 * 1024,  # Limite exato de 10 MB (10.485.760 bytes)
        backupCount=1,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)
    logger.addHandler(rotating_handler)

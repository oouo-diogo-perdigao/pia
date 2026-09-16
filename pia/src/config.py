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

RATE = int(os.getenv("RATE", "16000"))
CHANNELS = int(os.getenv("CHANNELS", "1"))
CHUNK = int(os.getenv("CHUNK", "1280"))
THRESHOLD = float(os.getenv("THRESHOLD", "0.5"))

STT_SERVER_URL = os.getenv("STT_SERVER_URL")
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL")
AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL")

BASE_DIR = Path(__file__).resolve().parent.parent
START_SOUND = str(BASE_DIR.parent / "sounds" / "start.mp3")
END_SOUND = str(BASE_DIR.parent / "sounds" / "end.mp3")

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
        log_dir / "pia.log",
        maxBytes=10 * 1024 * 1024,  # Limite exato de 10 MB (10.485.760 bytes)
        backupCount=1,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)
    logger.addHandler(rotating_handler)

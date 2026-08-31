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

DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "pm_santa")
DEFAULT_SPEED = float(os.getenv("DEFAULT_SPEED", "0.95"))

IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "600"))
DEVICE = os.getenv("DEVICE", "cuda")
MODEL_DIR = os.getenv("MODEL_DIR", "./models_cache/Kokoro-82M").strip()


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
        log_dir / "tts.log",
        maxBytes=10 * 1024 * 1024,  # Limite exato de 10 MB (10.485.760 bytes)
        backupCount=1,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)
    logger.addHandler(rotating_handler)


# Crie um logger dedicado para os textos emitidos (no topo do arquivo ou logo após as importações)
logger_tts = logging.getLogger("logger_tts")
logger_tts.setLevel(logging.INFO)
logger_tts.propagate = False  # Evita que suba para o log geral

if not logger_tts.handlers:
    formatter_tts = logging.Formatter("%(asctime)s\n%(message)s")

    stream_handler_tts = logging.StreamHandler()
    stream_handler_tts.setFormatter(formatter_tts)
    logger_tts.addHandler(stream_handler_tts)

    file_handler_tts = RotatingFileHandler(
        log_dir / "emited.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler_tts.setFormatter(formatter_tts)
    logger_tts.addHandler(file_handler_tts)

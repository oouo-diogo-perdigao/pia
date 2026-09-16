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

# Se vazio, o endpoint OpenAI-compatible fica sem autenticação. Isso é útil
# em localhost. Se exposto na rede, defina OPENAI_COMPAT_API_KEY no ambiente.
OPENAI_COMPAT_API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()

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

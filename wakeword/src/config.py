"""Configuration and logging for the wakeword package (src).

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

BASE_DIR = Path(__file__).resolve().parent
START_SOUND = str(BASE_DIR.parent / "sounds" / "start.mp3")
END_SOUND = str(BASE_DIR.parent / "sounds" / "end.mp3")

# Logging setup
log_dir = BASE_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "wakeword_agent.log", encoding="utf-8"),
        RotatingFileHandler(
            log_dir / "wakeword_agent.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        ),
    ],
)

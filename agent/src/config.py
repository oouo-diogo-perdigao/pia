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

USER_NAME = os.getenv("USER_NAME", "Diogo").strip() or "Diogo"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_STT_MODEL = os.getenv("GEMINI_STT_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_AGENT_MODEL = os.getenv("GEMINI_AGENT_MODEL", "gemini-3.5-flash-lite").strip()
VSCODE_COMMAND = os.getenv("VSCODE_COMMAND", "code").strip() or "code"
DEFAULT_LOCATION = os.getenv(
    "DEFAULT_LOCATION", "Belo Horizonte, Minas Gerais, Brasil"
).strip()

TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://localhost:8763").strip()

ROOT_DIR = BASE_DIR
MEMORY_FILE = BASE_DIR / "data" / "memory.json"
LEARNING_DIR = BASE_DIR / "learning_requests"

sample_rate: int = 16_000
channels: int = 1

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
        log_dir / "agent.log",
        maxBytes=10 * 1024 * 1024,  # Limite exato de 10 MB (10.485.760 bytes)
        backupCount=1,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)
    logger.addHandler(rotating_handler)

# Crie um logger dedicado para os textos emitidos (no topo do arquivo ou logo após as importações)
logger_llm = logging.getLogger("logger_llm")
logger_llm.setLevel(logging.INFO)
logger_llm.propagate = False  # Evita que suba para o log geral

if not logger_llm.handlers:
    # Handler dedicado e separado para entradas e saídas da LLM
    logger_llm = logging.getLogger("llm_trace")
    logger_llm.setLevel(logging.INFO)
    logger_llm.propagate = False
    llm_rotating_handler = RotatingFileHandler(
        log_dir / "llm_interactions.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    llm_rotating_handler.setFormatter(formatter)
    logger_llm.addHandler(llm_rotating_handler)

"""Configuration and logging for the PIA package (src).

This is the same content as the top-level config but lives under src.
"""

from __future__ import annotations
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT"))


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)).strip())


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)).strip())


# Se vazio, o endpoint OpenAI-compatible fica sem autenticação. Isso é útil
# em localhost. Se exposto na rede, defina OPENAI_COMPAT_API_KEY no ambiente.
OPENAI_COMPAT_API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_TIMEOUT_SECONDS = _float_env("COMFYUI_TIMEOUT_SECONDS", 300.0)
COMFYUI_POLL_INTERVAL_SECONDS = _float_env("COMFYUI_POLL_INTERVAL_SECONDS", 0.35)
COMFYUI_SERIALIZE_JOBS = _bool_env("COMFYUI_SERIALIZE_JOBS", True)
COMFYUI_AUTO_FREE = _bool_env("COMFYUI_AUTO_FREE", True)
COMFYUI_UNLOAD_MODELS = _bool_env("COMFYUI_UNLOAD_MODELS", True)
COMFYUI_FREE_MEMORY = _bool_env("COMFYUI_FREE_MEMORY", True)
COMFYUI_SAFE_FREE = _bool_env("COMFYUI_SAFE_FREE", True)

# checkpoint = arquivo all-in-one em models/checkpoints / CheckpointLoaderSimple
# split      = UNET + CLIP-L + T5 + VAE separados
COMFYUI_MODEL_LAYOUT = os.getenv("COMFYUI_MODEL_LAYOUT", "checkpoint").strip().lower()
COMFYUI_CHECKPOINT = os.getenv(
    "COMFYUI_CHECKPOINT", "flux1-schnell.safetensors"
).strip()
COMFYUI_UNET = os.getenv("COMFYUI_UNET", "flux1-schnell.safetensors").strip()
COMFYUI_CLIP_L = os.getenv("COMFYUI_CLIP_L", "clip_l.safetensors").strip()
COMFYUI_T5XXL = os.getenv("COMFYUI_T5XXL", "t5xxl_fp8_e4m3fn.safetensors").strip()
COMFYUI_VAE = os.getenv("COMFYUI_VAE", "ae.safetensors").strip()

IMAGE_STEPS = _int_env("IMAGE_STEPS", 4)
IMAGE_CFG = _float_env("IMAGE_CFG", 1.0)
IMAGE_SAMPLER = os.getenv("IMAGE_SAMPLER", "euler").strip()
IMAGE_SCHEDULER = os.getenv("IMAGE_SCHEDULER", "simple").strip()
IMAGE_FLUX_GUIDANCE = _float_env("IMAGE_FLUX_GUIDANCE", 3.5)

IMAGE_EDIT_DENOISE = _float_env("IMAGE_EDIT_DENOISE", 0.65)
IMAGE_EDIT_MASK_DENOISE = _float_env("IMAGE_EDIT_MASK_DENOISE", 1.0)
IMAGE_EDIT_GROW_MASK_BY = _int_env("IMAGE_EDIT_GROW_MASK_BY", 6)
IMAGE_VARIATION_DENOISE = _float_env("IMAGE_VARIATION_DENOISE", 0.75)
IMAGE_VARIATION_PROMPT = os.getenv(
    "IMAGE_VARIATION_PROMPT",
    "Create a visually coherent variation of the input image while preserving its main subject and composition.",
).strip()

OPENAI_IMAGE_MODEL_ID = os.getenv("OPENAI_IMAGE_MODEL_ID", "gpt-image-1").strip()
IMAGE_DEFAULT_SIZE = os.getenv("IMAGE_DEFAULT_SIZE", "1024x1024").strip()
IMAGE_MAX_N = _int_env("IMAGE_MAX_N", 4)
IMAGE_MAX_UPLOAD_BYTES = _int_env("IMAGE_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
OUTPUT_CACHE_DIR = Path(
    os.getenv("IMAGE_OUTPUT_CACHE_DIR", str(BASE_DIR / "cache" / "openai_images"))
)
OUTPUT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_CACHE_TTL_SECONDS = _int_env("IMAGE_OUTPUT_CACHE_TTL_SECONDS", 900)

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

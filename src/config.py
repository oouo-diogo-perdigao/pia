from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)).strip())


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)).strip())


def _str_env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _path_env(name: str, default: str) -> Path:
    return Path(os.getenv(name, default).strip())


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ============================================================
# GENERIC
# ============================================================
HOST = _str_env("HOST", "127.0.0.1")
PORT = _int_env("PORT", 8762)
# Se vazio, o endpoint OpenAI-compatible fica sem autenticação.
OPENAI_COMPAT_API_KEY = _str_env("OPENAI_COMPAT_API_KEY", "")
OPENAI_COMPAT_TIMEOUT_SECONDS = _int_env("OPENAI_COMPAT_TIMEOUT_SECONDS", 180)
# 10MB
OPENAI_COMPAT_MAX_UPLOAD_BYTES = _int_env("OPENAI_COMPAT_MAX_UPLOAD_BYTES", 104857600)
START_SOUND = _path_env("START_SOUND", str(BASE_DIR / "sounds" / "start.mp3"))
END_SOUND = _path_env("END_SOUND", str(BASE_DIR / "sounds" / "end.mp3"))
MODELS_DIR = _path_env("MODELS_DIR", str(BASE_DIR / "cache"))
PUBLIC_BASE_URL = _str_env("PUBLIC_BASE_URL", f"http://{HOST}:{PORT}")

# ============================================================
# STT
# ============================================================
STT_MODEL = _str_env("STT_MODEL", "large-v3-turbo")
STT_DEVICE = _str_env("STT_DEVICE", "cpu")
STT_COMPUTE_TYPE = _str_env("STT_COMPUTE_TYPE", "int8")
STT_CPU_THREADS = _int_env("STT_CPU_THREADS", 6)
STT_BEAM_SIZE = _int_env("STT_BEAM_SIZE", 5)
STT_BEST_OF = _int_env("STT_BEST_OF", 5)
STT_TEMPERATURE = _float_env("STT_TEMPERATURE", 0.0)
STT_SAMPLE_RATE = _int_env("STT_SAMPLE_RATE", 16_000)
STT_CHANNELS = _int_env("STT_CHANNELS", 1)
STT_WHISPER_TIMEOUT = _int_env("STT_WHISPER_TIMEOUT", 600)

# Provider prioritário. Valores: gemini, grok, local.
# O fallback para o Whisper local é automático quando o provider remoto falha.
STT_PROVIDER = _str_env("STT_PROVIDER", "gemini").lower()
STT_REMOTE_COOLDOWN_SECONDS = _int_env("STT_REMOTE_COOLDOWN_SECONDS", 900)
STT_GEMINI_API_KEY = _str_env("STT_GEMINI_API_KEY", _str_env("GEMINI_API_KEY", ""))
STT_GEMINI_MODEL = _str_env("STT_GEMINI_MODEL", "gemini-3.5-transcribe")
STT_GROK_API_KEY = _str_env("STT_GROK_API_KEY", _str_env("XAI_API_KEY", ""))
STT_GROK_MODEL = _str_env("STT_GROK_MODEL", "xai/grok-voice-transcribe-2.0")

# ============================================================
# TTS
# ============================================================
TTS_DEFAULT_VOICE = _str_env("TTS_DEFAULT_VOICE", "pm_santa")
TTS_DEFAULT_SPEED = _float_env("TTS_DEFAULT_SPEED", 0.95)
TTS_KOKORO_IDLE_TIMEOUT = _int_env("TTS_KOKORO_IDLE_TIMEOUT", 600)
TTS_QWEN_IDLE_TIMEOUT = _int_env("TTS_QWEN_IDLE_TIMEOUT", 300)
TTS_DEVICE = _str_env("TTS_DEVICE", "cuda")
TTS_KOKORO_MODEL = _str_env("TTS_KOKORO_MODEL", "./cache/Kokoro-82M")
TTS_LLM_MODEL = _str_env("TTS_LLM_MODEL", "my-agent")

# ============================================================
# ICE (Image Create/Edit)
# ============================================================
ICE_COMFYUI_URL = _str_env("ICE_COMFYUI_URL", "http://127.0.0.1:8188")
ICE_COMFYUI_TIMEOUT_SECONDS = _float_env("ICE_COMFYUI_TIMEOUT_SECONDS", 300.0)
ICE_COMFYUI_POLL_INTERVAL_SECONDS = _float_env(
    "ICE_COMFYUI_POLL_INTERVAL_SECONDS", 0.35
)
ICE_COMFYUI_SERIALIZE_JOBS = _bool_env("ICE_COMFYUI_SERIALIZE_JOBS", True)
ICE_COMFYUI_AUTO_FREE = _bool_env("ICE_COMFYUI_AUTO_FREE", True)
ICE_COMFYUI_UNLOAD_MODELS = _bool_env("ICE_COMFYUI_UNLOAD_MODELS", True)
ICE_COMFYUI_FREE_MEMORY = _bool_env("ICE_COMFYUI_FREE_MEMORY", True)
ICE_COMFYUI_SAFE_FREE = _bool_env("ICE_COMFYUI_SAFE_FREE", True)

# checkpoint = arquivo all-in-one em models/checkpoints / CheckpointLoaderSimple
# split      = UNET + CLIP-L + T5 + VAE separados
ICE_COMFYUI_MODEL_LAYOUT = _str_env("ICE_COMFYUI_MODEL_LAYOUT", "checkpoint").lower()
ICE_COMFYUI_CHECKPOINT = _str_env("ICE_COMFYUI_CHECKPOINT", "flux1-schnell.safetensors")
ICE_COMFYUI_UNET = _str_env("ICE_COMFYUI_UNET", "flux1-schnell.safetensors")
ICE_COMFYUI_CLIP_L = _str_env("ICE_COMFYUI_CLIP_L", "clip_l.safetensors")
ICE_COMFYUI_T5XXL = _str_env("ICE_COMFYUI_T5XXL", "t5xxl_fp8_e4m3fn.safetensors")
ICE_COMFYUI_VAE = _str_env("ICE_COMFYUI_VAE", "ae.safetensors")

ICE_IMAGE_STEPS = _int_env("ICE_IMAGE_STEPS", 4)
ICE_IMAGE_CFG = _float_env("ICE_IMAGE_CFG", 1.0)
ICE_IMAGE_SAMPLER = _str_env("ICE_IMAGE_SAMPLER", "euler")
ICE_IMAGE_SCHEDULER = _str_env("ICE_IMAGE_SCHEDULER", "simple")
ICE_IMAGE_FLUX_GUIDANCE = _float_env("ICE_IMAGE_FLUX_GUIDANCE", 3.5)
ICE_IMAGE_EDIT_DENOISE = _float_env("ICE_IMAGE_EDIT_DENOISE", 0.65)
ICE_IMAGE_EDIT_MASK_DENOISE = _float_env("ICE_IMAGE_EDIT_MASK_DENOISE", 1.0)
ICE_IMAGE_EDIT_GROW_MASK_BY = _int_env("ICE_IMAGE_EDIT_GROW_MASK_BY", 6)
ICE_IMAGE_VARIATION_DENOISE = _float_env("ICE_IMAGE_VARIATION_DENOISE", 0.75)
ICE_IMAGE_VARIATION_PROMPT = _str_env(
    "ICE_IMAGE_VARIATION_PROMPT",
    "Create a visually coherent variation of the input image while preserving its main subject and composition.",
)

ICE_IMAGE_DEFAULT_SIZE = _str_env("ICE_IMAGE_DEFAULT_SIZE", "1024x1024")
ICE_IMAGE_MAX_N = _int_env("ICE_IMAGE_MAX_N", 4)

ICE_OUTPUT_CACHE_DIR = _path_env(
    "ICE_OUTPUT_CACHE_DIR", str(BASE_DIR / "cache" / "ice_images")
)
ICE_OUTPUT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
ICE_OUTPUT_CACHE_TTL_SECONDS = _int_env("ICE_OUTPUT_CACHE_TTL_SECONDS", 900)

# ============================================================
# AGE Agent LLM
# ============================================================
AGE_USER_NAME = _str_env("AGE_USER_NAME", "Mestre")
AGE_GEMINI_API_KEY = _str_env("AGE_GEMINI_API_KEY", "")
GROQ_API_KEY = _str_env("GROQ_API_KEY", "")
DEFAULT_LOCATION = _str_env("DEFAULT_LOCATION", "Belo Horizonte, Minas Gerais, Brasil")

# ============================================================
# OVE
# ============================================================
OVE_RATE = _int_env("OVE_RATE", 16000)
OVE_CHANNELS = _int_env("OVE_CHANNELS", 1)
OVE_CHUNK = _int_env("OVE_CHUNK", 1280)
OVE_THRESHOLD = _float_env("OVE_THRESHOLD", 0.5)

# ============================================================
# Logging setup
# ============================================================
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
        maxBytes=10 * 1024 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)
    logger.addHandler(rotating_handler)

logger_stt = logging.getLogger("logger_stt")
logger_stt.setLevel(logging.INFO)
logger_stt.propagate = False

if not logger_stt.handlers:
    formatter_stt = logging.Formatter("%(asctime)s\n%(message)s")

    stream_handler_stt = logging.StreamHandler()
    stream_handler_stt.setFormatter(formatter_stt)
    logger_stt.addHandler(stream_handler_stt)
    file_handler_stt = RotatingFileHandler(
        log_dir / "emited.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler_stt.setFormatter(formatter_stt)
    logger_stt.addHandler(file_handler_stt)

logger_tts = logging.getLogger("logger_tts")
logger_tts.setLevel(logging.INFO)
logger_tts.propagate = False

if not logger_tts.handlers:
    formatter_stt = logging.Formatter("%(asctime)s\n%(message)s")

    stream_handler_tts = logging.StreamHandler()
    stream_handler_tts.setFormatter(formatter_stt)
    logger_tts.addHandler(stream_handler_tts)

    file_handler_tts = RotatingFileHandler(
        log_dir / "emited.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler_tts.setFormatter(formatter_stt)
    logger_tts.addHandler(file_handler_tts)

logger_llm = logging.getLogger("logger_llm")
logger_llm.setLevel(logging.INFO)
logger_llm.propagate = False

if not logger_llm.handlers:
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
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

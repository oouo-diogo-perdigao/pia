"""TTS package."""

from .engine import TTSManager
from .service import TTSService, TTSServiceError, get_tts_service

__all__ = ["TTSManager", "TTSService", "TTSServiceError", "get_tts_service"]

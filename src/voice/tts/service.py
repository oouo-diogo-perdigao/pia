"""Unified TTS service facade shared by /v1/tts/* and /api/pia/tts/*."""

from src.tts_service import TTSService, TTSServiceError, get_tts_service

__all__ = ["TTSService", "TTSServiceError", "get_tts_service"]

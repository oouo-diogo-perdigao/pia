"""Provider remoto OpenAI TTS."""
import json
import logging
import urllib.request
from .base import TTSProvider

logger = logging.getLogger(__name__)


class OpenAITTSProvider(TTSProvider):
    name = "OpenAI TTS"
    kind = "remote"

    def _key(self):
        try:
            from src.settings_store import get
            v = get("OPENAI_API_KEY")
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                for k in ("value", "key", "api_key", "token"):
                    if v.get(k):
                        return str(v.get(k)).strip()
        except Exception:
            pass
        return None

    def is_available(self) -> bool:
        return bool(self._key())

    def list_voices(self) -> list[dict]:
        return [{"id": v, "name": v} for v in ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]]

    def synthesize(self, text, voice, speed, response_format):
        key = self._key()
        if not key:
            raise RuntimeError("Chave OpenAI não configurada no cofre.")
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice or "alloy",
            "speed": speed,
            "response_format": response_format if response_format in ("mp3", "opus", "aac", "flac", "wav", "pcm") else "mp3",
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

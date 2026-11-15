"""Provider remoto ElevenLabs TTS."""
import json
import logging
import urllib.request
from .base import TTSProvider

logger = logging.getLogger(__name__)


class ElevenLabsProvider(TTSProvider):
    name = "ElevenLabs TTS"
    kind = "remote"

    def _key(self):
        try:
            from src.settings_store import get
            v = get("ELEVENLABS_API_KEY")
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
        return [{"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"}]

    def synthesize(self, text, voice, speed, response_format):
        key = self._key()
        if not key:
            raise RuntimeError("Chave ElevenLabs não configurada no cofre.")
        valid_voices = {v["id"] for v in self.list_voices()}
        vid = voice or "21m00Tcm4TlvDq8ikWAM"
        if vid not in valid_voices:
            raise ValueError(f"Voz inválida: {vid}")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
        payload = {"text": text}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

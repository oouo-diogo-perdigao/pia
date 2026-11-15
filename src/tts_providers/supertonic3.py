"""Provider local Supertonic 3 (wrapper sobre TTSManager existente)."""
import logging
from .base import TTSProvider

logger = logging.getLogger(__name__)


class Supertonic3Provider(TTSProvider):
    name = "Supertonic 3 (local)"
    kind = "local"

    def is_available(self) -> bool:
        return True

    def list_voices(self) -> list[dict]:
        try:
            from src.TTSManager import TTSManager
            tm = TTSManager()
            data = tm.get_voices().get("data", [])
            return [{"id": v["id"], "name": v["name"]} for v in data]
        except Exception:
            return [{"id": "pm_santa", "name": "Santa"}]

    def synthesize(self, text, voice, speed, response_format):
        from src.TTSManager import TTSManager
        tm = TTSManager()
        return tm.generate(text, voice or "pm_santa", speed, output_format=response_format)

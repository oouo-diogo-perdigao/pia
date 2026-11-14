"""Registry que descobre providers disponíveis com base no cofre."""
import importlib
import logging
from .base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_CLASSES = [
    ("supertonic3", "src.tts_providers.supertonic3", "Supertonic3Provider"),
    ("openai", "src.tts_providers.openai_tts", "OpenAITTSProvider"),
    ("elevenlabs", "src.tts_providers.elevenlabs", "ElevenLabsProvider"),
]


class TTSProviderRegistry:
    def __init__(self):
        self._providers = {}
        self._discover()

    def _discover(self):
        for key, module_path, cls_name in _PROVIDER_CLASSES:
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, cls_name)
                instance = cls()
                self._providers[key] = instance
            except Exception as e:
                logger.warning("Provider %s indisponível: %s", key, e)

    def available(self) -> list[dict]:
        result = []
        for key, prov in self._providers.items():
            try:
                avail = bool(prov.is_available())
            except Exception:
                avail = False
            result.append({
                "id": key,
                "name": getattr(prov, "name", key),
                "kind": getattr(prov, "kind", "remote"),
                "available": avail,
                "voices": prov.list_voices() if avail else [],
            })
        return result

    def get(self, key: str):
        return self._providers.get(key)

    def keys(self):
        return list(self._providers.keys())

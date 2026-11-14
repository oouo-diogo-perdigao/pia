"""Provider remoto OpenAI TTS."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from .base import AudioResult, MIME_BY_FORMAT, TTSProvider

logger = logging.getLogger(__name__)

_OPENAI_VOICES_BASE = [
    {"id": "alloy", "name": "Alloy", "lang": "multi", "gender": "neutral"},
    {"id": "echo", "name": "Echo", "lang": "multi", "gender": "male"},
    {"id": "fable", "name": "Fable", "lang": "multi", "gender": "neutral"},
    {"id": "onyx", "name": "Onyx", "lang": "multi", "gender": "male"},
    {"id": "nova", "name": "Nova", "lang": "multi", "gender": "female"},
    {"id": "shimmer", "name": "Shimmer", "lang": "multi", "gender": "female"},
]
_OPENAI_VOICES_4O = _OPENAI_VOICES_BASE + [
    {"id": "ash", "name": "Ash", "lang": "multi", "gender": "male"},
    {"id": "coral", "name": "Coral", "lang": "multi", "gender": "female"},
    {"id": "sage", "name": "Sage", "lang": "multi", "gender": "female"},
]
_OPENAI_MODELS = [
    {
        "id": "tts-1",
        "name": "OpenAI TTS-1",
        "description": "Baixa latência para respostas em tempo real",
        "size_mb": None,
    },
    {
        "id": "tts-1-hd",
        "name": "OpenAI TTS-1 HD",
        "description": "Alta definição para narração",
        "size_mb": None,
    },
    {
        "id": "gpt-4o-mini-tts",
        "name": "GPT-4o Mini TTS",
        "description": "Modelo expressivo com controle de estilo",
        "size_mb": None,
    },
]


class OpenAITTSProvider(TTSProvider):
    id = "openai"
    name = "OpenAI TTS"
    kind = "remote"
    description = "Vozes neurais na nuvem da OpenAI (requer OPENAI_API_KEY)"

    def _key(self) -> str | None:
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

    def credential_state(self) -> str:
        return "configured" if self._key() else "missing"

    def models(self) -> list[dict[str, Any]]:
        return list(_OPENAI_MODELS)

    def capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "install": False,
            "uninstall": False,
            "formats": ["mp3", "opus", "aac", "flac", "wav", "pcm"],
            "speed": {
                "supported": True,
                "min": 0.25,
                "max": 4.0,
                "step": 0.05,
                "default": 1.0,
            },
        }

    def is_available(self, model_id: str | None = None) -> bool:
        if model_id and model_id not in {m["id"] for m in _OPENAI_MODELS}:
            return False
        return bool(self._key())

    def list_voices(self, model_id: str | None = None) -> list[dict[str, Any]]:
        if model_id == "gpt-4o-mini-tts":
            return list(_OPENAI_VOICES_4O)
        return list(_OPENAI_VOICES_BASE)

    def synthesize(
        self,
        text: str,
        voice: str,
        speed: float,
        response_format: str,
        *,
        model: str | None = None,
        style: str | None = None,
        device: str | None = None,
    ) -> AudioResult:
        key = self._key()
        if not key:
            raise RuntimeError("Chave OpenAI não configurada no cofre.")
        chosen_model = model if model in {m["id"] for m in _OPENAI_MODELS} else "tts-1"
        fmt = (
            response_format.lower().strip()
            if response_format
            and response_format.lower().strip()
            in ("mp3", "opus", "aac", "flac", "wav", "pcm")
            else "mp3"
        )
        valid_voices = {v["id"] for v in self.list_voices(chosen_model)}
        chosen_voice = voice or "alloy"
        if chosen_voice not in valid_voices:
            raise ValueError(f"Voz OpenAI inválida: {chosen_voice}")

        payload: dict[str, Any] = {
            "model": chosen_model,
            "input": text,
            "voice": chosen_voice,
            "speed": float(speed),
            "response_format": fmt,
        }
        if style and chosen_model == "gpt-4o-mini-tts":
            payload["instructions"] = style
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            audio = r.read()
        return AudioResult(
            audio=audio,
            mime=MIME_BY_FORMAT.get(fmt, "audio/mpeg"),
            format=fmt,
        )

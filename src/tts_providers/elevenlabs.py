"""Provider remoto ElevenLabs TTS."""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.request
import wave
from typing import Any

from .base import AudioResult, TTSProvider

logger = logging.getLogger(__name__)

_DEFAULT_VOICES = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "lang": "en", "gender": "female"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "lang": "en", "gender": "female"},
    {"id": "TX3LPaxmHKxFdv7VOQHJ", "name": "Liam", "lang": "en", "gender": "male"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "lang": "en", "gender": "male"},
]

_ELEVEN_MODELS = [
    {
        "id": "eleven_multilingual_v2",
        "name": "Eleven Multilingual v2",
        "description": "Alta qualidade multilíngue (inclui PT-BR)",
        "size_mb": None,
    },
    {
        "id": "eleven_flash_v2_5",
        "name": "Eleven Flash v2.5",
        "description": "Ultrarrápido para conversação em tempo real",
        "size_mb": None,
    },
    {
        "id": "eleven_turbo_v2_5",
        "name": "Eleven Turbo v2.5",
        "description": "Equilíbrio entre velocidade e qualidade",
        "size_mb": None,
    },
]


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class ElevenLabsProvider(TTSProvider):
    id = "elevenlabs"
    name = "ElevenLabs TTS"
    kind = "remote"
    description = "Vozes expressivas ElevenLabs (requer ELEVENLABS_API_KEY)"

    def __init__(self):
        self._voices_cache: tuple[float, list[dict[str, Any]]] | None = None

    def _key(self) -> str | None:
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

    def credential_state(self) -> str:
        return "configured" if self._key() else "missing"

    def models(self) -> list[dict[str, Any]]:
        return list(_ELEVEN_MODELS)

    def capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "install": False,
            "uninstall": False,
            "formats": ["mp3", "wav", "pcm"],
            "speed": {
                "supported": True,
                "min": 0.7,
                "max": 1.2,
                "step": 0.05,
                "default": 1.0,
            },
        }

    def is_available(self, model_id: str | None = None) -> bool:
        if model_id and model_id not in {m["id"] for m in _ELEVEN_MODELS}:
            return False
        return bool(self._key())

    def list_voices(
        self, model_id: str | None = None, *, refresh: bool = False
    ) -> list[dict[str, Any]]:
        key = self._key()
        if not key:
            return list(_DEFAULT_VOICES)
        now = time.time()
        if (
            not refresh
            and self._voices_cache is not None
            and (now - self._voices_cache[0]) < 300
        ):
            return list(self._voices_cache[1])
        try:
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": key, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            voices = [
                {
                    "id": v["voice_id"],
                    "name": v.get("name", v["voice_id"]),
                    "lang": (v.get("labels") or {}).get("language", "multi"),
                    "gender": (v.get("labels") or {}).get("gender", "unknown"),
                }
                for v in data.get("voices", [])
                if v.get("voice_id")
            ]
            if voices:
                self._voices_cache = (now, voices)
                return list(voices)
        except Exception as exc:
            logger.debug("Falha ao listar vozes ElevenLabs: %s", exc)
        return list(_DEFAULT_VOICES)

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
            raise RuntimeError("Chave ElevenLabs não configurada no cofre.")
        valid_voices = {v["id"] for v in self.list_voices(model)}
        vid = voice or "21m00Tcm4TlvDq8ikWAM"
        if vid not in valid_voices:
            raise ValueError(f"Voz inválida: {vid}")
        chosen_model = (
            model
            if model in {m["id"] for m in _ELEVEN_MODELS}
            else "eleven_multilingual_v2"
        )
        req_fmt = (response_format or "mp3").lower().strip()
        if req_fmt in ("wav", "pcm"):
            output_format = "pcm_22050"
            accept = "audio/pcm"
        else:
            output_format = "mp3_44100_128"
            accept = "audio/mpeg"
            req_fmt = "mp3"

        clamped_speed = max(0.7, min(1.2, float(speed)))
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format={output_format}"
        payload = {
            "text": text,
            "model_id": chosen_model,
            "voice_settings": {"speed": clamped_speed},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "xi-api-key": key,
                "Content-Type": "application/json",
                "Accept": accept,
            },
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
        if req_fmt == "wav":
            return AudioResult(
                audio=_pcm_to_wav(raw, 22050),
                mime="audio/wav",
                format="wav",
                sample_rate=22050,
            )
        if req_fmt == "pcm":
            return AudioResult(
                audio=raw,
                mime="audio/pcm",
                format="pcm",
                sample_rate=22050,
            )
        return AudioResult(audio=raw, mime="audio/mpeg", format="mp3")

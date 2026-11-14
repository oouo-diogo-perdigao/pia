"""Provider local Qwen3 TTS."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from .base import AudioResult, MIME_BY_FORMAT, TTSProvider
from .local_catalog import (
    install_artifacts,
    is_manifest_installed,
    uninstall_artifacts,
)

logger = logging.getLogger(__name__)

_MODEL_ID = "qwen3-tts-1.7b"
_QWEN_VOICES = [
    {"id": "Ryan", "name": "Ryan", "lang": "en", "gender": "male"},
    {"id": "Serena", "name": "Serena", "lang": "en", "gender": "female"},
    {"id": "Vivian", "name": "Vivian", "lang": "en", "gender": "female"},
    {"id": "Aiden", "name": "Aiden", "lang": "en", "gender": "male"},
    {"id": "Ono_Anna", "name": "Ono Anna", "lang": "ja", "gender": "female"},
    {"id": "Sohee", "name": "Sohee", "lang": "ko", "gender": "female"},
    {"id": "Uncle_Fu", "name": "Uncle Fu", "lang": "zh", "gender": "male"},
    {"id": "Dylan", "name": "Dylan", "lang": "zh", "gender": "male"},
    {"id": "Eric", "name": "Eric", "lang": "zh", "gender": "male"},
]


class QwenTTSProvider(TTSProvider):
    id = "qwen"
    name = "Qwen3 TTS"
    kind = "local"
    description = "Qwen3-TTS 1.7B · Alta expressividade em GPU (~3.4 GB)"

    def models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": _MODEL_ID,
                "name": "Qwen3-TTS 1.7B",
                "description": self.description,
                "size_mb": 3400,
            }
        ]

    def _has_hf_cache(self) -> bool:
        if importlib.util.find_spec("qwen_tts") is None:
            return False
        hf_dir = (
            Path.home()
            / ".cache"
            / "huggingface"
            / "hub"
            / "models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice"
        )
        return hf_dir.is_dir() and any(hf_dir.iterdir())

    def is_available(self, model_id: str | None = None) -> bool:
        if model_id and model_id != _MODEL_ID:
            return False
        return is_manifest_installed(self.id, _MODEL_ID) or self._has_hf_cache()

    def capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "install": True,
            "uninstall": True,
            "formats": ["wav", "mp3", "opus", "aac", "flac", "pcm"],
            "speed": {
                "supported": True,
                "min": 0.5,
                "max": 2.0,
                "step": 0.05,
                "default": 1.0,
            },
        }

    def list_voices(self, model_id: str | None = None) -> list[dict[str, Any]]:
        if model_id and model_id != _MODEL_ID:
            return []
        try:
            from src.TTSManager import TTSManager

            raw = TTSManager().qwen_voices()
            return [
                {
                    "id": vid,
                    "name": info.get("name", vid),
                    "lang": "multi",
                    "gender": info.get("gender", "unknown"),
                }
                for vid, info in raw.items()
            ]
        except Exception:
            return list(_QWEN_VOICES)

    def install(
        self,
        model_id: str | None = None,
        *,
        job_id: str,
        progress_cb=None,
        cancel_event=None,
    ):
        mid = model_id or _MODEL_ID
        if mid != _MODEL_ID:
            raise ValueError(f"Modelo Qwen desconhecido: {mid}")
        if importlib.util.find_spec("qwen_tts") is None:
            raise RuntimeError("Pacote qwen-tts não está instalado neste ambiente.")
        artifacts = [
            {
                "filename": "config.json",
                "url": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/resolve/main/config.json",
                "size_bytes": 4096,
            }
        ]
        return install_artifacts(
            self.id,
            mid,
            artifacts,
            job_id=job_id,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def uninstall(self, model_id: str | None = None) -> bool:
        mid = model_id or _MODEL_ID
        if mid != _MODEL_ID:
            raise ValueError(f"Modelo Qwen desconhecido: {mid}")
        self.unload(mid)
        return uninstall_artifacts(self.id, mid)

    def unload(self, model_id: str | None = None) -> None:
        try:
            from src.TTSManager import TTSManager

            tm = TTSManager()
            if hasattr(tm, "unload_qwen"):
                tm.unload_qwen()
        except Exception:
            pass

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
        from src.TTSManager import TTSManager

        fmt = (response_format or "wav").lower().strip()
        if fmt not in MIME_BY_FORMAT:
            fmt = "wav"
        tm = TTSManager()
        data = tm.generate(
            text=text,
            voice=voice or "Ryan",
            speed=float(speed),
            style=style,
            device=device,
            output_format=fmt,
        )
        return AudioResult(
            audio=data,
            mime=MIME_BY_FORMAT.get(fmt, "audio/wav"),
            format=fmt,
        )

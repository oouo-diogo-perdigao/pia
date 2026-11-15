"""Provider local Piper TTS (ONNX)."""

from __future__ import annotations

import logging
from typing import Any

from .base import AudioResult, TTSProvider
from .local_catalog import (
    install_artifacts,
    is_manifest_installed,
    uninstall_artifacts,
)

logger = logging.getLogger(__name__)

_MODEL_ID = "pt_BR-faber-medium"
_PIPER_VOICES = [
    {
        "id": "pt_BR-faber-medium",
        "name": "Faber (PT-BR)",
        "lang": "pt-BR",
        "gender": "male",
    }
]
_ARTIFACTS = [
    {
        "filename": "pt_BR-faber-medium.onnx",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        "size_bytes": 63_200_000,
    },
    {
        "filename": "pt_BR-faber-medium.onnx.json",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
        "size_bytes": 4_900,
    },
]


class PiperProvider(TTSProvider):
    id = "piper"
    name = "Piper TTS"
    kind = "local"
    description = "Piper ONNX · Síntese ultraleve em CPU (~63 MB)"

    def models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": _MODEL_ID,
                "name": "Piper PT-BR (Faber)",
                "description": self.description,
                "size_mb": 63,
            }
        ]

    def is_available(self, model_id: str | None = None) -> bool:
        if model_id and model_id != _MODEL_ID:
            return False
        return is_manifest_installed(self.id, _MODEL_ID)

    def capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "install": True,
            "uninstall": True,
            "formats": ["wav"],
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
        return list(_PIPER_VOICES)

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
            raise ValueError(f"Modelo Piper desconhecido: {mid}")
        return install_artifacts(
            self.id,
            mid,
            _ARTIFACTS,
            job_id=job_id,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def uninstall(self, model_id: str | None = None) -> bool:
        mid = model_id or _MODEL_ID
        if mid != _MODEL_ID:
            raise ValueError(f"Modelo Piper desconhecido: {mid}")
        return uninstall_artifacts(self.id, mid)

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
        if not self.is_available(model):
            raise RuntimeError("Piper TTS não está instalado localmente.")
        raise RuntimeError("Motor Piper não carregado neste ambiente.")

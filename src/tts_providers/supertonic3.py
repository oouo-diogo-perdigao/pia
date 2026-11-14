"""Provider local Supertonic 3 (ONNX)."""

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

_MODEL_ID = "supertonic-3"
_SUPERTONIC_VOICES = [
    {"id": "M1", "name": "Masculino 1 (M1)", "lang": "multi", "gender": "male"},
    {"id": "M2", "name": "Masculino 2 (M2)", "lang": "multi", "gender": "male"},
    {"id": "F1", "name": "Feminino 1 (F1)", "lang": "multi", "gender": "female"},
    {"id": "F2", "name": "Feminino 2 (F2)", "lang": "multi", "gender": "female"},
]
_ARTIFACTS = [
    {
        "filename": "tts.json",
        "url": "https://huggingface.co/Supertone/supertonic/resolve/main/onnx/tts.json",
        "size_bytes": 16_384,
    }
]


class Supertonic3Provider(TTSProvider):
    id = "supertonic3"
    name = "Supertonic 3 (local)"
    kind = "local"
    description = "Supertonic ONNX · Síntese neural ultrarrápida offline"

    def models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": _MODEL_ID,
                "name": "Supertonic 3",
                "description": self.description,
                "size_mb": 260,
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
        return list(_SUPERTONIC_VOICES)

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
            raise ValueError(f"Modelo Supertonic desconhecido: {mid}")
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
            raise ValueError(f"Modelo Supertonic desconhecido: {mid}")
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
            raise RuntimeError("Supertonic 3 não está instalado localmente.")
        raise RuntimeError(
            "Runtime Supertonic 3 ONNX não carregado para síntese direta neste ambiente."
        )

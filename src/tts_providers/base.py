"""Abstração de providers de TTS para o seletor de voz e serviço central da PIA."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


MIME_BY_FORMAT = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "pcm": "audio/pcm",
}


@dataclass(frozen=True)
class AudioResult:
    """Resultado de síntese com bytes e MIME real do áudio gerado."""

    audio: bytes
    mime: str
    format: str
    sample_rate: int | None = None
    duration_ms: int | None = None


class TTSProvider(ABC):
    id: str = ""
    name: str = ""
    kind: str = "remote"  # "local" | "remote"
    description: str = ""

    def models(self) -> list[dict[str, Any]]:
        """Lista modelos/variantes suportados pelo provider."""
        return [
            {
                "id": self.id or self.name,
                "name": self.name or self.id,
                "description": self.description,
                "size_mb": None,
            }
        ]

    def default_model(self) -> str:
        items = self.models()
        return items[0]["id"] if items else (self.id or "")

    def capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "install": self.kind == "local",
            "uninstall": self.kind == "local",
            "formats": ["wav", "mp3"],
            "speed": {
                "supported": True,
                "min": 0.5,
                "max": 2.0,
                "step": 0.05,
                "default": 1.0,
            },
        }

    def installation_status(self, model_id: str | None = None) -> dict[str, Any]:
        if self.kind == "remote":
            return {"state": "not_applicable", "job_id": None, "error": None}
        return {
            "state": "installed" if self.is_available(model_id) else "not_installed",
            "job_id": None,
            "error": None,
        }

    def credential_state(self) -> str:
        return "not_required"

    def unload(self, model_id: str | None = None) -> None:
        """Descarrega modelo local da memória, se aplicável."""
        return None

    @abstractmethod
    def is_available(self, model_id: str | None = None) -> bool: ...

    @abstractmethod
    def list_voices(self, model_id: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
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
    ) -> AudioResult | bytes: ...

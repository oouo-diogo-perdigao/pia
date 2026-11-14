"""Abstração de providers de TTS para o seletor de voz da PIA."""
from abc import ABC, abstractmethod


class TTSProvider(ABC):
    name: str = ""
    kind: str = "remote"  # "local" | "remote"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def list_voices(self) -> list[dict]:
        ...

    @abstractmethod
    def synthesize(self, text: str, voice: str, speed: float, response_format: str) -> bytes:
        ...

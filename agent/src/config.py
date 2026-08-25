from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE)


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    memory_file: Path = ROOT_DIR / "data" / "memory.json"
    learning_dir: Path = ROOT_DIR / "learning_requests"
    log_dir: Path = ROOT_DIR / "logs"

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_stt_model: str = os.getenv(
        "GEMINI_STT_MODEL",
        "gemini-3.5-flash-lite",
    ).strip()
    gemini_agent_model: str = os.getenv(
        "GEMINI_AGENT_MODEL",
        "gemini-3.5-flash-lite",
    ).strip()

    user_name: str = os.getenv("USER_NAME", "Diogo").strip() or "Diogo"
    default_location: str = os.getenv(
        "DEFAULT_LOCATION",
        "Belo Horizonte, Minas Gerais, Brasil",
    ).strip()

    max_recording_seconds: float = float(os.getenv("MAX_RECORDING_SECONDS", "60"))

    vscode_command: str = os.getenv("VSCODE_COMMAND", "code").strip() or "code"

    sample_rate: int = 16_000
    channels: int = 1

    def validate(self) -> None:
        if not self.gemini_api_key or self.gemini_api_key == "COLE_SUA_CHAVE_AQUI":
            raise RuntimeError(
                "GEMINI_API_KEY não configurada. Copie .env.example para .env e informe a chave."
            )


settings = Settings()

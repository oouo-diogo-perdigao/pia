"""Provider local Kokoro ONNX."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .base import AudioResult, MIME_BY_FORMAT, TTSProvider
from .local_catalog import (
    install_artifacts,
    is_manifest_installed,
    model_dir,
    uninstall_artifacts,
)

logger = logging.getLogger(__name__)

_MODEL_ID = "kokoro-v1.0"
_ARTIFACTS = [
    {
        "filename": "kokoro-v1.0.onnx",
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx",
        "size_bytes": 325_505_369,
    },
    {
        "filename": "voices-v1.0.bin",
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin",
        "size_bytes": 28_214_398,
    },
]

_KOKORO_VOICES = [
    {"id": "pm_santa", "name": "Santa", "lang": "pt-BR", "gender": "male"},
    {"id": "pm_alex", "name": "Alex", "lang": "pt-BR", "gender": "male"},
    {"id": "pf_dora", "name": "Dora", "lang": "pt-BR", "gender": "female"},
]


class KokoroProvider(TTSProvider):
    id = "kokoro"
    name = "Kokoro ONNX"
    kind = "local"
    description = "Kokoro v1.0 · Leve e rápido em CPU/GPU (~350 MB)"

    def models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": _MODEL_ID,
                "name": "Kokoro v1.0",
                "description": self.description,
                "size_mb": 353,
            }
        ]

    @staticmethod
    def _has_kokoro_files(directory: Path) -> bool:
        onnx = directory / "kokoro-v1.0.onnx"
        voices = directory / "voices-v1.0.bin"
        try:
            return (
                onnx.is_file()
                and onnx.stat().st_size > 0
                and voices.is_file()
                and voices.stat().st_size > 0
            )
        except OSError:
            return False

    def _custom_or_cache_dir(self) -> Path | None:
        candidates: list[Path] = []
        try:
            from src import settings_store

            custom = settings_store.get("TTS_KOKORO_MODEL", "", section="general")
            if isinstance(custom, str) and custom.strip():
                p = Path(custom.strip()).expanduser()
                candidates.extend([p, p / "kokoro"])
        except Exception:
            pass
        env_custom = os.environ.get("TTS_KOKORO_MODEL", "").strip()
        if env_custom:
            p = Path(env_custom).expanduser()
            candidates.extend([p, p / "kokoro"])
        try:
            from src.config import TTS_KOKORO_MODEL

            if TTS_KOKORO_MODEL:
                candidates.append(Path(TTS_KOKORO_MODEL))
        except Exception:
            pass
        try:
            from src import cache_paths

            tts_dir = getattr(cache_paths, "TTS_CACHE_DIR", None)
            if tts_dir:
                candidates.extend([Path(tts_dir), Path(tts_dir) / "kokoro"])
            candidates.extend(
                [
                    cache_paths.CACHE / "main/tts/kokoro",
                    cache_paths.CACHE / "Kokoro-82M",
                ]
            )
        except Exception:
            pass
        seen: set[Path] = set()
        for cand in candidates:
            try:
                resolved = cand.resolve()
            except OSError:
                resolved = cand
            if resolved in seen:
                continue
            seen.add(resolved)
            if self._has_kokoro_files(cand):
                return cand
        return None

    def is_available(self, model_id: str | None = None) -> bool:
        if model_id and model_id != _MODEL_ID:
            return False
        if is_manifest_installed(self.id, _MODEL_ID):
            return True
        return self._custom_or_cache_dir() is not None

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
                "default": 0.95,
            },
        }

    def list_voices(self, model_id: str | None = None) -> list[dict[str, Any]]:
        if model_id and model_id != _MODEL_ID:
            return []
        try:
            from src.TTSManager import TTSManager

            raw = TTSManager().kokoro_voices()
            return [
                {
                    "id": vid,
                    "name": info.get("name", vid),
                    "lang": "pt-BR",
                    "gender": info.get("gender", "unknown"),
                }
                for vid, info in raw.items()
            ]
        except Exception:
            return list(_KOKORO_VOICES)

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
            raise ValueError(f"Modelo Kokoro desconhecido: {mid}")
        existing = self._custom_or_cache_dir()
        if existing is not None:
            total = (existing / "kokoro-v1.0.onnx").stat().st_size + (
                existing / "voices-v1.0.bin"
            ).stat().st_size
            if progress_cb is not None:
                progress_cb(total, total)
            return {
                "schema_version": 1,
                "provider": self.id,
                "model": mid,
                "files": ["kokoro-v1.0.onnx", "voices-v1.0.bin"],
                "bytes": total,
                "source_dir": str(existing),
            }
        manifest = install_artifacts(
            self.id,
            mid,
            _ARTIFACTS,
            job_id=job_id,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        return manifest

    def uninstall(self, model_id: str | None = None) -> bool:
        mid = model_id or _MODEL_ID
        if mid != _MODEL_ID:
            raise ValueError(f"Modelo Kokoro desconhecido: {mid}")
        self.unload(mid)
        removed = uninstall_artifacts(self.id, mid)
        existing = self._custom_or_cache_dir()
        if existing is not None:
            for fname in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
                fpath = existing / fname
                if fpath.is_file() and not fpath.is_symlink():
                    fpath.unlink(missing_ok=True)
                    removed = True
        return removed

    def unload(self, model_id: str | None = None) -> None:
        try:
            from src.TTSManager import TTSManager

            tm = TTSManager()
            if hasattr(tm, "unload_kokoro"):
                tm.unload_kokoro()
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
        # Se instalado via gerenciador local e TTS_KOKORO_MODEL não foi definido, apontar temporariamente
        managed = model_dir(self.id, _MODEL_ID)
        if is_manifest_installed(self.id, _MODEL_ID) and hasattr(
            tm, "kokoro_model_dir"
        ):
            tm.kokoro_model_dir = str(managed)
        data = tm.generate(
            text=text,
            voice=voice or "pm_santa",
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

"""Registry que descobre providers de TTS locais e remotos."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_CLASSES = [
    ("kokoro", "src.tts_providers.kokoro", "KokoroProvider"),
    ("qwen", "src.tts_providers.qwen", "QwenTTSProvider"),
    ("supertonic3", "src.tts_providers.supertonic3", "Supertonic3Provider"),
    ("piper", "src.tts_providers.piper", "PiperProvider"),
    ("openai", "src.tts_providers.openai_tts", "OpenAITTSProvider"),
    ("elevenlabs", "src.tts_providers.elevenlabs", "ElevenLabsProvider"),
]


class TTSProviderRegistry:
    def __init__(self):
        self._providers: dict[str, TTSProvider] = {}
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

    def catalog(
        self, active_jobs: dict[tuple[str, str], str | dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Retorna descritores completos de todos os providers (locais e remotos)."""
        jobs = active_jobs or {}
        result: list[dict[str, Any]] = []
        for key, prov in self._providers.items():
            kind = getattr(prov, "kind", "remote")
            cred_state = (
                prov.credential_state()
                if hasattr(prov, "credential_state")
                else "not_required"
            )
            models_out: list[dict[str, Any]] = []
            provider_error: str | None = None
            raw_models = (
                prov.models()
                if hasattr(prov, "models")
                else [{"id": key, "name": getattr(prov, "name", key)}]
            )
            for m in raw_models:
                mid = m["id"]
                try:
                    avail = bool(prov.is_available(mid))
                except Exception as exc:
                    avail = False
                    provider_error = str(exc)
                job_entry = jobs.get((key, mid))
                if isinstance(job_entry, dict):
                    job_id = job_entry.get("job_id")
                    inst_state = {
                        "state": "installing",
                        "job_id": job_id,
                        "phase": job_entry.get("phase"),
                        "progress": job_entry.get("progress"),
                        "error": None,
                    }
                elif job_entry:
                    job_id = job_entry
                    inst_state = {
                        "state": "installing",
                        "job_id": job_id,
                        "error": None,
                    }
                else:
                    job_id = None
                    if hasattr(prov, "installation_status"):
                        inst_state = prov.installation_status(mid)
                    else:
                        inst_state = {
                            "state": "installed" if avail else "not_installed",
                            "job_id": None,
                            "error": None,
                        }
                try:
                    voices = prov.list_voices(mid)
                except Exception as exc:
                    voices = []
                    provider_error = provider_error or str(exc)
                caps = prov.capabilities(mid) if hasattr(prov, "capabilities") else {}
                reason = None
                if not avail:
                    reason = (
                        "credential_missing" if kind == "remote" else "model_missing"
                    )
                models_out.append(
                    {
                        "id": mid,
                        "name": m.get("name", mid),
                        "description": m.get("description", ""),
                        "size_mb": m.get("size_mb"),
                        "installed": bool(avail) if kind == "local" else False,
                        "installing": bool(job_id),
                        "installation": inst_state,
                        "available": avail,
                        "reason": reason,
                        "capabilities": caps,
                        "voices": voices,
                    }
                )
            any_avail = any(m["available"] for m in models_out)
            default_voices = models_out[0]["voices"] if models_out else []
            default_inst = (
                models_out[0]["installation"]
                if models_out
                else {"state": "not_installed", "job_id": None, "error": None}
            )
            result.append(
                {
                    "id": key,
                    "name": getattr(prov, "name", key),
                    "kind": kind,
                    "description": getattr(prov, "description", ""),
                    "available": any_avail,
                    "installed": any_avail if kind == "local" else False,
                    "installing": any(m["installing"] for m in models_out),
                    "installation": default_inst,
                    "credential_state": cred_state,
                    "capabilities": models_out[0]["capabilities"] if models_out else {},
                    "models": models_out,
                    "voices": default_voices,
                    "error": provider_error,
                }
            )
        return result

    def available(self) -> list[dict[str, Any]]:
        """Compatibilidade com contrato anterior."""
        return self.catalog()

    def get(self, key: str) -> TTSProvider | None:
        return self._providers.get(key)

    def keys(self) -> list[str]:
        return list(self._providers.keys())

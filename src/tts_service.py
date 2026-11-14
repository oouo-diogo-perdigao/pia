"""Serviço central de TTS: catálogo, seleção persistida, instalação, preview e síntese."""

from __future__ import annotations

import json
import logging
import math
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from src.tts_providers.base import AudioResult, MIME_BY_FORMAT
from src.tts_providers.registry import TTSProviderRegistry

logger = logging.getLogger(__name__)

DEFAULT_PREVIEW_TEXT = "Olá, eu sou a PIA e esta é a minha voz."
PREVIEW_TTL_SECONDS = 600
MAX_PREVIEW_CHARS = 300


class TTSServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: str = "invalid_profile",
        param: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.param = param
        self.details = details or {}


@dataclass
class TTSJobState:
    job_id: str
    kind: str  # "install" | "uninstall" | "preview"
    provider: str
    model: str
    state: str = "queued"  # queued | running | done | error
    phase: str = "queued"
    completed_bytes: int = 0
    total_bytes: int | None = None
    percent: float | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    cancelled: threading.Event | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "state": self.state,
            "phase": self.phase,
            "progress": {
                "completed_bytes": self.completed_bytes,
                "total_bytes": self.total_bytes,
                "percent": self.percent,
            },
            "provider": self.provider,
            "model": self.model,
            "error": self.error,
            "result": self.result,
        }


def _validate_speed(raw: Any, min_v: float = 0.25, max_v: float = 4.0) -> float:
    if isinstance(raw, bool):
        raise TTSServiceError(
            "speed inválido.", status=400, code="invalid_profile", param="speed"
        )
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise TTSServiceError(
            "speed inválido.", status=400, code="invalid_profile", param="speed"
        ) from None
    if not math.isfinite(val) or not (min_v <= val <= max_v):
        raise TTSServiceError(
            f"speed deve estar entre {min_v} e {max_v}.",
            status=400,
            code="invalid_profile",
            param="speed",
        )
    return round(val, 4)


class TTSService:
    def __init__(self, registry: TTSProviderRegistry | None = None):
        self.registry = registry or TTSProviderRegistry()
        self._lock = threading.RLock()
        self._jobs: dict[str, TTSJobState] = {}
        self._request_jobs: dict[str, str] = {}
        self._active_model_jobs: dict[tuple[str, str], str] = {}
        self._previews: dict[str, tuple[float, AudioResult]] = {}

    def _current_revision(self) -> int:
        from src import settings_store

        doc = settings_store.document("tts/general_meta", {"revision": 1})
        try:
            return int((doc or {}).get("revision", 1))
        except Exception:
            return 1

    def _migrate_legacy_profile(
        self, provider: str, model: str, voice: str
    ) -> tuple[str, str, str, list[str]]:
        warnings: list[str] = []
        if provider == "supertonic3":
            if voice in ("pm_santa", "pm_alex", "pf_dora"):
                warnings.append(
                    f"Perfil legado supertonic3/{voice} mapeado para kokoro/{voice}."
                )
                return "kokoro", "kokoro-v1.0", voice, warnings
            if voice in (
                "Ryan",
                "Serena",
                "Vivian",
                "Aiden",
                "Ono_Anna",
                "Sohee",
                "Uncle_Fu",
                "Dylan",
                "Eric",
            ):
                warnings.append(
                    f"Perfil legado supertonic3/{voice} mapeado para qwen/{voice}."
                )
                return "qwen", "qwen3-tts-1.7b", voice, warnings
        return provider, model, voice, warnings

    def _read_general_profile(self) -> tuple[dict[str, Any], int, list[str]]:
        from src import settings_store

        provider = str(
            settings_store.get("TTS_PROVIDER", "kokoro", section="general") or "kokoro"
        ).strip()
        model = str(
            settings_store.get("TTS_MODEL", "", section="general") or ""
        ).strip()
        voice = str(
            settings_store.get("TTS_DEFAULT_VOICE", "pm_santa", section="general")
            or "pm_santa"
        ).strip()
        raw_speed = settings_store.get("TTS_DEFAULT_SPEED", "0.95", section="general")
        try:
            speed = _validate_speed(raw_speed)
        except TTSServiceError:
            speed = 0.95

        provider, model, voice, warnings = self._migrate_legacy_profile(
            provider, model, voice
        )
        prov = self.registry.get(provider)
        if prov is None:
            provider = "kokoro"
            prov = self.registry.get("kokoro")
        if prov is not None and not model:
            model = prov.default_model()

        profile = {
            "provider": provider,
            "model": model,
            "voice": voice,
            "speed": speed,
        }
        return profile, self._current_revision(), warnings

    def selection(self) -> dict[str, Any]:
        profile, rev, warnings = self._read_general_profile()
        prov = self.registry.get(profile["provider"])
        avail = bool(prov and prov.is_available(profile["model"]))
        reason = None
        if not avail and prov is not None:
            reason = "credential_missing" if prov.kind == "remote" else "model_missing"
        return {
            "revision": rev,
            "profile": profile,
            "effective_profile": profile if avail else None,
            "available": avail,
            "reason": reason,
            "warnings": warnings,
        }

    def catalog(self) -> dict[str, Any]:
        with self._lock:
            active = dict(self._active_model_jobs)
        providers = self.registry.catalog(active_jobs=active)
        profile, rev, warnings = self._read_general_profile()
        return {
            "schema_version": 1,
            "revision": rev,
            "providers": providers,
            "selection": {
                "revision": rev,
                "profile": profile,
            },
            # Compatibilidade com contrato UX/UI anterior
            "selected": profile,
            "warnings": warnings,
        }

    def voices(
        self, provider_id: str, model_id: str | None = None, *, refresh: bool = False
    ) -> dict[str, Any]:
        prov = self.registry.get(provider_id)
        if prov is None:
            raise TTSServiceError(
                "Provider de TTS inválido.",
                status=400,
                code="invalid_profile",
                param="provider",
            )
        mid = model_id or prov.default_model()
        known_models = {m["id"] for m in prov.models()}
        if mid not in known_models:
            raise TTSServiceError(
                "Modelo de TTS inválido.",
                status=400,
                code="invalid_profile",
                param="model",
            )
        try:
            if provider_id == "elevenlabs" and hasattr(prov, "list_voices"):
                voices_list = prov.list_voices(mid, refresh=refresh)
            else:
                voices_list = prov.list_voices(mid)
            return {
                "provider": provider_id,
                "model": mid,
                "voices": voices_list,
                "stale": False,
                "error": None,
            }
        except Exception as exc:
            return {
                "provider": provider_id,
                "model": mid,
                "voices": [],
                "stale": True,
                "error": str(exc),
            }

    def select(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        speed: Any = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        from src import settings_store

        current_profile, current_rev, _ = self._read_general_profile()
        if revision is not None:
            try:
                expected_rev = int(revision)
            except (TypeError, ValueError):
                raise TTSServiceError(
                    "revision inválido.",
                    status=400,
                    code="invalid_profile",
                    param="revision",
                ) from None
            if expected_rev != current_rev:
                raise TTSServiceError(
                    "Conflito de revisão na seleção TTS. Recarregue as configurações.",
                    status=409,
                    code="revision_conflict",
                    param="revision",
                    details={"current_revision": current_rev},
                )

        target_provider = (
            str(provider).strip()
            if provider is not None
            else current_profile["provider"]
        )
        prov = self.registry.get(target_provider)
        if prov is None:
            raise TTSServiceError(
                "Provider de TTS inválido.",
                status=400,
                code="invalid_profile",
                param="provider",
            )

        target_model = (
            str(model).strip()
            if model is not None and str(model).strip()
            else prov.default_model()
        )
        known_models = {m["id"] for m in prov.models()}
        if target_model not in known_models:
            raise TTSServiceError(
                "Modelo de TTS inválido.",
                status=400,
                code="invalid_profile",
                param="model",
            )

        caps = prov.capabilities(target_model)
        speed_caps = caps.get("speed") or {}
        min_s = float(speed_caps.get("min", 0.25))
        max_s = float(speed_caps.get("max", 4.0))
        target_speed = (
            _validate_speed(speed, min_s, max_s)
            if speed is not None
            else current_profile["speed"]
        )

        voices_list = prov.list_voices(target_model)
        valid_voice_ids = {v["id"] for v in voices_list}
        target_voice = (
            str(voice).strip()
            if voice is not None and str(voice).strip()
            else (voices_list[0]["id"] if voices_list else current_profile["voice"])
        )
        if valid_voice_ids and target_voice not in valid_voice_ids:
            raise TTSServiceError(
                f"Voz '{target_voice}' não pertence ao modelo '{target_model}'.",
                status=400,
                code="invalid_profile",
                param="voice",
            )

        with self._lock:
            store = settings_store.get_store()
            with store.connection() as db:
                row = db.execute(
                    "SELECT value FROM documents WHERE name=?", ("tts/general_meta",)
                ).fetchone()
                db_rev = int(json.loads(row[0]).get("revision", 1)) if row else 1
                if revision is not None and int(revision) != db_rev:
                    raise TTSServiceError(
                        "Conflito de revisão na seleção TTS.",
                        status=409,
                        code="revision_conflict",
                        details={"current_revision": db_rev},
                    )
                new_rev = db_rev + 1
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?)",
                    ("tts/general_meta", json.dumps({"revision": new_rev})),
                )
            store.save(
                "general",
                {
                    "TTS_PROVIDER": target_provider,
                    "TTS_MODEL": target_model,
                    "TTS_DEFAULT_VOICE": target_voice,
                    "TTS_DEFAULT_SPEED": str(target_speed),
                },
            )

        new_profile = {
            "provider": target_provider,
            "model": target_model,
            "voice": target_voice,
            "speed": target_speed,
        }
        return {
            "ok": True,
            "revision": new_rev,
            "profile": new_profile,
            # Compatibilidade com contrato anterior
            "provider": target_provider,
            "model": target_model,
            "voice": target_voice,
            "speed": target_speed,
        }

    def _find_model_references(self, provider_id: str, model_id: str) -> list[str]:
        from src import settings_store

        refs: list[str] = []
        general, _, _ = self._read_general_profile()
        if general["provider"] == provider_id and general["model"] == model_id:
            refs.append("pia:general")

        store = settings_store.get_store()
        for key, raw_val in store.rows("documents"):
            if key.startswith("tts/speakers/"):
                try:
                    doc = json.loads(raw_val)
                except Exception:
                    continue
                if doc.get("mode") == "custom" and isinstance(doc.get("profile"), dict):
                    prof = doc["profile"]
                    if (
                        prof.get("provider") == provider_id
                        and prof.get("model") == model_id
                    ):
                        refs.append(key.removeprefix("tts/speakers/"))
        return refs

    def install(
        self,
        provider_id: str,
        model_id: str | None = None,
        *,
        request_id: str | None = None,
        workspace_jobs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prov = self.registry.get(provider_id)
        if prov is None or prov.kind != "local":
            raise TTSServiceError(
                "Apenas providers locais suportam instalação.",
                status=400,
                code="invalid_profile",
                param="provider",
            )
        mid = model_id or prov.default_model()
        if mid not in {m["id"] for m in prov.models()}:
            raise TTSServiceError(
                "Modelo inválido.", status=400, code="invalid_profile", param="model"
            )
        if not hasattr(prov, "install"):
            raise TTSServiceError(
                "Instalação não suportada por este modelo.",
                status=422,
                code="unsupported_platform",
            )

        with self._lock:
            if request_id and request_id in self._request_jobs:
                existing_id = self._request_jobs[request_id]
                return {"job_id": existing_id, "state": self._jobs[existing_id].state}
            if (provider_id, mid) in self._active_model_jobs:
                existing_id = self._active_model_jobs[(provider_id, mid)]
                return {"job_id": existing_id, "state": self._jobs[existing_id].state}

            job_id = secrets.token_hex(12)
            cancel_ev = threading.Event()
            job_state = TTSJobState(
                job_id=job_id,
                kind="install",
                provider=provider_id,
                model=mid,
                state="queued",
                phase="queued",
                cancelled=cancel_ev,
            )
            self._jobs[job_id] = job_state
            self._active_model_jobs[(provider_id, mid)] = job_id
            if request_id:
                self._request_jobs[request_id] = job_id

            ws_job = None
            if workspace_jobs is not None:
                from src.pia.service import Job

                ws_job = Job()
                ws_job.id = job_id
                workspace_jobs[job_id] = ws_job

        def run():
            job_state.state = "running"
            job_state.phase = "downloading"
            if ws_job:
                ws_job.emit("progress", **job_state.snapshot())

            def on_progress(completed: int, total: int | None):
                job_state.completed_bytes = completed
                job_state.total_bytes = total
                job_state.percent = (
                    round((completed / total) * 100.0, 1)
                    if total and total > 0
                    else None
                )
                if ws_job:
                    ws_job.emit("progress", **job_state.snapshot())

            try:
                manifest = prov.install(
                    mid,
                    job_id=job_id,
                    progress_cb=on_progress,
                    cancel_event=cancel_ev,
                )
                job_state.state = "done"
                job_state.phase = "installed"
                job_state.percent = 100.0
                job_state.result = {"installed": True, "manifest": manifest}
                if ws_job:
                    ws_job.emit("done", **job_state.snapshot())
            except InterruptedError:
                job_state.state = "error"
                job_state.phase = "cancelled"
                job_state.error = {
                    "code": "cancelled",
                    "message": "Instalação cancelada.",
                }
                if ws_job:
                    ws_job.emit(
                        "error", error="Instalação cancelada.", code="cancelled"
                    )
            except Exception as exc:
                job_state.state = "error"
                job_state.phase = "error"
                job_state.error = {"code": "install_failed", "message": str(exc)}
                if ws_job:
                    ws_job.emit("error", error=str(exc), code="install_failed")
            finally:
                with self._lock:
                    if self._active_model_jobs.get((provider_id, mid)) == job_id:
                        self._active_model_jobs.pop((provider_id, mid), None)

        threading.Thread(
            target=run, daemon=True, name=f"tts-install-{provider_id}"
        ).start()
        return {"job_id": job_id, "state": "queued"}

    def uninstall(
        self,
        provider_id: str,
        model_id: str | None = None,
        *,
        request_id: str | None = None,
        workspace_jobs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prov = self.registry.get(provider_id)
        if prov is None or prov.kind != "local":
            raise TTSServiceError(
                "Apenas providers locais suportam desinstalação.",
                status=400,
                code="invalid_profile",
                param="provider",
            )
        mid = model_id or prov.default_model()
        if mid not in {m["id"] for m in prov.models()}:
            raise TTSServiceError(
                "Modelo inválido.", status=400, code="invalid_profile", param="model"
            )

        refs = self._find_model_references(provider_id, mid)
        if refs:
            raise TTSServiceError(
                "Modelo está atualmente em uso e não pode ser desinstalado.",
                status=409,
                code="model_in_use",
                details={"references": refs},
            )

        with self._lock:
            if request_id and request_id in self._request_jobs:
                existing_id = self._request_jobs[request_id]
                return {"job_id": existing_id, "state": self._jobs[existing_id].state}
            if (provider_id, mid) in self._active_model_jobs:
                raise TTSServiceError(
                    "Já existe uma operação em andamento para este modelo.",
                    status=409,
                    code="model_in_use",
                )
            job_id = secrets.token_hex(12)
            job_state = TTSJobState(
                job_id=job_id,
                kind="uninstall",
                provider=provider_id,
                model=mid,
                state="running",
                phase="uninstalling",
            )
            self._jobs[job_id] = job_state
            if request_id:
                self._request_jobs[request_id] = job_id

        removed = bool(hasattr(prov, "uninstall") and prov.uninstall(mid))
        job_state.state = "done"
        job_state.phase = "not_installed"
        job_state.result = {"uninstalled": removed}
        if workspace_jobs is not None:
            from src.pia.service import Job

            ws_job = Job()
            ws_job.id = job_id
            workspace_jobs[job_id] = ws_job
            ws_job.emit("done", **job_state.snapshot())
        return {"job_id": job_id, "state": "done", "uninstalled": removed}

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise TTSServiceError("Job não encontrado.", status=404, code="not_found")
        return job.snapshot()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise TTSServiceError("Job não encontrado.", status=404, code="not_found")
        if job.cancelled is not None:
            job.cancelled.set()
        snap = job.snapshot()
        snap["cancel_requested"] = True
        return snap

    def _prune_previews(self) -> None:
        cutoff = time.time() - PREVIEW_TTL_SECONDS
        with self._lock:
            for jid in [k for k, (ts, _) in self._previews.items() if ts < cutoff]:
                self._previews.pop(jid, None)

    def preview(
        self,
        profile: dict[str, Any] | None = None,
        text: str | None = None,
        *,
        workspace_jobs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._prune_previews()
        msg = (text or DEFAULT_PREVIEW_TEXT).strip()
        if not msg:
            msg = DEFAULT_PREVIEW_TEXT
        if len(msg) > MAX_PREVIEW_CHARS:
            raise TTSServiceError(
                f"Texto de prévia excede {MAX_PREVIEW_CHARS} caracteres.",
                status=400,
                code="invalid_profile",
                param="text",
            )
        resolved = self.resolve_profile("pia", override=profile)
        job_id = secrets.token_hex(12)
        job_state = TTSJobState(
            job_id=job_id,
            kind="preview",
            provider=resolved["provider"],
            model=resolved["model"],
            state="queued",
            phase="synthesizing",
        )
        with self._lock:
            self._jobs[job_id] = job_state

        ws_job = None
        if workspace_jobs is not None:
            from src.pia.service import Job

            ws_job = Job()
            ws_job.id = job_id
            workspace_jobs[job_id] = ws_job

        def run():
            job_state.state = "running"
            try:
                res = self.synthesize(msg, profile=resolved, response_format="wav")
                with self._lock:
                    self._previews[job_id] = (time.time(), res)
                job_state.state = "done"
                job_state.phase = "done"
                job_state.result = {
                    "audio_url": f"/api/pia/tts/previews/{job_id}/audio",
                    "mime": res.mime,
                    "format": res.format,
                }
                if ws_job:
                    ws_job.emit("done", **job_state.snapshot())
            except Exception as exc:
                job_state.state = "error"
                job_state.phase = "error"
                job_state.error = {"code": "provider_unavailable", "message": str(exc)}
                if ws_job:
                    ws_job.emit("error", error=str(exc), code="provider_unavailable")

        threading.Thread(target=run, daemon=True, name="tts-preview").start()
        return {"job_id": job_id, "state": "queued"}

    def get_preview_audio(self, job_id: str) -> AudioResult:
        self._prune_previews()
        with self._lock:
            entry = self._previews.get(job_id)
        if not entry:
            raise TTSServiceError(
                "Prévia não encontrada ou expirada.", status=404, code="not_found"
            )
        return entry[1]

    def resolve_profile(
        self, speaker_id: str = "pia", override: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        general, _, _ = self._read_general_profile()
        base = dict(general)
        if speaker_id and speaker_id != "pia":
            from src import settings_store

            doc = settings_store.document(f"tts/speakers/{speaker_id}")
            if isinstance(doc, dict) and doc.get("mode") == "custom":
                prof = doc.get("profile")
                if isinstance(prof, dict) and prof.get("provider"):
                    base.update(
                        {
                            "provider": str(prof["provider"]),
                            "model": str(prof.get("model") or ""),
                            "voice": str(prof.get("voice") or base["voice"]),
                            "speed": _validate_speed(prof.get("speed", base["speed"])),
                        }
                    )
        if override and isinstance(override, dict):
            if override.get("provider"):
                base["provider"] = str(override["provider"]).strip()
            if override.get("model"):
                base["model"] = str(override["model"]).strip()
            if override.get("voice"):
                base["voice"] = str(override["voice"]).strip()
            if override.get("speed") is not None:
                base["speed"] = _validate_speed(override["speed"])

        prov = self.registry.get(base["provider"])
        if prov is None:
            raise TTSServiceError(
                f"Provider de TTS desconhecido: {base['provider']}",
                status=400,
                code="invalid_profile",
                param="provider",
            )
        if not base.get("model"):
            base["model"] = prov.default_model()
        return base

    def synthesize(
        self,
        text: str,
        *,
        profile: dict[str, Any] | None = None,
        response_format: str = "wav",
        speaker_id: str = "pia",
        style: str | None = None,
        device: str | None = None,
    ) -> AudioResult:
        prof = profile or self.resolve_profile(speaker_id)
        prov = self.registry.get(prof["provider"])
        if prov is None:
            raise TTSServiceError(
                "Provider indisponível.", status=503, code="provider_unavailable"
            )
        try:
            raw = prov.synthesize(
                text,
                prof["voice"],
                float(prof["speed"]),
                response_format,
                model=prof["model"],
                style=style,
                device=device,
            )
            if isinstance(raw, AudioResult):
                return raw
            fmt = (response_format or "wav").lower().strip()
            return AudioResult(
                audio=raw, mime=MIME_BY_FORMAT.get(fmt, "audio/wav"), format=fmt
            )
        except Exception as exc:
            # Fallback seguro apenas de remoto para local instalado; nunca envia local para remoto
            if prov.kind == "remote":
                for local_id in ("kokoro", "qwen", "piper"):
                    local_prov = self.registry.get(local_id)
                    if local_prov is not None and local_prov.is_available():
                        voices = local_prov.list_voices()
                        fallback_voice = voices[0]["id"] if voices else "pm_santa"
                        logger.warning(
                            "Provider remoto %s falhou (%s); fallback local para %s/%s.",
                            prof["provider"],
                            exc,
                            local_id,
                            fallback_voice,
                        )
                        raw = local_prov.synthesize(
                            text,
                            fallback_voice,
                            float(prof["speed"]),
                            response_format,
                            model=local_prov.default_model(),
                            style=style,
                            device=device,
                        )
                        if isinstance(raw, AudioResult):
                            return raw
                        fmt = (response_format or "wav").lower().strip()
                        return AudioResult(
                            audio=raw,
                            mime=MIME_BY_FORMAT.get(fmt, "audio/wav"),
                            format=fmt,
                        )
            raise TTSServiceError(
                f"Falha na síntese TTS: {exc}",
                status=503,
                code="provider_unavailable",
            ) from exc

    def speak(
        self,
        text: str,
        *,
        speaker_id: str = "pia",
        conversation_epoch: Any = None,
        cancelled: Any = None,
        speed: Any = None,
        voice: str | None = None,
        style: str | None = None,
        device: str | None = None,
        bot_name: str | None = None,
        avatar_url: str | None = None,
        avatar_colors: dict[str, str] | None = None,
    ) -> None:
        from src.TTSManager import TTSManager
        from src.voice_interrupt import EpochCancellation, epoch

        override: dict[str, Any] = {}
        if speed is not None:
            override["speed"] = speed
        if voice is not None:
            override["voice"] = voice
        prof = self.resolve_profile(speaker_id, override=override or None)
        tm = TTSManager()

        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        utterance_id = secrets.token_hex(8)
        for idx, part in enumerate(parts, start=1):
            if conversation_epoch is not None and conversation_epoch != epoch():
                break
            part_cancel = cancelled or (
                EpochCancellation(conversation_epoch)
                if conversation_epoch is not None
                else None
            )
            prov = self.registry.get(prof["provider"])
            if prov is not None and prov.kind == "remote":
                res = self.synthesize(
                    part,
                    profile=prof,
                    response_format="wav",
                    speaker_id=speaker_id,
                    style=style,
                    device=device,
                )
                tm.add_audio_job(
                    jobName=f" ({idx} de {len(parts)}) {part[:30]}",
                    wav_bytes=res.audio,
                    device=device,
                    cancelled=part_cancel,
                )
            else:
                tm.add_tts_job(
                    text=part,
                    voice=prof["voice"],
                    speed=float(prof["speed"]),
                    style=style,
                    device=device,
                    job_name=f" ({idx} de {len(parts)}) {part[:30]}",
                    cancelled=part_cancel,
                )
        _ = utterance_id, bot_name, avatar_url, avatar_colors


_tts_service: TTSService | None = None
_tts_service_lock = threading.Lock()


def get_tts_service() -> TTSService:
    global _tts_service
    with _tts_service_lock:
        if _tts_service is None:
            _tts_service = TTSService()
        return _tts_service

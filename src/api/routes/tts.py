"""TTS routes for /api/pia/tts/* and /api/pia/speakers/*."""

from __future__ import annotations

from src.voice.tts.engine import TTSManager
from src.voice.tts.service import get_tts_service


def _providers(ctx, data, query):
    return get_tts_service().catalog()


def _voices(ctx, data, query):
    provider_id = (query.get("provider") or [""])[0].strip()
    model_id = (query.get("model") or [None])[0]
    refresh = (query.get("refresh") or [""])[0].lower() in ("1", "true", "yes")
    return get_tts_service().voices(provider_id, model_id=model_id, refresh=refresh)


def _selection(ctx, data, query):
    return get_tts_service().selection()


def _select(ctx, data, query):
    return get_tts_service().select(
        provider=data.get("provider"),
        model=data.get("model"),
        voice=data.get("voice"),
        speed=data.get("speed"),
        revision=data.get("revision"),
    )


def _install(ctx, data, query):
    return get_tts_service().install(
        str(data.get("provider") or ""),
        data.get("model"),
        request_id=data.get("request_id"),
        workspace_jobs=ctx.jobs,
    )


def _uninstall(ctx, data, query):
    return get_tts_service().uninstall(
        str(data.get("provider") or ""),
        data.get("model"),
        request_id=data.get("request_id"),
        workspace_jobs=ctx.jobs,
    )


def _get_job(ctx, data, query, job_id):
    return get_tts_service().get_job(job_id)


def _cancel_job(ctx, data, query, job_id):
    return get_tts_service().cancel_job(job_id)


def _preview(ctx, data, query):
    return get_tts_service().preview(
        profile=data.get("profile"),
        text=data.get("text"),
        workspace_jobs=ctx.jobs,
    )


def _stop(ctx, data, query):
    if hasattr(ctx.backend, "voice_stop"):
        ctx.backend.voice_stop.set()
    TTSManager().stop()
    return {"ok": True}


def _speaker_voice_get(ctx, data, query, speaker_id):
    return get_tts_service().get_speaker_voice(speaker_id)


def _speaker_voice_set(ctx, data, query, speaker_id):
    return get_tts_service().set_speaker_voice(
        speaker_id,
        mode=str(data.get("mode") or "inherit"),
        profile=data.get("profile"),
        revision=data.get("revision"),
    )


def register(router) -> None:
    router.add("GET", "/tts/providers", _providers, description="Listar provedores TTS")
    router.add("GET", "/tts/voices", _voices, description="Listar vozes TTS")
    router.add("GET", "/tts/selection", _selection, description="Obter seleção TTS")
    router.add(
        "POST", "/tts/select", _select, description="Selecionar voz/provedor TTS"
    )
    router.add("POST", "/tts/install", _install, description="Instalar modelo TTS")
    router.add(
        "POST", "/tts/uninstall", _uninstall, description="Desinstalar modelo TTS"
    )
    router.add("GET", "/tts/jobs/{job_id}", _get_job, description="Consultar job TTS")
    router.add(
        "POST", "/tts/jobs/{job_id}/cancel", _cancel_job, description="Cancelar job TTS"
    )
    router.add(
        "POST", "/tts/preview", _preview, description="Gerar preview de áudio TTS"
    )
    router.add("POST", "/tts/stop", _stop, description="Interromper fala TTS")
    router.add(
        "GET",
        "/speakers/{speaker_id}/voice",
        _speaker_voice_get,
        description="Obter voz do speaker",
    )
    router.add(
        "PUT",
        "/speakers/{speaker_id}/voice",
        _speaker_voice_set,
        description="Definir voz do speaker",
    )
    router.add(
        "POST",
        "/speakers/{speaker_id}/voice",
        _speaker_voice_set,
        description="Definir voz do speaker",
    )

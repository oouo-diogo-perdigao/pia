"""E2e T8 do Suno: web_api.handle + mock MCP. Sem chamada paga. Sem skipif."""

from __future__ import annotations

import threading

import pytest

from Plugins.Apps.music import service
from Plugins.Apps.music import web_api
from tests._suno_e2e_support import (
    JOB_WAIT,
    SUNO,
    TIMEOUT_DELAY,
    TIMEOUT_SECONDS,
    Context,
    assert_interrupted,
    assert_no_secrets,
    assert_t3_t4_surface,
    audio_files,
    error_event,
    events,
    isolated_manager,
    patch_music_runtime,
    post_generate_http,
    register_mock,
    run_generate,
)
from tests.fixtures.fake_suno_mcp import DEFAULT_TOKEN, FakeSunoMcpServer


@pytest.fixture(autouse=True)
def _job_hygiene(monkeypatch):
    monkeypatch.setattr(web_api, "_latest", None)
    yield
    for thread in [t for t in threading.enumerate() if t.name == "pia-music"]:
        thread.join(JOB_WAIT)
        assert not thread.is_alive(), "worker thread still running"


@pytest.fixture
def music_env(tmp_path, monkeypatch):
    out = patch_music_runtime(monkeypatch, tmp_path)
    mgr = isolated_manager(tmp_path, monkeypatch)
    return {"out": out, "mgr": mgr, "tmp_path": tmp_path, "monkeypatch": monkeypatch}


def test_t3_t4_behavior_probes():
    assert_t3_t4_surface()


def test_ca05_success_saves_one_track_and_notifies(music_env):
    with FakeSunoMcpServer(scenarios=["success"], leaky=True) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})

        assert job.status == "done"
        assert len(suno.generation_calls()) == 1
        tracks = events(job, "track")
        assert len(tracks) == 1
        item = tracks[0]["item"]
        assert item["provider"] == "suno_mcp"
        assert item["audio_url"].startswith("/api/pia/music/files/")
        assert "127.0.0.1" not in item["audio_url"]
        assert "X-Amz-Signature" not in item.get("audio_url", "")
        audios = audio_files(music_env["out"])
        assert len(audios) == 1
        sidecar = audios[0].with_name(audios[0].name + ".json")
        assert sidecar.is_file()
        assert context.notifications == [
            ("Apps/music", "Músicas prontas", "1 música(s) gerada(s).")
        ]
        assert_no_secrets(job, context, sidecar)


def test_ca06_401_is_auth_error_interrupted(music_env):
    with FakeSunoMcpServer(scenarios=["401"], leaky=True) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})

        assert job.status == "error"
        error, _ = assert_interrupted(
            job,
            completed=0,
            total=1,
            ready=service.tracks_ready_text(0, 1),
        )
        assert error["code"] == "suno_auth"
        assert error["error"] == service.SunoAuthError.default_message
        assert context.notifications == []
        assert len(suno.generation_calls()) == 1
        assert_no_secrets(job, context)
        status = service.suno_status()
        assert status["available"] is False
        assert status["credential_state"] == "expired"


def test_ca06_503_is_unavailable_interrupted(music_env):
    with FakeSunoMcpServer(scenarios=["503"]) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})

        assert job.status == "error"
        error, _ = assert_interrupted(
            job,
            completed=0,
            total=1,
            ready=service.tracks_ready_text(0, 1),
        )
        assert error["code"] == "suno_unavailable"
        assert error["error"] == service.SunoUnavailableError.default_message
        assert context.notifications == []
        assert service.suno_status()["available"] is True


def test_ca06_timeout_is_interrupted(music_env, monkeypatch):
    patch_music_runtime(monkeypatch, music_env["tmp_path"], timeout=TIMEOUT_SECONDS)
    with FakeSunoMcpServer(scenarios=["timeout"], timeout_delay=TIMEOUT_DELAY) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})

        assert job.status == "error"
        error, _ = assert_interrupted(
            job,
            completed=0,
            total=1,
            ready=service.tracks_ready_text(0, 1),
        )
        assert error["code"] == "suno_timeout"
        assert error["error"] == service.SunoTimeoutError.default_message
        assert context.notifications == []


def test_ca07_partial_stops_at_first_failed_clip(music_env):
    """Q8: ["partial","503"] e N=3 → 1 tools/call, 1 faixa, notificação parcial."""
    with FakeSunoMcpServer(scenarios=["partial", "503"], leaky=True) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 3})

        assert job.status == "error"
        assert len(suno.generation_calls()) == 1
        tracks = events(job, "track")
        assert len(tracks) == 1
        assert len(audio_files(music_env["out"])) == 1
        error, _ = assert_interrupted(
            job,
            completed=1,
            total=3,
            ready="1 de 3 músicas prontas",
        )
        assert error["error"] == service.SunoClipFailedError.default_message
        assert "1 de 3" not in error["error"]
        assert context.notifications == [
            (
                "Apps/music",
                "Músicas prontas",
                "1 de 3 músicas prontas (geração interrompida)",
            )
        ]
        assert_no_secrets(job, context, *music_env["out"].glob("*.json"))


def test_incomplete_batch_message_and_ready_text(music_env):
    """Q1: o mock devolve 1 clip; event.error não leva 'k de N'."""
    with FakeSunoMcpServer(scenarios=["success"], clips_per_call=1, leaky=True) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 3})

        assert job.status == "error"
        assert len(suno.generation_calls()) == 1
        assert len(events(job, "track")) == 1
        assert len(audio_files(music_env["out"])) == 1
        error, _ = assert_interrupted(
            job,
            completed=1,
            total=3,
            ready="1 de 3 músicas prontas",
        )
        assert error["code"] == "incomplete_batch"
        assert error["error"] == "O Suno devolveu menos músicas que o esperado."
        assert error["error"] == service.SunoIncompleteBatchError.default_message
        assert "1 de 3" not in error["error"]
        assert context.notifications == [
            (
                "Apps/music",
                "Músicas prontas",
                "1 de 3 músicas prontas (geração interrompida)",
            )
        ]
        assert_no_secrets(job, context, *music_env["out"].glob("*.json"))


def test_ca10_leaky_payloads_stay_redacted(music_env):
    with FakeSunoMcpServer(scenarios=["success"], leaky=True) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})
        catalog = service.providers_catalog()
        assert_no_secrets(
            job,
            context,
            catalog,
            *music_env["out"].glob("*.json"),
            extra=(suno.token or DEFAULT_TOKEN,),
        )


def test_refusal_suno_not_connected_before_job_and_400_json(music_env, monkeypatch):
    isolated_manager(music_env["tmp_path"], monkeypatch)
    monkeypatch.setattr(service, "settings", lambda: {"MUSIC_PROVIDER": "suno_mcp"})
    context = Context()
    with pytest.raises(service.SunoJobRefusedError) as err:
        web_api.handle("generate", {**SUNO, "count": 1}, context)
    assert isinstance(err.value, ValueError)
    assert str(err.value) == service.SUNO_CONNECT_MESSAGE
    assert err.value.code == "suno_not_connected"
    assert context.jobs == {} and web_api._latest is None

    handler, http_context = post_generate_http(monkeypatch, {**SUNO, "count": 1})
    assert handler.status == 400
    assert handler.json() == {
        "error": service.SUNO_CONNECT_MESSAGE,
        "code": "suno_not_connected",
    }
    assert http_context.jobs == {}


def test_refusal_suno_credential_expired_after_401_and_400_json(music_env, monkeypatch):
    with FakeSunoMcpServer(scenarios=["401"]) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})
        assert job.status == "error"
        assert error_event(job)["code"] == "suno_auth"
        assert service.suno_status()["credential_state"] == "expired"

        refused = Context()
        with pytest.raises(service.SunoJobRefusedError) as err:
            web_api.handle("generate", {**SUNO, "count": 2}, refused)
        assert isinstance(err.value, ValueError)
        assert err.value.code == "suno_credential_expired"
        assert str(err.value) == service.SunoAuthError.default_message
        assert refused.jobs == {}
        assert web_api._latest is job

        handler, http_context = post_generate_http(monkeypatch, {**SUNO, "count": 1})
        assert handler.status == 400
        assert handler.json() == {
            "error": service.SunoAuthError.default_message,
            "code": "suno_credential_expired",
        }
        assert http_context.jobs == {}
        assert len(suno.generation_calls()) == 1
        assert_no_secrets(job, context)


def test_download_failed_code(music_env):
    with FakeSunoMcpServer(scenarios=["success"], audio_behavior="500") as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})

        assert job.status == "error"
        error, _ = assert_interrupted(
            job,
            completed=0,
            total=1,
            ready=service.tracks_ready_text(0, 1),
        )
        assert error["code"] == "download_failed"
        assert error["error"] == service.SunoDownloadError.default_message
        assert events(job, "track") == []
        assert audio_files(music_env["out"]) == []
        assert context.notifications == []


def test_suno_no_credits_402(music_env):
    with FakeSunoMcpServer(scenarios=["402"]) as suno:
        register_mock(music_env["mgr"], suno)
        job, context = run_generate({**SUNO, "count": 1})

        assert job.status == "error"
        error, _ = assert_interrupted(
            job,
            completed=0,
            total=1,
            ready=service.tracks_ready_text(0, 1),
        )
        assert error["code"] == "suno_no_credits"
        assert error["error"] == service.SunoNoCreditsError.default_message
        assert context.notifications == []
        assert len(suno.generation_calls()) == 1

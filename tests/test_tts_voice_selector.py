"""Tests for the PIA voice selector, TTS catalog, selection, and workspace routes."""

from __future__ import annotations

import http.client
import json
import logging
import threading
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

from src import config, settings_store
from src.tts_providers.base import AudioResult

_desktop = ModuleType("src.LocalActions")
_desktop.LocalActions = Mock()
with patch.dict("sys.modules", {"src.LocalActions": _desktop}):
    from src import HTTPServer as http_module


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    db_path = tmp_path / "settings.sqlite3"
    store = settings_store.SettingsStore(path=db_path)
    monkeypatch.setattr(settings_store, "_store", store)
    monkeypatch.setattr(
        "src.user_paths.user_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    monkeypatch.setattr(
        "src.tts_providers.local_catalog.user_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    import src.tts_service as ts_mod

    monkeypatch.setattr(ts_mod, "_tts_service", ts_mod.TTSService())
    return store


@pytest.fixture
def api(monkeypatch, isolated_store):
    monkeypatch.setattr(config, "AGE_GEMINI_API_KEY", "test-credential", raising=False)
    monkeypatch.setattr(http_module, "OPENAI_COMPAT_API_KEY", "", raising=False)
    server = http_module.STTThreadingHTTPServer(
        ("127.0.0.1", 0), http_module.HTTPServer
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(payload=None, path="/", method="GET", headers=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            body = json.dumps(payload) if payload is not None else None
            req_headers = dict(headers or {})
            if body is not None:
                req_headers.setdefault("Content-Type", "application/json")
            connection.request(method, path, body=body, headers=req_headers)
            response = connection.getresponse()
            raw = response.read()
            try:
                data = json.loads(raw.decode())
            except Exception:
                data = raw
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    yield request, server.server_address[1]
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_contract_tts_providers(api):
    request, _ = api
    status, data, _ = request(path="/v1/tts/providers", method="GET")
    assert status == 200
    assert "providers" in data
    assert isinstance(data["providers"], list)
    ids = {p["id"] for p in data["providers"]}
    assert {"kokoro", "qwen", "supertonic3", "piper", "openai", "elevenlabs"} <= ids
    for p in data["providers"]:
        assert {
            "id",
            "name",
            "kind",
            "available",
            "voices",
            "models",
            "credential_state",
            "capabilities",
        } <= set(p.keys())
        assert p["kind"] in ("local", "remote")
        assert isinstance(p["models"], list) and len(p["models"]) >= 1


def test_contract_tts_voices_and_selection(api):
    request, _ = api
    status, data, _ = request(
        path="/v1/tts/voices?provider=kokoro&model=kokoro-v1.0", method="GET"
    )
    assert status == 200
    assert data["provider"] == "kokoro"
    assert any(v["id"] == "pf_dora" for v in data["voices"])

    status, sel, _ = request(path="/v1/tts/selection", method="GET")
    assert status == 200
    rev = sel["revision"]

    status, upd, _ = request(
        payload={
            "provider": "kokoro",
            "model": "kokoro-v1.0",
            "voice": "pf_dora",
            "speed": 1.15,
            "revision": rev,
        },
        path="/v1/tts/select",
        method="POST",
    )
    assert status == 200
    assert upd["ok"] is True
    assert upd["profile"]["voice"] == "pf_dora"
    assert upd["profile"]["speed"] == 1.15
    assert upd["revision"] == rev + 1

    # Stale revision returns 409 conflict
    status_conflict, _, _ = request(
        payload={"provider": "kokoro", "voice": "pm_santa", "revision": rev},
        path="/v1/tts/select",
        method="POST",
    )
    assert status_conflict == 409


def test_tts_select_rejects_invalid_speed_and_voice(api):
    request, _ = api
    status, _, _ = request(
        payload={"provider": "kokoro", "voice": "pf_dora", "speed": True},
        path="/v1/tts/select",
        method="POST",
    )
    assert status == 400

    status, _, _ = request(
        payload={"provider": "kokoro", "voice": "nonexistent_voice", "speed": 1.0},
        path="/v1/tts/select",
        method="POST",
    )
    assert status == 400


def test_tts_uninstall_blocked_when_in_use(api):
    request, _ = api
    request(
        payload={"provider": "kokoro", "model": "kokoro-v1.0", "voice": "pm_santa"},
        path="/v1/tts/select",
        method="POST",
    )
    status, data, _ = request(
        payload={"provider": "kokoro", "model": "kokoro-v1.0"},
        path="/v1/tts/uninstall",
        method="POST",
    )
    assert status == 409
    assert data["error"]["code"] == "model_in_use"
    assert "pia:general" in data["error"]["references"]


def test_workspace_tts_routes_require_session_and_work(api):
    request, port = api
    status_unauth, _, _ = request(path="/api/pia/tts/providers", method="GET")
    assert status_unauth == 401

    origin = f"http://127.0.0.1:{port}"
    status_sess, _, headers = request(
        payload={},
        path="/api/pia/session",
        method="POST",
        headers={"Origin": origin},
    )
    assert status_sess == 200
    cookie = headers.get("Set-Cookie") or headers.get("set-cookie")
    session_cookie = cookie.split(";", 1)[0]

    status_cat, cat, _ = request(
        path="/api/pia/tts/providers",
        method="GET",
        headers={"Cookie": session_cookie},
    )
    assert status_cat == 200
    assert "providers" in cat and "selection" in cat

    status_sel, sel_res, _ = request(
        payload={
            "provider": "kokoro",
            "model": "kokoro-v1.0",
            "voice": "pm_alex",
            "speed": 1.25,
        },
        path="/api/pia/tts/select",
        method="POST",
        headers={"Cookie": session_cookie, "Origin": origin},
    )
    assert status_sel == 200
    assert sel_res["profile"]["voice"] == "pm_alex"
    assert sel_res["profile"]["speed"] == 1.25


def test_audio_speech_and_speak_use_tts_service(api, monkeypatch):
    request, _ = api
    from src.tts_service import get_tts_service

    calls = []

    def fake_synth(
        text,
        *,
        profile=None,
        response_format="wav",
        speaker_id="pia",
        style=None,
        device=None,
    ):
        calls.append((text, profile, response_format))
        return AudioResult(audio=b"RIFF....", mime="audio/wav", format="wav")

    monkeypatch.setattr(get_tts_service(), "synthesize", fake_synth)

    request(
        payload={"provider": "kokoro", "voice": "pf_dora", "speed": 1.1},
        path="/v1/tts/select",
        method="POST",
    )
    status, body, headers = request(
        payload={"input": "Olá teste", "response_format": "wav"},
        path="/v1/audio/speech",
        method="POST",
    )
    assert status == 200
    assert body == b"RIFF...."
    assert headers.get("Content-Type", "").startswith("audio/wav")
    assert calls[-1][1]["voice"] == "pf_dora"


def test_smoke_synthesis_local(monkeypatch):
    from src.tts_providers import supertonic3 as mod

    monkeypatch.setattr(
        mod.Supertonic3Provider,
        "synthesize",
        lambda self, *a, **k: AudioResult(
            audio=b"RIFF....", mime="audio/wav", format="wav"
        ),
    )
    res = mod.Supertonic3Provider().synthesize("oi", "M1", 1.0, "wav")
    assert res.audio == b"RIFF...."


def test_kokoro_and_qwen_providers_call_real_tts_manager_generate(monkeypatch):
    import inspect
    import queue
    from src.TTSManager import TTSManager
    from src.tts_providers.kokoro import KokoroProvider
    from src.tts_providers.qwen import QwenTTSProvider

    sig = inspect.signature(TTSManager.generate)
    assert "device" in sig.parameters
    assert "output_format" in sig.parameters

    tm = TTSManager()
    monkeypatch.setattr(tm, "ensure_worker_running", lambda backend: None)
    for backend in ("kokoro", "qwen"):
        tm.task_queues[backend] = queue.Queue()
        tm.result_queues[backend] = queue.Queue()
        tm.worker_processes[backend] = Mock(is_alive=lambda: True)

    monkeypatch.setattr("src.TTSManager.TTSManager", lambda: tm)

    def feed_result(backend):
        req = tm.task_queues[backend].get(timeout=2)
        tm.result_queues[backend].put(
            {"req_id": req["req_id"], "ok": True, "wav_data": b"RIFFfake"}
        )

    threading.Thread(target=feed_result, args=("kokoro",), daemon=True).start()
    res_k = KokoroProvider().synthesize("Olá", "pm_santa", 1.0, "wav", device="default")
    assert res_k.audio == b"RIFFfake"
    assert res_k.mime == "audio/wav"

    threading.Thread(target=feed_result, args=("qwen",), daemon=True).start()
    res_q = QwenTTSProvider().synthesize("Olá", "ryan", 1.0, "wav", device="default")
    assert res_q.audio == b"RIFFfake"
    assert res_q.mime == "audio/wav"


def test_http_preview_audio_speech_and_speak_flow_through_real_tts_manager(
    api, monkeypatch
):
    import queue
    import time
    from src.TTSManager import TTSManager

    request, port = api
    origin = f"http://127.0.0.1:{port}"
    status_sess, _, headers = request(
        payload={},
        path="/api/pia/session",
        method="POST",
        headers={"Origin": origin},
    )
    assert status_sess == 200
    cookie = (headers.get("Set-Cookie") or headers.get("set-cookie")).split(";", 1)[0]

    tm = TTSManager()
    monkeypatch.setattr(tm, "ensure_worker_running", lambda backend: None)
    for backend in ("kokoro", "qwen"):
        tm.task_queues[backend] = queue.Queue()
        tm.result_queues[backend] = queue.Queue()
        tm.worker_processes[backend] = Mock(is_alive=lambda: True)
    tts_jobs = []
    monkeypatch.setattr(tm, "add_tts_job", lambda **kwargs: tts_jobs.append(kwargs))
    monkeypatch.setattr("src.TTSManager.TTSManager", lambda: tm)

    def feed_once(backend):
        req = tm.task_queues[backend].get(timeout=3)
        tm.result_queues[backend].put(
            {"req_id": req["req_id"], "ok": True, "wav_data": b"RIFFreal"}
        )

    # 1. /api/pia/tts/preview via real KokoroProvider -> TTSManager.generate(device=...)
    threading.Thread(target=feed_once, args=("kokoro",), daemon=True).start()
    st_prev, prev_job, _ = request(
        payload={
            "text": "Teste preview real",
            "profile": {
                "provider": "kokoro",
                "model": "kokoro-v1.0",
                "voice": "pm_santa",
                "speed": 1.0,
            },
        },
        path="/api/pia/tts/preview",
        method="POST",
        headers={"Cookie": cookie, "Origin": origin},
    )
    assert st_prev == 202
    job_id = prev_job["job_id"]
    audio_bytes = None
    for _ in range(40):
        st_aud, data_aud, _ = request(
            path=f"/api/pia/tts/previews/{job_id}/audio",
            method="GET",
            headers={"Cookie": cookie},
        )
        if st_aud == 200:
            audio_bytes = data_aud
            break
        time.sleep(0.05)
    assert audio_bytes == b"RIFFreal"

    # 2. /v1/audio/speech via real QwenTTSProvider -> TTSManager.generate(device=...)
    threading.Thread(target=feed_once, args=("qwen",), daemon=True).start()
    st_sp, body_sp, _ = request(
        payload={
            "model": "qwen",
            "voice": "Ryan",
            "input": "Teste speech real",
            "response_format": "wav",
        },
        path="/v1/audio/speech",
        method="POST",
    )
    assert st_sp == 200
    assert body_sp == b"RIFFreal"

    # 3. /tts/speak with device kwarg
    st_spk, data_spk, _ = request(
        payload={"text": "Teste speak real", "device": "default"},
        path="/tts/speak",
        method="POST",
    )
    assert st_spk == 200
    assert data_spk["ok"] is True
    assert len(tts_jobs) == 1
    assert tts_jobs[0]["device"] == "default"


def test_keys_not_in_logs(caplog):
    from src.tts_providers import openai_tts, elevenlabs

    caplog.set_level(logging.DEBUG)
    p = openai_tts.OpenAITTSProvider()
    assert "sk-" not in repr(p)
    e = elevenlabs.ElevenLabsProvider()
    assert "xi-api-key" not in repr(e)
    try:
        p.synthesize("hi", "alloy", 1.0, "mp3")
    except Exception as ex:
        assert "sk-" not in str(ex)


def test_kokoro_detected_when_installed_in_tts_manager_path(tmp_path, monkeypatch):
    from src import config as cfg
    from src.tts_providers.kokoro import KokoroProvider
    from src.tts_providers.registry import TTSProviderRegistry

    kokoro_dir = tmp_path / "main" / "tts" / "kokoro"
    kokoro_dir.mkdir(parents=True)
    (kokoro_dir / "kokoro-v1.0.onnx").write_bytes(b"onnx-weights")
    (kokoro_dir / "voices-v1.0.bin").write_bytes(b"voices-bin")

    monkeypatch.setattr(cfg, "TTS_KOKORO_MODEL", str(kokoro_dir))
    monkeypatch.setattr(
        "src.tts_providers.kokoro.is_manifest_installed",
        lambda *_a, **_kw: False,
    )

    prov = KokoroProvider()
    assert prov.is_available("kokoro-v1.0") is True

    reg = TTSProviderRegistry()
    cat = {p["id"]: p for p in reg.catalog()}
    kok = cat["kokoro"]
    assert kok["available"] is True
    assert kok["installed"] is True
    assert kok["installation"]["state"] == "installed"
    assert kok["models"][0]["installed"] is True
    assert kok["models"][0]["installation"]["state"] == "installed"


def test_tts_install_job_reports_incremental_progress(api, tmp_path, monkeypatch):
    import threading
    import time
    from src.tts_providers import local_catalog, piper

    request, port = api
    origin = f"http://127.0.0.1:{port}"
    st_s, _, hdrs = request(
        payload={},
        path="/api/pia/session",
        method="POST",
        headers={"Origin": origin},
    )
    assert st_s == 200
    cookie = (hdrs.get("Set-Cookie") or hdrs.get("set-cookie")).split(";", 1)[0]

    monkeypatch.setenv("PIA_USER_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(
        piper,
        "_ARTIFACTS",
        [
            {
                "filename": "pt_BR-faber-medium.onnx",
                "url": "https://example.invalid/model.onnx",
                "size_bytes": 100,
            }
        ],
    )

    release_second_chunk = threading.Event()
    first_chunk_sent = threading.Event()

    class _FakeResp:
        def __init__(self):
            self.headers = {"Content-Length": "100"}
            self._chunks = [b"a" * 50, b"b" * 50, b""]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _n=-1):
            chunk = self._chunks.pop(0)
            if len(self._chunks) == 2:
                return chunk
            if len(self._chunks) == 1:
                first_chunk_sent.set()
                release_second_chunk.wait(timeout=5)
                return chunk
            return chunk

    monkeypatch.setattr(
        local_catalog.urllib.request, "urlopen", lambda *_a, **_kw: _FakeResp()
    )

    st_ins, ins_data, _ = request(
        payload={"provider": "piper", "model": "pt_BR-faber-medium"},
        path="/api/pia/tts/install",
        method="POST",
        headers={"Cookie": cookie, "Origin": origin},
    )
    assert st_ins == 202
    job_id = ins_data["job_id"]

    assert first_chunk_sent.wait(timeout=5)
    # Wait briefly for on_progress(50, 100) to record 50%
    mid_job = None
    for _ in range(40):
        st_j, job_snap, _ = request(
            path=f"/api/pia/tts/jobs/{job_id}",
            method="GET",
            headers={"Cookie": cookie},
        )
        assert st_j == 200
        if (job_snap.get("progress") or {}).get("completed_bytes") == 50:
            mid_job = job_snap
            break
        time.sleep(0.025)

    assert mid_job is not None
    assert mid_job["state"] == "running"
    assert mid_job["phase"] == "downloading"
    assert mid_job["progress"] == {
        "completed_bytes": 50,
        "total_bytes": 100,
        "percent": 50.0,
    }

    release_second_chunk.set()
    done_job = None
    for _ in range(60):
        st_j, job_snap, _ = request(
            path=f"/api/pia/tts/jobs/{job_id}",
            method="GET",
            headers={"Cookie": cookie},
        )
        assert st_j == 200
        if job_snap.get("state") == "done":
            done_job = job_snap
            break
        time.sleep(0.025)

    assert done_job is not None
    assert done_job["phase"] == "done"
    assert done_job["progress"] == {
        "completed_bytes": 100,
        "total_bytes": 100,
        "percent": 100.0,
    }
    assert done_job["result"]["installed"] is True


def test_preview_synthesizes_once_without_local_playback_or_duplicate_events(
    api, monkeypatch
):
    import time
    from src.TTSManager import TTSManager
    from src.tts_service import get_tts_service

    request, port = api
    origin = f"http://127.0.0.1:{port}"
    st_s, _, hdrs = request(
        payload={},
        path="/api/pia/session",
        method="POST",
        headers={"Origin": origin},
    )
    assert st_s == 200
    cookie = (hdrs.get("Set-Cookie") or hdrs.get("set-cookie")).split(";", 1)[0]

    tm = TTSManager()
    playback_calls = []
    monkeypatch.setattr(
        tm, "add_tts_job", lambda *a, **kw: playback_calls.append(("tts", a, kw))
    )
    monkeypatch.setattr(
        tm, "add_audio_job", lambda *a, **kw: playback_calls.append(("audio", a, kw))
    )
    monkeypatch.setattr("src.TTSManager.TTSManager", lambda: tm)

    svc = get_tts_service()
    prov = svc.registry.get("kokoro")
    synth_calls = []

    def fake_synthesize(
        text, voice, speed, response_format, *, model=None, style=None, device=None
    ):
        synth_calls.append((text, voice, speed, response_format, model))
        return b"RIFFpreview-once"

    monkeypatch.setattr(prov, "synthesize", fake_synthesize)

    st_prev, prev_data, _ = request(
        payload={
            "text": "Olá, eu sou a PIA e esta é a minha voz.",
            "profile": {
                "provider": "kokoro",
                "model": "kokoro-v1.0",
                "voice": "pm_santa",
                "speed": 1.0,
            },
        },
        path="/api/pia/tts/preview",
        method="POST",
        headers={"Cookie": cookie, "Origin": origin},
    )
    assert st_prev == 202
    job_id = prev_data["job_id"]

    done_snap = None
    for _ in range(40):
        st_j, snap, _ = request(
            path=f"/api/pia/tts/jobs/{job_id}",
            method="GET",
            headers={"Cookie": cookie},
        )
        assert st_j == 200
        if snap.get("state") == "done":
            done_snap = snap
            break
        time.sleep(0.025)

    assert done_snap is not None
    assert done_snap["result"]["audio_url"] == f"/api/pia/tts/previews/{job_id}/audio"

    st_aud, aud_bytes, _ = request(
        path=f"/api/pia/tts/previews/{job_id}/audio",
        method="GET",
        headers={"Cookie": cookie},
    )
    assert st_aud == 200
    assert aud_bytes == b"RIFFpreview-once"

    assert len(synth_calls) == 1
    assert playback_calls == []

    # Verifica que o stream de eventos do job emitiu apenas 1 evento 'done' (sem duplicidade)
    from src.pia.http import get_service

    ws_job = get_service().jobs.get(job_id)
    assert ws_job is not None
    done_events = [ev for ev in ws_job.events if ev.get("type") == "done"]
    assert len(done_events) == 1
    assert (
        done_events[0]["result"]["audio_url"] == f"/api/pia/tts/previews/{job_id}/audio"
    )

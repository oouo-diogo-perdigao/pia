"""Tests for per-speaker voice config, notification speaker propagation, and TTS playback status."""

from __future__ import annotations

import http.client
import io
import json
import threading
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np  # noqa: F401
import pytest

from src import settings_store
from src.notifications import NotificationCenter
from src.tts_service import TTSService
from src.workspace_store import WorkspaceStore

_desktop = ModuleType("src.LocalActions")
_desktop.LocalActions = Mock()
with patch.dict("sys.modules", {"src.LocalActions": _desktop}):
    from src import HTTPServer as http_module


def _make_wav_bytes(duration_frames: int = 800) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * duration_frames)
    return buf.getvalue()


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    db_path = tmp_path / "settings.sqlite3"
    store = settings_store.SettingsStore(path=db_path)
    monkeypatch.setattr(settings_store, "_store", store)
    monkeypatch.setattr(
        "src.user_paths.user_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    import src.tts_service as ts_mod

    svc = TTSService()
    monkeypatch.setattr(ts_mod, "_tts_service", svc)
    return store, svc


def test_speaker_voice_crud_and_resolution(isolated_store):
    _, svc = isolated_store
    v0 = svc.get_speaker_voice("native:secretaria")
    assert v0["mode"] == "inherit"
    assert v0["profile"] is None

    # Inherit resolves to general voice
    prof_inherit = svc.resolve_profile("Bot/secretaria")
    assert prof_inherit["provider"] == "kokoro"
    assert prof_inherit["voice"] == "pm_santa"

    # Set custom voice for Secretaria
    updated = svc.set_speaker_voice(
        "secretaria",
        mode="custom",
        profile={
            "provider": "kokoro",
            "model": "kokoro-v1.0",
            "voice": "pf_dora",
            "speed": 1.1,
        },
        revision=v0["revision"],
    )
    assert updated["mode"] == "custom"
    assert updated["profile"]["voice"] == "pf_dora"

    prof_custom = svc.resolve_profile("Bot/secretaria")
    assert prof_custom["voice"] == "pf_dora"
    assert prof_custom["speed"] == 1.1

    # Stale revision fails with 409
    from src.tts_service import TTSServiceError

    with pytest.raises(TTSServiceError) as exc_info:
        svc.set_speaker_voice(
            "native:secretaria", mode="inherit", revision=v0["revision"]
        )
    assert exc_info.value.status == 409


def test_notification_center_preserves_source_speaker(tmp_path):
    ws = WorkspaceStore(tmp_path / "workspace.sqlite3")
    spoken = []
    done = threading.Event()

    def fake_speak(text, *, speaker_id="pia"):
        spoken.append((text, speaker_id))
        done.set()

    nc = NotificationCenter(ws, lambda *a: None, fake_speak)
    nc.configure({"read_aloud": True, "muted": []})
    nc.publish("Bot/secretaria", "Lembrete", "Reunião às 15h.")
    assert done.wait(timeout=2)
    assert spoken == [("Lembrete. Reunião às 15h.", "Bot/secretaria")]


def test_tts_manager_play_loop_emits_speaker_and_restores_pia(monkeypatch):
    from src.TTSManager import TTSManager

    tm = TTSManager()
    states_seen = []

    class FakeStream:
        active = False

    fake_sd = ModuleType("sounddevice")
    fake_sd.play = lambda *a, **k: states_seen.append(tm.get_speech_status())
    fake_sd.get_stream = lambda: FakeStream()
    fake_sd.stop = lambda: None
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake_sd)

    ctx = {
        "utterance_id": "utt-1",
        "speaker_id": "secretaria",
        "bot_name": "Secretária",
        "avatar_url": "/bots/secretaria/avatar.svg",
        "avatar_colors": {"primary": "#ad83ff", "accent": "#65d9ff", "eyes": "#faf4ff"},
    }
    done = threading.Event()
    fut = SimpleNamespace(
        done=lambda: False,
        set_result=lambda v: done.set(),
        set_exception=lambda e: done.set(),
        cancel=lambda: done.set(),
    )
    tm.add_audio_job(
        "Secretaria test", _make_wav_bytes(), completion=fut, speaker_context=ctx
    )
    assert done.wait(timeout=3)
    # Wait briefly for finally block to restore idle
    for _ in range(30):
        if tm.get_speech_status()["status"] == "idle":
            break
        threading.Event().wait(0.02)

    assert len(states_seen) == 1
    assert states_seen[0]["status"] == "playing"
    assert states_seen[0]["speaker_id"] == "secretaria"
    assert states_seen[0]["avatar_url"] == "/bots/secretaria/avatar.svg"

    after = tm.get_speech_status()
    assert after["status"] == "idle"
    assert after["phase"] == "idle"
    assert after["speaker_id"] == "pia"
    assert after["avatar_url"] == "/pia.svg"


def test_secretaria_avatar_has_talking_hooks():
    svg = Path("Plugins/Bot/secretaria/avatar.svg").read_text(encoding="utf-8")
    assert "enable-mouth" in svg
    assert "animation-talking" in svg


def test_workspace_speaker_voice_endpoint(isolated_store):
    server = http_module.STTThreadingHTTPServer(
        ("127.0.0.1", 0), http_module.HTTPServer
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/pia/session",
            body="{}",
            headers={"Origin": origin, "Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        resp.read()
        cookie = resp.getheader("Set-Cookie").split(";", 1)[0]

        conn.request(
            "GET",
            "/api/pia/speakers/native:secretaria/voice",
            headers={"Cookie": cookie},
        )
        r1 = conn.getresponse()
        d1 = json.loads(r1.read().decode())
        assert r1.status == 200
        assert d1["mode"] == "inherit"

        body = json.dumps(
            {
                "mode": "custom",
                "revision": d1["revision"],
                "profile": {
                    "provider": "kokoro",
                    "model": "kokoro-v1.0",
                    "voice": "pf_dora",
                    "speed": 1.05,
                },
            }
        )
        conn.request(
            "PUT",
            "/api/pia/speakers/native:secretaria/voice",
            body=body,
            headers={
                "Cookie": cookie,
                "Origin": origin,
                "Content-Type": "application/json",
            },
        )
        r2 = conn.getresponse()
        d2 = json.loads(r2.read().decode())
        assert r2.status == 200
        assert d2["mode"] == "custom"
        assert d2["profile"]["voice"] == "pf_dora"
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

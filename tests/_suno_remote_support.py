"""Helpers dos testes T6: Suno pela PIA Server contra o fake local.

Só loopback (``_ALLOW_LOOPBACK_HTTP`` liberado aqui), nenhuma chamada real ao
Suno ou a uma pia-server real. Esperas por ``Event``/``Condition``; toda
thread ``pia-music`` é encerrada (cancel + release) e unida no teardown.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from Plugins.Apps.music import history, remote_suno, service, web_api
from Plugins.Connectors.pia_server import remote as device
from tests.fixtures.fake_pia_server_suno import (
    DEVICE_TOKEN,
    SUNO_AUDIO_LINK,
    SUNO_SECRET,
    FakePiaServerSuno,
)

JOB_WAIT = 15
PROMPT = "prompt-privado-do-diogo-T6"
SUNO = {"prompt": PROMPT, "provider": "suno_mcp", "duration": 30}
SECRET_NEEDLES = (
    SUNO_SECRET,
    SUNO_AUDIO_LINK,
    "fake-suno-signature",
    "X-Amz-Signature",
    DEVICE_TOKEN,
)


class Context:
    def __init__(self):
        self.jobs = {}
        self.notifications = []

    def publish_notification(self, source, title, text, **_kw):
        self.notifications.append((source, title, text))


def pair(profile, url, token=DEVICE_TOKEN):
    profile.save(
        "Connectors/pia_server",
        {"PIA_SERVER_URL": url, "PIA_SERVER_DEVICE_TOKEN": token},
    )
    remote_suno.invalidate_status()


def unpair(profile):
    profile.save("Connectors/pia_server", {"PIA_SERVER_DEVICE_TOKEN": ""})
    remote_suno.invalidate_status()


def wait_for(job, predicate, timeout=JOB_WAIT):
    with job.changed:
        assert job.changed.wait_for(lambda: predicate(job), timeout), job.events


def wait_done(job, timeout=JOB_WAIT):
    wait_for(job, lambda j: j.status != "running", timeout)
    return job


def join_workers(timeout=JOB_WAIT):
    """Join every ``pia-music`` worker (work after ``done`` included)."""
    for thread in [t for t in threading.enumerate() if t.name == "pia-music"]:
        thread.join(timeout)
        assert not thread.is_alive(), "pia-music thread still running"


def events(job, kind):
    return [e for e in job.events if e["type"] == kind]


def last(job, kind):
    found = events(job, kind)
    assert found, job.events
    return found[-1]


def sidecars(output):
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(output.glob("*.mp3.json"))
    ]


def assert_no_secrets(*blobs):
    text = "\n".join(
        b if isinstance(b, str) else json.dumps(b, ensure_ascii=False, default=str)
        for b in blobs
    )
    for needle in SECRET_NEEDLES:
        assert needle not in text, needle


@pytest.fixture(name="remote")
def remote_env(isolated_profile, monkeypatch, tmp_path):
    """Paired PC + fake pia-server + OUTPUT isolado + logs capturados."""
    output = tmp_path / "output"
    logs = []
    monkeypatch.setattr(device, "_ALLOW_LOOPBACK_HTTP", True)
    monkeypatch.setattr(service, "OUTPUT", output)
    monkeypatch.setattr(remote_suno, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(remote_suno, "OFFLINE_BACKOFF_MIN", 0.01)
    monkeypatch.setattr(remote_suno, "OFFLINE_BACKOFF_MAX", 0.02)
    monkeypatch.setattr(remote_suno, "WAIT_SLICE", 0.01)
    monkeypatch.setattr(remote_suno, "_mirrors", {})
    monkeypatch.setattr(remote_suno, "_redownloads", {})
    monkeypatch.setattr(history, "_server_ids", {})
    monkeypatch.setattr(web_api, "_latest", None)
    monkeypatch.setattr(
        "src.plugin_logs.write", lambda *args: logs.append(" · ".join(map(str, args)))
    )
    remote_suno.invalidate_status()
    context = Context()
    with FakePiaServerSuno() as fake:
        pair(isolated_profile, fake.url)
        env = SimpleNamespace(
            fake=fake,
            profile=isolated_profile,
            output=output,
            context=context,
            logs=logs,
        )
        try:
            yield env
        finally:
            fake.offline.clear()
            for gate in fake.hold.values():
                gate.set()
            for job in context.jobs.values():
                job.cancelled.set()
            for thread in [t for t in threading.enumerate() if t.name == "pia-music"]:
                thread.join(JOB_WAIT)
                assert not thread.is_alive(), "pia-music thread leaked"
    remote_suno.invalidate_status()

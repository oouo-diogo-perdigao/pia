"""T4: job worker of the music app (partial batches, codes, redaction).

Only fakes: no real Suno call (the local mock MCP integration left in T8,
RN18; T6 adds the fake PIA Server). Concurrency uses Event/release (no sleep) and every worker thread
is joined.
"""

import json
import threading

import pytest

from Plugins.Apps.music import service
from Plugins.Apps.music import web_api
from src import mcp_connectors

PLANTED = "planted-secret-token-123"
WAIT = 10


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class Context:
    def __init__(self):
        self.jobs = {}
        self.notifications = []

    def publish_notification(self, source, title, text, **_kw):
        self.notifications.append((source, title, text))


@pytest.fixture(autouse=True)
def _job_hygiene(monkeypatch):
    monkeypatch.setattr(web_api, "_latest", None)
    yield
    for thread in [t for t in threading.enumerate() if t.name == "pia-music"]:
        thread.join(WAIT)
        assert not thread.is_alive(), "worker thread still running"


def _wait(job):
    with job.changed:
        assert job.changed.wait_for(lambda: job.status != "running", timeout=WAIT)
    return job


def _run(context, data):
    response = web_api.handle("generate", data, context)
    return _wait(context.jobs[response["job"]])


def _events(job, kind):
    return [event for event in job.events if event["type"] == kind]


def _error(job):
    events = _events(job, "error")
    assert len(events) == 1, job.events
    return events[0]


def _item(n):
    return {
        "file": f"{n:032x}.mp3",
        "provider": "suno_mcp",
        "audio_url": f"/api/pia/music/files/{n:032x}.mp3",
        "batch": "b" * 32,
        "variant": n,
    }


class _NoServerBackend:
    """T6 seam faked: the server job is not created (the batch is faked)."""

    @staticmethod
    def create(data, account):
        return None


def _server_ready(monkeypatch):
    monkeypatch.setattr(
        service, "suno_job_account", lambda *_a: {"id": "acc-1", "label": "a@suno"}
    )
    monkeypatch.setattr(service, "suno_backend", lambda: _NoServerBackend())


@pytest.fixture
def suno_ready(monkeypatch):
    """Suno available (status faked) and no known secret by default."""
    monkeypatch.setattr(service, "suno_job_refusal", lambda: None)
    _server_ready(monkeypatch)
    monkeypatch.setattr(service, "suno_known_secrets", lambda: [PLANTED])

    def no_chat_generate(**_kw):
        raise AssertionError("Suno batch must not go through generate()")

    monkeypatch.setattr(service, "generate", no_chat_generate)


def _fake_batch(monkeypatch, behaviour):
    calls = []

    def batch(**kwargs):
        calls.append(kwargs)
        return behaviour(**kwargs)

    monkeypatch.setattr(service, "generate_suno_batch", batch)
    return calls


def _fail_after(tracks, exc, total):
    def behaviour(on_track, **_kw):
        for n in range(1, tracks + 1):
            on_track(_item(n), n, total)
        exc.completed, exc.total = tracks, total
        raise exc

    return behaviour


SUNO = {"prompt": "piano", "provider": "suno_mcp", "duration": 30}


# --------------------------------------------------------------------------
# 1/2. partial batch: error without suffix + code/completed/total + notification
# --------------------------------------------------------------------------
def test_partial_batch_error_event_has_code_completed_total(monkeypatch, suno_ready):
    calls = _fake_batch(monkeypatch, _fail_after(1, service.SunoUnavailableError(), 3))
    context = Context()
    job = _run(context, {**SUNO, "count": 3})

    assert job.status == "error"
    assert len(calls) == 1 and calls[0]["count"] == 3
    assert [e["item"]["variant"] for e in _events(job, "track")] == [1]
    error = _error(job)
    assert error["error"] == service.SunoUnavailableError.default_message
    assert " de 3" not in error["error"]  # answer (c): no "k de N" suffix
    assert (error["code"], error["completed"], error["total"]) == (
        "suno_unavailable",
        1,
        3,
    )
    assert error["ready_text"] == "1 de 3 músicas prontas"
    assert job.error == error["error"]
    last = _events(job, "progress")[-1]["value"]
    assert last["label"] == "Geração interrompida"
    assert last["state"] == "interrupted"
    assert (last["completed"], last["total"]) == (1, 3)
    assert context.notifications == [
        (
            "Apps/music",
            "Músicas prontas",
            "1 de 3 músicas prontas (geração interrompida)",
        )
    ]


def test_failure_without_tracks_has_no_notification(monkeypatch, suno_ready):
    _fake_batch(monkeypatch, _fail_after(0, service.SunoTimeoutError(), 1))
    context = Context()
    job = _run(context, {**SUNO, "count": 1})

    error = _error(job)
    assert (error["code"], error["completed"], error["total"]) == ("suno_timeout", 0, 1)
    assert error["error"] == service.SunoTimeoutError.default_message
    assert _events(job, "track") == []
    assert _events(job, "progress")[-1]["value"]["state"] == "interrupted"
    assert context.notifications == []


def test_partial_notification_flag_off(monkeypatch, suno_ready):
    monkeypatch.setattr(web_api, "PARTIAL_BATCH_NOTIFICATION", False)
    _fake_batch(monkeypatch, _fail_after(2, service.SunoUnavailableError(), 3))
    context = Context()
    job = _run(context, {**SUNO, "count": 3})
    assert _error(job)["completed"] == 2
    assert context.notifications == []


def test_partial_text_singular_by_total():
    assert web_api.partial_notification_text(1, 1) == (
        "1 de 1 música pronta (geração interrompida)"
    )
    assert web_api.partial_notification_text(1, 3) == (
        "1 de 3 músicas prontas (geração interrompida)"
    )
    assert service.tracks_ready_text(0, 1) == "0 de 1 música pronta"


def test_exception_completed_wins_over_tracks_seen(monkeypatch, suno_ready):
    """Tracks saved by the batch (exc.completed) are kept even if on_track
    was not called for every one of them."""

    def behaviour(on_track, **_kw):
        on_track(_item(1), 1, 3)
        exc = service.SunoClipFailedError()
        exc.completed, exc.total = 2, 3
        raise exc

    _fake_batch(monkeypatch, behaviour)
    job = _run(Context(), {**SUNO, "count": 3})
    error = _error(job)
    assert (error["code"], error["completed"], error["total"]) == ("error", 2, 3)


# --------------------------------------------------------------------------
# 3. success
# --------------------------------------------------------------------------
def test_suno_success_one_track_notifies_and_passes_job_controls(
    monkeypatch, suno_ready
):
    def behaviour(on_track, **_kw):
        on_track(_item(1), 1, 1)
        return [_item(1)]

    calls = _fake_batch(monkeypatch, behaviour)
    context = Context()
    job = _run(context, {**SUNO, "count": 1})

    assert job.status == "done", job.error
    result = _events(job, "done")[0]["result"]
    assert [i["file"] for i in result["items"]] == [_item(1)["file"]]
    assert result["batch"] == "b" * 32
    assert context.notifications == [
        ("Apps/music", "Músicas prontas", "1 música(s) gerada(s).")
    ]
    progress = _events(job, "progress")[-1]["value"]
    assert (progress["percent"], progress["completed"], progress["state"]) == (
        100,
        1,
        "completed",
    )
    kwargs = calls[0]
    assert kwargs["cancel_event"] is job.cancelled
    assert kwargs["cancelled"] == job.cancelled.is_set
    assert (kwargs["prompt"], kwargs["duration"], kwargs["lyrics"]) == ("piano", 30, "")


def test_omitted_provider_uses_saved_suno(monkeypatch, suno_ready, isolated_profile):
    isolated_profile.save("Apps/music", {"MUSIC_PROVIDER": "suno_mcp"})
    calls = _fake_batch(monkeypatch, lambda **_kw: [])
    job = _run(Context(), {"prompt": "piano", "count": 2})
    assert job.status == "done", job.error
    assert calls and calls[0]["count"] == 2


# --------------------------------------------------------------------------
# 4. redaction (CA10)
# --------------------------------------------------------------------------
def test_logs_and_error_are_redacted(monkeypatch, suno_ready):
    leak = (
        f"Bearer {PLANTED} https://cdn.example/a.mp3?X-Amz-Signature=fake-sig"
        f"&token={PLANTED} raw={PLANTED} X-Amz-Credential=abc token=zzz"
    )

    def behaviour(on_track, progress, **_kw):
        progress("log: " + leak)
        on_track(_item(1), 1, 2)
        exc = service.MusicProviderError("Falhou: " + leak)
        exc.completed, exc.total = 1, 2
        raise exc

    _fake_batch(monkeypatch, behaviour)
    context = Context()
    job = _run(context, {**SUNO, "count": 2})

    blob = json.dumps(job.events, ensure_ascii=False) + json.dumps(
        context.notifications, ensure_ascii=False
    )
    for needle in (PLANTED, "fake-sig", "X-Amz-Signature", "X-Amz-Credential", "zzz"):
        assert needle not in blob, needle
    assert _error(job)["error"].startswith("Falhou: ")
    assert any("log: " in e["text"] for e in _events(job, "log"))


def test_unexpected_exception_is_generic_and_detail_goes_to_redacted_log(
    monkeypatch, suno_ready
):
    def behaviour(**_kw):
        raise KeyError(f"token={PLANTED}")

    _fake_batch(monkeypatch, behaviour)
    job = _run(Context(), {**SUNO, "count": 1})
    error = _error(job)
    assert error["error"] == web_api.UNEXPECTED_ERROR_MESSAGE
    assert error["code"] == "error"
    logs = " ".join(e["text"] for e in _events(job, "log"))
    assert "KeyError" in logs and PLANTED not in logs


def test_redact_secrets_rules():
    text = (
        "Bearer abc.def https://h/p?sig=1&X-Amz-Signature=2 "
        "token=t1 access_token=t2 X-Amz-Date=3 secret-value-42"
    )
    out = service.redact_secrets(text, ["secret-value-42", "", None, "abc"])
    for needle in ("abc.def", "sig=1", "X-Amz-Signature", "t1", "t2", "X-Amz-Date"):
        assert needle not in out, needle
    assert "secret-value-42" not in out
    assert "https://h/p" in out
    assert service.redact_secrets(None) == ""


def test_secret_rotated_during_job_never_leaks(monkeypatch):
    """The worker reads the known secrets again for every log/error: a secret
    that appears during the job is redacted in event.error, logs and the
    notification."""
    monkeypatch.setattr(service, "suno_job_refusal", lambda: None)
    _server_ready(monkeypatch)
    known = ["initial-device-token-0001"]
    monkeypatch.setattr(service, "suno_known_secrets", lambda: list(known))
    rotated = "rotated-device-token-7777"

    def behaviour(on_track, progress, **_kw):
        progress("antes com initial-device-token-0001")
        known.append(rotated)
        progress(f"depois: {rotated}")
        on_track(_item(1), 1, 3)
        exc = service.SunoUnavailableError(f"Suno caiu ({rotated})")
        exc.completed, exc.total = 1, 3
        raise exc

    _fake_batch(monkeypatch, behaviour)
    context = Context()
    job = _run(context, {**SUNO, "count": 3})

    assert _error(job)["error"].startswith("Suno caiu (")
    blob = json.dumps(job.events, ensure_ascii=False) + json.dumps(
        context.notifications, ensure_ascii=False
    )
    for needle in ("initial-device-token-0001", rotated):
        assert needle not in blob, needle
    assert len(_events(job, "log")) == 2
    assert context.notifications[-1][2] == (
        "1 de 3 músicas prontas (geração interrompida)"
    )


def test_known_secrets_is_the_device_token_never_old_suno_entries(
    tmp_path, monkeypatch, isolated_profile
):
    mgr = _isolated_manager(tmp_path, monkeypatch)
    mgr._set_secret("suno_mcp", "default", "oauth_access_token", "old-suno-access-1")
    assert service.suno_known_secrets() == []
    token = "D" * 43
    isolated_profile.save("Connectors/pia_server", {"PIA_SERVER_DEVICE_TOKEN": token})
    assert service.suno_known_secrets() == [token]


# --------------------------------------------------------------------------
# 5. refusal before creating the job
# --------------------------------------------------------------------------
def _isolated_manager(tmp_path, monkeypatch):
    from src.core.secrets.vault import MemoryVault
    from src.workspace_store import WorkspaceStore

    mgr = mcp_connectors.MCPConnectorManager(
        store=WorkspaceStore(tmp_path / "ws.sqlite3"), vault=MemoryVault()
    )
    monkeypatch.setattr(mcp_connectors, "_manager", mgr)
    return mgr


def _remote(monkeypatch, **status):
    monkeypatch.setattr(service, "_remote_suno_status", lambda: dict(status))


@pytest.mark.parametrize("explicit", [True, False])
def test_unconnected_suno_refused_before_job_suno_not_connected(
    monkeypatch, isolated_profile, explicit
):
    _remote(monkeypatch, available=False, reason="suno_not_connected")
    isolated_profile.save("Apps/music", {"MUSIC_PROVIDER": "suno_mcp"})
    called = []
    monkeypatch.setattr(service, "generate_suno_batch", lambda **k: called.append(k))
    monkeypatch.setattr(service, "generate", lambda **k: called.append(k))
    data = {"prompt": "piano", "count": 1}
    if explicit:
        data["provider"] = "suno_mcp"
    context = Context()
    with pytest.raises(service.SunoJobRefusedError) as err:
        web_api.handle("generate", data, context)
    assert isinstance(err.value, ValueError)  # HTTP 400 in src/pia/http.py
    assert str(err.value) == "Conecte o Suno em Configurações → Música."
    assert err.value.code == "suno_not_connected"
    assert context.jobs == {} and web_api._latest is None and called == []


def test_expired_suno_refused_before_job_suno_credential_expired(monkeypatch):
    _remote(monkeypatch, available=False, reason="suno_credential_expired")
    called = []
    monkeypatch.setattr(service, "generate_suno_batch", lambda **k: called.append(k))
    context = Context()
    with pytest.raises(service.SunoJobRefusedError) as err:
        web_api.handle("generate", {**SUNO, "count": 2}, context)
    assert isinstance(err.value, ValueError)
    assert str(err.value) == service.SunoAuthError.default_message
    assert "Reconecte em Configurações → Música" in str(err.value)
    assert err.value.code == "suno_credential_expired"
    assert context.jobs == {} and web_api._latest is None and called == []


def test_unpaired_suno_is_refused_pia_server_unpaired(monkeypatch):
    # T6 replaces the T8 placeholder (pia_server_unsupported): the seam now
    # asks the PIA Server, and this PC is not paired in the test profile.
    called = []
    monkeypatch.setattr(service, "generate_suno_batch", lambda **k: called.append(k))
    context = Context()
    with pytest.raises(service.SunoJobRefusedError) as err:
        web_api.handle("generate", {**SUNO, "count": 1}, context)
    assert err.value.code == "pia_server_unpaired"
    assert context.jobs == {} and called == []


def test_available_suno_is_not_refused(monkeypatch):
    _remote(monkeypatch, available=True, connected=True, credential_state="configured")
    assert service.suno_job_refusal() is None


# --------------------------------------------------------------------------
# incomplete_batch (decision (b)): no "k de N" in event.error
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tracks", "total", "ready", "note"),
    [
        (
            1,
            3,
            "1 de 3 músicas prontas",
            "1 de 3 músicas prontas (geração interrompida)",
        ),
        (0, 1, "0 de 1 música pronta", None),
    ],
)
def test_incomplete_batch_error_message_and_ready_text(
    monkeypatch, suno_ready, tracks, total, ready, note
):
    _fake_batch(
        monkeypatch,
        _fail_after(tracks, service.SunoIncompleteBatchError(tracks, total), total),
    )
    context = Context()
    job = _run(context, {**SUNO, "count": total})
    error = _error(job)
    assert error["error"] == "O Suno devolveu menos músicas que o esperado."
    assert " de " not in error["error"]
    assert error["code"] == "incomplete_batch"
    assert (error["completed"], error["total"]) == (tracks, total)
    assert error["ready_text"] == ready
    expected = [("Apps/music", "Músicas prontas", note)] if note else []
    assert context.notifications == expected


def test_local_provider_is_not_checked_against_suno(monkeypatch, tmp_path):
    def refusal():
        raise AssertionError("Suno status must not gate other providers")

    monkeypatch.setattr(service, "suno_job_refusal", refusal)
    monkeypatch.setattr(
        service,
        "generate",
        lambda **kw: {"file": "a" * 32 + ".mp3", "provider": kw.get("provider")},
    )
    monkeypatch.setattr(service, "audio_file", lambda name: tmp_path / name)
    job = _run(Context(), {"prompt": "p", "provider": "local", "count": 1})
    assert job.status == "done", job.error


# --------------------------------------------------------------------------
# 6. cancel with Suno (Event/release, no sleep)
# --------------------------------------------------------------------------
def test_cancel_during_suno_batch_reports_credits_and_blocks_second_job(
    monkeypatch, suno_ready
):
    started, release = threading.Event(), threading.Event()

    def behaviour(on_track, cancelled, cancel_event, **_kw):
        on_track(_item(1), 1, 3)
        started.set()
        assert release.wait(WAIT)
        if cancelled():
            exc = InterruptedError(service.SUNO_CANCEL_MESSAGE)
            exc.completed, exc.total = 1, 3
            raise exc
        return [_item(1)]

    _fake_batch(monkeypatch, behaviour)
    context = Context()
    job_id = web_api.handle("generate", {**SUNO, "count": 3}, context)["job"]
    try:
        assert started.wait(WAIT)
        with pytest.raises(ValueError, match="Já há uma tarefa musical"):
            web_api.handle("generate", {**SUNO, "count": 1}, context)
        assert list(context.jobs) == [job_id]
        assert web_api.handle("cancel", {"job": job_id}, context) == {"ok": True}
    finally:
        release.set()
    job = _wait(context.jobs[job_id])

    error = _error(job)
    assert error["code"] == "cancelled"
    assert (
        error["error"] == service.SUNO_CANCEL_MESSAGE and "créditos" in error["error"]
    )
    assert (error["completed"], error["total"]) == (1, 3)
    assert (
        context.notifications[-1][2] == "1 de 3 músicas prontas (geração interrompida)"
    )


# --------------------------------------------------------------------------
# 7. codes
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (service.SunoAuthError(), "suno_auth"),
        (service.SunoUnavailableError(), "suno_unavailable"),
        (service.SunoTimeoutError(), "suno_timeout"),
        (service.SunoNoCreditsError(), "suno_no_credits"),
        (service.SunoDownloadError(), "download_failed"),
        (InterruptedError(service.SUNO_CANCEL_BEFORE_SEND_MESSAGE), "cancelled"),
        (RuntimeError("Já existe uma geração musical em andamento."), "error"),
        (ValueError("Duração deve estar entre 10 e 180 segundos."), "error"),
    ],
)
def test_error_codes(monkeypatch, suno_ready, exc, code):
    _fake_batch(monkeypatch, _fail_after(0, exc, 2))
    job = _run(Context(), {**SUNO, "count": 2})
    error = _error(job)
    assert error["code"] == code
    assert error["error"] == str(exc)
    assert (error["completed"], error["total"]) == (0, 2)


# --------------------------------------------------------------------------
# 8. other providers keep their loop and gain completed/total
# --------------------------------------------------------------------------
def test_local_batch_failure_keeps_previous_tracks(monkeypatch, tmp_path):
    produced = []

    def generate(**kwargs):
        if produced:
            raise RuntimeError("ACE-Step não conseguiu gerar a música.")
        name = "c" * 32 + ".mp3"
        (tmp_path / name).write_bytes(b"audio")
        produced.append(name)
        return {"file": name, "provider": "local", "prompt": kwargs["prompt"]}

    monkeypatch.setattr(service, "generate", generate)
    monkeypatch.setattr(service, "audio_file", lambda name: tmp_path / name)
    context = Context()
    job = _run(context, {"prompt": "p", "provider": "local", "count": 3})

    assert len(_events(job, "track")) == 1
    assert (tmp_path / produced[0]).is_file()
    assert (tmp_path / (produced[0] + ".json")).is_file()
    error = _error(job)
    assert error["error"] == "ACE-Step não conseguiu gerar a música."
    assert (error["code"], error["completed"], error["total"]) == ("error", 1, 3)
    assert context.notifications == [
        (
            "Apps/music",
            "Músicas prontas",
            "1 de 3 músicas prontas (geração interrompida)",
        )
    ]


def test_prepare_local_error_has_code_and_no_batch_fields(monkeypatch):
    def prepare(report):
        report(f"baixando com token={PLANTED}")
        raise RuntimeError("Falha ao preparar o ACE-Step.")

    monkeypatch.setattr(service, "prepare", prepare)
    context = Context()
    response = web_api.handle("prepare-local", {}, context)
    job = _wait(context.jobs[response["job"]])
    error = _error(job)
    assert error == {
        "type": "error",
        "error": "Falha ao preparar o ACE-Step.",
        "code": "error",
    }
    assert PLANTED not in json.dumps(job.events)
    assert context.notifications == []

"""E2e T6: Suno pela PIA Server contra o fake (tests/fixtures/fake_pia_server_suno.py).

Fluxo remoto completo pela API local da música (web_api): catálogo/status,
contas, connect, geração (sucesso, extra, parcial, cancelamento, offline e
volta, 409, 410), retomada e varredura de segredos. Substitui os e2e do mock
MCP removidos na T8 (RN18). Sem chamada real ao Suno nem à pia-server.
"""

from __future__ import annotations

import pytest

from Plugins.Apps.music import history, remote_suno, service, web_api
from tests._suno_remote_support import (  # noqa: F401  (fixture)
    PROMPT,
    SUNO,
    assert_no_secrets,
    events,
    last,
    remote_env,
    sidecars,
    wait_done,
    wait_for,
)
from tests.fixtures.fake_pia_server_suno import (
    OTHER_DEVICE_TOKEN,
    account,
    plan_partial,
    plan_success,
)


def test_t3_t4_behavior_probes():
    """Probes de comportamento (hasattr), não leitura de fonte."""
    for name in (
        "suno_job_refusal",
        "redact_secrets",
        "generate_suno_batch",
        "SunoIncompleteBatchError",
        "SunoJobRefusedError",
        "SunoDownloadError",
        "SunoNoCreditsError",
        "SunoClipFailedError",
        "tracks_ready_text",
    ):
        assert hasattr(service, name), name


def _suno(catalog):
    return next(p for p in catalog["providers"] if p["id"] == "suno_mcp")


def _generate(env, **data):
    result = web_api.handle("generate", {**SUNO, **data}, env.context)
    return env.context.jobs[result["job"]]


def _job_calls(fake):
    return fake.calls("POST", "/device/suno/jobs")


# --------------------------------------------------------------------------
# catálogo / status / contas
# --------------------------------------------------------------------------
def test_catalog_single_account_is_preselected_with_real_status_shape(remote):
    only = remote.fake.accounts[0]
    item = _suno(web_api.providers(remote.context))
    assert item["available"] is True and item["reason"] is None and item["hint"] is None
    assert item["selected_account_id"] == only["id"]
    assert item["settings"] == {
        "max_count": 10,
        "duration": [10, 180],
        "instrumental": True,
    }
    assert item["active_job"] is None
    (acc,) = item["accounts"]
    assert acc["id"] == only["id"] and acc["label"] == "diogo@suno"
    assert acc["credential_state"] == "configured" and acc["available"] is True
    assert "legacy_credentials" in item  # T8 field kept
    assert_no_secrets(item)


@pytest.mark.parametrize("state", ["unavailable", "refresh_failed"])
def test_unusable_credential_is_suno_credential_expired(remote, state):
    remote.fake.accounts = [account(label="velha@suno", state=state)]
    item = web_api.suno_status(remote.context)
    assert item["reason"] == "suno_credential_expired"
    assert item["accounts"][0]["reason"] == "suno_credential_expired"
    assert item["hint"]["route"] == service.SUNO_SETTINGS_ROUTE
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "suno_credential_expired"
    assert _job_calls(remote.fake) == [] and remote.context.jobs == {}


def test_two_valid_accounts_never_fall_back_to_default_or_saved_choice(remote):
    """PO: com 2+ contas válidas, nem default_account_id nem a escolha salva
    preselecionam; gerar sem suno_account_id é 400 suno_account_required."""
    first, second = account(label="a@suno"), account(label="b@suno")
    remote.fake.accounts = [first, second]
    real_status = remote.fake.status
    remote.fake.status = lambda dev: {
        **real_status(dev),
        "default_account_id": first["id"],
    }
    web_api.route(
        "POST",
        "/music/select",
        {"provider": "suno_mcp", "suno_account_id": first["id"]},
        {},
        remote.context,
    )

    item = _suno(web_api.providers(remote.context))
    assert item["available"] is True and item["selected_account_id"] is None
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "suno_account_required"
    assert _job_calls(remote.fake) == [] and remote.context.jobs == {}

    job = wait_done(_generate(remote, suno_account_id=second["id"]))
    assert job.status == "done"
    (call,) = _job_calls(remote.fake)
    assert call[2]["suno_account_id"] == second["id"]


def test_unknown_account_is_suno_account_not_found(remote):
    with pytest.raises(ValueError) as err:
        web_api.handle(
            "generate", {**SUNO, "suno_account_id": "nao-existe"}, remote.context
        )
    assert err.value.code == "suno_account_not_found"


def test_connect_attempt_states_and_codes(remote):
    started = web_api.route("POST", "/music/suno/connect", {}, {}, remote.context)
    assert set(started) == {"auth_url", "attempt_id", "expires_in"}
    assert started["auth_url"].startswith("https://") and started["expires_in"] == 600
    path = f"/music/suno/connect/{started['attempt_id']}"
    assert web_api.route("GET", path, {}, {}, remote.context) == {"state": "pending"}

    new = account(label="nova@suno")
    remote.fake.attempt_outcome = {"state": "connected", "new_account": new}
    assert web_api.route("GET", path, {}, {}, remote.context) == {
        "state": "connected",
        "account_id": new["id"],
    }
    item = web_api.suno_status(remote.context)
    assert {a["id"] for a in item["accounts"]} == {
        remote.fake.accounts[0]["id"],
        new["id"],
    }

    remote.fake.attempt_outcome = {"state": "failed", "code": "suno_account_taken"}
    assert web_api.route("GET", path, {}, {}, remote.context) == {
        "state": "failed",
        "code": "suno_account_taken",
    }

    with pytest.raises(ValueError) as err:
        web_api.route("GET", "/music/suno/connect/sumiu", {}, {}, remote.context)
    assert err.value.code == "suno_connect_not_found"
    remote.fake.attempt_outcome = {"state": "expired"}  # pia-server 0a1fee6 state
    with pytest.raises(ValueError) as err:
        web_api.route("GET", path, {}, {}, remote.context)
    assert err.value.code == "suno_connect_not_found"
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST",
            "/music/suno/connect",
            {"replace_account_id": "nao-existe"},
            {},
            remote.context,
        )
    assert err.value.code == "suno_account_not_found"


@pytest.mark.parametrize(
    "label", ["", "   ", "x" * 81, "com\x07controle", "linha\nnova", 5]
)
def test_rename_validates_label_without_calling_the_server(remote, label):
    identity = remote.fake.accounts[0]["id"]
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST",
            f"/music/suno/accounts/{identity}/rename",
            {"label": label},
            {},
            remote.context,
        )
    assert err.value.code == "invalid_label"
    assert remote.fake.calls("PATCH") == []


def test_rename_accepts_an_80_character_label(remote):
    identity = remote.fake.accounts[0]["id"]
    web_api.route(
        "POST",
        f"/music/suno/accounts/{identity}/rename",
        {"label": "x" * 80},
        {},
        remote.context,
    )
    assert len(remote.fake.calls("PATCH")) == 1


def test_rename_and_disconnect_use_the_account_routes(remote):
    identity = remote.fake.accounts[0]["id"]
    out = web_api.route(
        "POST",
        f"/music/suno/accounts/{identity}/rename",
        {"label": "  Trabalho "},
        {},
        remote.context,
    )
    assert remote.fake.calls("PATCH") == [
        ("PATCH", f"/device/suno/accounts/{identity}", {"label": "Trabalho"})
    ]
    assert out["provider"]["accounts"][0]["label"] == "Trabalho"

    out = web_api.route(
        "POST", "/music/suno/disconnect", {"account_id": identity}, {}, remote.context
    )
    assert remote.fake.calls("DELETE", "/device/suno/accounts/") == [
        ("DELETE", f"/device/suno/accounts/{identity}", {})
    ]
    assert out == {"ok": True, "provider": out["provider"]}
    assert out["provider"]["reason"] == "suno_not_connected"
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST",
            "/music/suno/disconnect",
            {"account_id": identity},
            {},
            remote.context,
        )
    assert err.value.code == "suno_account_not_found"


def test_capability_missing_is_pia_server_unsupported(remote):
    remote.fake.capabilities = []
    item = web_api.suno_status(remote.context)
    assert item["reason"] == "pia_server_unsupported" and item["available"] is False
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "pia_server_unsupported"
    assert _job_calls(remote.fake) == []


def test_unknown_device_401_without_code_is_unpaired_never_credential_expired(remote):
    from tests._suno_remote_support import pair

    pair(remote.profile, remote.fake.url, token="F" * 43)  # valid shape, unknown device
    item = web_api.suno_status(remote.context)
    assert item["reason"] == "pia_server_unpaired"
    assert item["hint"]["route"] == {
        "view": "settings",
        "section": "Connectors/pia_server",
    }
    assert remote.fake.calls("GET", "/device/account")  # it did ask (401 {error})
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "pia_server_unpaired"
    with pytest.raises(ValueError) as err:
        web_api.route("POST", "/music/suno/connect", {}, {}, remote.context)
    assert err.value.code == "pia_server_unpaired"


def test_not_paired_sends_nothing(remote):
    from tests._suno_remote_support import unpair

    unpair(remote.profile)
    before = len(remote.fake.requests)
    assert web_api.suno_status(remote.context)["reason"] == "pia_server_unpaired"
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "pia_server_unpaired"
    assert len(remote.fake.requests) == before


# --------------------------------------------------------------------------
# geração
# --------------------------------------------------------------------------
def test_success_downloads_every_track_into_output(remote):
    job = wait_done(_generate(remote, count=2))
    assert job.status == "done", job.events
    tracks = events(job, "track")
    assert len(tracks) == 2
    assert remote.context.notifications[-1][2] == "2 música(s) gerada(s)."
    (call,) = _job_calls(remote.fake)
    assert call[2]["prompt"] == PROMPT and call[2]["count"] == 2
    assert set(call[2]) >= {"client_job_id", "suno_account_id", "duration", "lyrics"}
    files = sorted(p.name for p in remote.output.glob("*.mp3"))
    assert len(files) == 2 and not list(remote.output.glob("*.part"))
    for meta in sidecars(remote.output):
        assert meta["provider"] == "suno_mcp" and meta["label"] == "Suno"
        assert meta["audio_url"] == "/api/pia/music/files/" + meta["file"]
        assert meta["client_id"] == call[2]["client_job_id"]
    entry = history.get(call[2]["client_job_id"])
    assert entry["state"] == "completed" and entry["pending"] is False
    assert set(entry["tracks"]) == {"1", "2"}
    progress = last(job, "progress")["value"]
    assert progress["completed"] == 2 and progress["connection"] == "ok"
    assert_no_secrets(
        job.events,
        sidecars(remote.output),
        remote.logs,
        (remote.output / history.INDEX_NAME).read_text(),
    )
    assert not any(PROMPT in line for line in remote.logs)


def test_extra_tracks_are_saved_and_counted_separately(remote):
    remote.fake.next_plan = plan_success(2, extra=1)
    job = wait_done(_generate(remote, count=2))
    assert job.status == "done"
    items = [e["item"] for e in events(job, "track")]
    assert [i["extra"] for i in items] == [False, False, True]
    assert items[2]["label"] == "Suno · extra"
    assert remote.context.notifications[-1][2] == "2 música(s) gerada(s) (+1 extra)."
    assert "(+1 extra)" in last(job, "progress")["value"]["ready_text"]
    assert len(list(remote.output.glob("*.mp3"))) == 3


def test_partial_failure_keeps_ready_tracks_with_server_code(remote):
    remote.fake.next_plan = plan_partial(1, 3, "suno_no_credits")
    job = wait_done(_generate(remote, count=3))
    error = last(job, "error")
    assert error["code"] == "suno_no_credits"
    assert (error["completed"], error["total"]) == (1, 3)
    assert error["error"] == "A conta Suno diogo@suno está sem créditos."
    assert (
        len(events(job, "track")) == 1 and len(list(remote.output.glob("*.mp3"))) == 1
    )
    assert (
        remote.context.notifications[-1][2]
        == "1 de 3 músicas prontas (geração interrompida)"
    )


def test_cancel_sends_server_cancel_and_keeps_downloaded_tracks(remote):
    gate = remote.fake.hold.setdefault(1, __import__("threading").Event())
    job = _generate(remote, count=2)
    wait_for(job, lambda j: events(j, "track"))
    web_api.handle("cancel", {"job": job.id}, remote.context)
    wait_done(job)
    assert not gate.is_set()
    error = last(job, "error")
    assert error["code"] == "cancelled" and error["completed"] == 1
    server_id = next(iter(remote.fake.jobs))
    assert remote.fake.calls("POST", f"/device/suno/jobs/{server_id}/cancel")
    assert len(list(remote.output.glob("*.mp3"))) == 1


def test_offline_then_back_reports_connection_and_finishes(remote):
    import threading

    gate = remote.fake.hold.setdefault(1, threading.Event())
    job = _generate(remote, count=2)
    wait_for(job, lambda j: events(j, "track"))
    remote.fake.offline.set()
    wait_for(
        job,
        lambda j: any(
            e["value"].get("connection") == "lost" for e in events(j, "progress")
        ),
    )
    assert any("Sem conexão com a PIA Server" in e["text"] for e in events(job, "log"))
    assert job.status == "running"  # no deadline: still waiting
    remote.fake.offline.clear()
    gate.set()
    wait_done(job)
    assert job.status == "done", job.events
    states = [e["value"].get("connection") for e in events(job, "progress")]
    lost = states.index("lost")
    assert "ok" in states[lost:]
    assert len(list(remote.output.glob("*.mp3"))) == 2


def test_job_active_409_is_400_without_local_job(remote):
    remote.fake.job_conflict = True
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "suno_job_active"
    assert remote.context.jobs == {} and web_api._latest is None


def test_active_job_of_other_device_blocks_and_has_no_local_id(remote):
    import threading

    remote.fake.hold[0] = threading.Event()
    remote.fake.create_job(
        {"count": 1, "client_job_id": "c-outro", "prompt": "x"}, "device-b"
    )
    item = web_api.suno_status(remote.context)
    assert (
        item["active_job"]["this_device"] is False
        and item["active_job"]["job_id"] is None
    )
    assert remote.context.jobs == {}  # nothing mirrored on this PC
    with pytest.raises(ValueError) as err:
        web_api.handle("generate", dict(SUNO), remote.context)
    assert err.value.code == "suno_job_active"


def _hold_first_step(remote):
    import threading

    gate = remote.fake.hold.setdefault(0, threading.Event())
    job = _generate(remote, count=2)
    remote.fake.wait_polls(1)
    generation = next(iter(remote.fake.jobs.values()))["generation_id"]
    return job, gate, generation


def test_track_unavailable_410_is_typed_and_other_tracks_are_kept(remote):
    job, gate, generation = _hold_first_step(remote)
    remote.fake.dead_tracks.add((generation, 2))
    gate.set()
    wait_done(job)
    error = last(job, "error")
    assert error["code"] == "suno_track_unavailable"
    assert error["error"] == "Esta música não está mais disponível no Suno."
    assert len(list(remote.output.glob("*.mp3"))) == 1


def test_sha_mismatch_is_download_failed_without_part(remote):
    job, gate, generation = _hold_first_step(remote)
    remote.fake.bad_sha.add((generation, 1))
    gate.set()
    wait_done(job)
    assert last(job, "error")["code"] == "download_failed"
    assert not list(remote.output.glob("*.part"))
    assert len(list(remote.output.glob("*.mp3"))) == 1


# --------------------------------------------------------------------------
# retomada
# --------------------------------------------------------------------------
def test_reopen_mirrors_active_job_of_this_pc_and_downloads(remote):
    import threading

    gate = remote.fake.hold.setdefault(0, threading.Event())
    remote.fake.create_job(
        {
            "count": 1,
            "client_job_id": "c-reaberto",
            "prompt": "x",
            "suno_account_id": remote.fake.accounts[0]["id"],
        },
        "device-a",
    )
    item = _suno(web_api.providers(remote.context))
    local_id = item["active_job"]["job_id"]
    assert item["active_job"]["this_device"] is True and local_id in remote.context.jobs
    # a second catalog call does not start a second mirror
    assert _suno(web_api.providers(remote.context))["active_job"]["job_id"] == local_id
    assert len(remote.context.jobs) == 1
    gate.set()
    job = wait_done(remote.context.jobs[local_id])
    assert job.status == "done"
    assert history.get("c-reaberto")["tracks"]["1"]["file"]


def test_reopen_finishes_pending_downloads_of_a_completed_job(remote):
    created = remote.fake.create_job(
        {
            "count": 1,
            "client_job_id": "c-pendente",
            "prompt": "x",
            "suno_account_id": remote.fake.accounts[0]["id"],
        },
        "device-a",
    )[1]
    remote.fake.jobs[created["job_id"]]["step"] = 2  # already completed on the server
    history.record(
        "c-pendente",
        source="suno",
        provider="suno_mcp",
        prompt=PROMPT,
        lyrics="",
        params={"provider": "suno_mcp", "duration": 30, "count": 1},
        count=1,
        state="running",
        job_id=created["job_id"],
        generation_id=created["generation_id"],
        suno_account=None,
        pending=True,
    )
    web_api.providers(remote.context)
    (job,) = remote.context.jobs.values()
    wait_done(job)
    assert job.status == "done"
    assert history.get("c-pendente")["pending"] is False
    assert history.pending_suno_jobs() == []


# --------------------------------------------------------------------------
# rota pelo WorkspaceService (/api/pia/music/*)
# --------------------------------------------------------------------------
def test_workspace_dispatch_routes_music_paths_to_the_app(remote):
    from types import SimpleNamespace

    from src.pia.service import WorkspaceService

    workspace = WorkspaceService(backend=SimpleNamespace(store=None))
    status = workspace._dispatch("GET", "/music/suno/status", {}, {})
    assert status["id"] == "suno_mcp" and status["available"] is True
    catalog = workspace._dispatch("GET", "/music/providers", {}, {})
    assert [p["id"] for p in catalog["providers"]] == ["local", "gemini", "suno_mcp"]
    page = workspace._dispatch("GET", "/music/history", {}, {})
    assert page["server_unavailable"] is False
    legacy = workspace._dispatch("GET", "/music/suno/legacy-credentials", {}, {})
    assert "present" in legacy  # T8 route untouched


def test_other_device_token_sees_job_as_not_this_device(remote):
    from tests._suno_remote_support import pair

    job = wait_done(_generate(remote, count=1))
    assert job.status == "done"
    pair(remote.profile, remote.fake.url, token=OTHER_DEVICE_TOKEN)
    page = web_api.route("GET", "/music/history", {}, {}, remote.context)
    (item,) = page["items"]
    assert item["this_device"] is True  # the local index knows it was generated here
    assert item["tracks"][0]["availability"] == "local_file"


def test_generate_accepts_suno_account_id_from_music_generate(remote):
    identity = remote.fake.accounts[0]["id"]
    assert "suno_account_id" in web_api.GENERATE_KEYS
    job = wait_done(_generate(remote, suno_account_id=identity))
    assert job.status == "done"
    (call,) = _job_calls(remote.fake)
    assert call[2]["suno_account_id"] == identity


def test_suno_job_expired_no_longer_exists(remote):
    """Contrato v3 final: sem expiração de job (sem ACK nem TTL de 24 h)."""
    assert "suno_job_expired" not in remote_suno.MESSAGES
    assert not hasattr(remote_suno, "JOB_TTL")
    exc = remote_suno.job_error("suno_job_expired")  # unknown code: generic error
    assert type(exc) is service.MusicProviderError
    remote.fake.next_plan = plan_success(1)
    job = wait_done(_generate(remote, count=1))
    assert job.status == "done"
    assert all("expired" not in str(e.get("code")) for e in job.events)
    assert not any(
        "ack" in c[1] for c in remote.fake.calls("POST", "/device/suno/jobs/")
    )

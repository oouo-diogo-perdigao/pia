"""T6 (v3.1/v3.2): histórico de gerações, fila de registros locais e
re-download, contra o fake da pia-server. Nunca apaga arquivo local."""

from __future__ import annotations

import threading
import time

import pytest

from Plugins.Apps.music import history, remote_suno, service, web_api
from tests._suno_remote_support import (  # noqa: F401  (fixture)
    PROMPT,
    assert_no_secrets,
    last,
    join_workers,
    pair,
    remote_env,
    sidecars,
    unpair,
    wait_done,
)
from tests.fixtures.fake_pia_server_suno import audio_bytes

LOCAL = {"prompt": PROMPT, "provider": "local", "duration": 30}


@pytest.fixture
def local_generator(remote, monkeypatch):
    def generate(**kwargs):
        name = f"{time.time_ns():032x}"[-32:] + ".mp3"
        remote.output.mkdir(parents=True, exist_ok=True)
        (remote.output / name).write_bytes(b"ID3local")
        return {
            "file": name,
            "provider": kwargs.get("provider") or "local",
            "prompt": kwargs.get("prompt"),
            "audio_url": "/api/pia/music/files/" + name,
        }

    monkeypatch.setattr(service, "generate", generate)
    return generate


def _local(remote, count=1):
    result = web_api.handle("generate", {**LOCAL, "count": count}, remote.context)
    job = wait_done(remote.context.jobs[result["job"]])
    join_workers()  # the record is sent after the "done" event
    assert job.status == "done", job.events
    return job


def _records(fake):
    """Local records the server actually stored (attempts while offline are
    logged by the fake but answered 503)."""
    with fake.lock:
        return [g for g in fake.generations if g["source"] == "local"]


def _history(remote, **query):
    return web_api.route(
        "GET", "/music/history", {}, {k: [v] for k, v in query.items()}, remote.context
    )


# --------------------------------------------------------------------------
# RN14: registro das gerações locais
# --------------------------------------------------------------------------
def test_local_generation_is_recorded_online_without_audio(remote, local_generator):
    job = _local(remote, count=2)
    (call,) = remote.fake.calls("POST", "/device/music/generations")
    body = call[2]
    assert body["source"] == "local" and body["provider"] == "local"
    assert (
        body["prompt"] == PROMPT and body["count"] == 2 and body["state"] == "completed"
    )
    assert not set(body) & {"audio", "audio_url", "file", "path", "data"}
    assert len(_records(remote.fake)) == 1
    client_id = last(job, "track")["item"]["client_id"]
    assert body["client_id"] == client_id
    assert history.get(client_id)["generation_id"]
    assert history.queued_ids() == []
    assert not any(PROMPT in line for line in remote.logs)


def test_paired_offline_queues_and_flushes_when_back(remote, local_generator):
    remote.fake.offline.set()
    job = _local(remote)
    client_id = last(job, "track")["item"]["client_id"]
    assert history.queued_ids() == [client_id]
    offline = _history(remote)
    assert offline["server_unavailable"] is True
    assert offline["server_reason"] == "pia_server_unreachable"
    assert [i["id"] for i in offline["items"]] == [client_id]
    remote.fake.offline.clear()
    page = _history(remote)
    assert page["server_unavailable"] is False and history.queued_ids() == []
    assert [g["client_id"] for g in _records(remote.fake)] == [client_id]
    assert [i["id"] for i in page["items"]] == [client_id]  # merged, not duplicated
    assert not any(PROMPT in line for line in remote.logs)


def test_unpaired_local_generation_sends_and_queues_nothing(remote, local_generator):
    unpair(remote.profile)
    job = _local(remote)
    client_id = last(job, "track")["item"]["client_id"]
    assert remote.fake.calls("POST", "/device/music/generations") == []
    pair(remote.profile, remote.fake.url)
    assert history.queued_ids() == []
    assert history.get(client_id) is not None  # still in the local index


def test_queue_keeps_newest_500_and_drops_after_30_days(remote, monkeypatch):
    monkeypatch.setattr(history, "QUEUE_MAX_ITEMS", 3)
    remote.fake.offline.set()
    for n in range(5):
        entry = history.record(
            f"loc-{n}",
            source="local",
            provider="gemini",
            prompt=PROMPT,
            lyrics="",
            params={"provider": "gemini", "duration": 30},
            count=1,
            state="completed",
            code=None,
        )
        assert history.record_local_generation(entry) == "queued"
    assert history.queued_ids() == ["loc-2", "loc-3", "loc-4"]
    from src.settings_store import get_store

    with get_store().connection() as db:
        db.execute(
            "UPDATE pia_music_generation_queue SET created=? WHERE client_id='loc-2'",
            (time.time() - history.QUEUE_MAX_AGE - 10,),
        )
    remote.fake.offline.clear()
    assert history.flush_pending() == 2
    assert [g["client_id"] for g in _records(remote.fake)] == ["loc-3", "loc-4"]


# --------------------------------------------------------------------------
# GET /music/history
# --------------------------------------------------------------------------
def test_history_format_and_availability(remote):
    fake = remote.fake
    acc = fake.accounts[0]
    mine = fake.add_generation(client_id="c-mine", count=1)
    other_suno = fake.add_generation(
        client_id="c-suno-b",
        device_id="device-b",
        tracks=[
            {"n": 1, "title": "B", "duration": 20, "extra": False},
            {"n": 2, "title": "B+", "duration": 20, "extra": True},
        ],
    )
    fake.add_generation(
        client_id="c-local-b",
        device_id="device-b",
        source="local",
        provider="gemini",
        suno_account=None,
        count=2,
        tracks=[],
    )
    # c-mine was downloaded here
    path = remote.output / ("a" * 32 + ".mp3")
    remote.output.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio_bytes(mine["id"], 1))
    history.record(
        "c-mine",
        source="suno",
        provider="suno_mcp",
        prompt="prompt",
        lyrics="",
        params={
            "provider": "suno_mcp",
            "duration": 30,
            "count": 1,
            "suno_account_id": acc["id"],
        },
        count=1,
        state="completed",
        generation_id=mine["id"],
        suno_account={"id": acc["id"], "name": acc["label"]},
    )
    remote_suno.save_track(
        path,
        history.get("c-mine"),
        {"n": 1, "title": "Faixa 1", "duration": 30},
        variant=1,
    )

    page = _history(remote, limit="100")
    assert set(page) == {"items", "next_cursor", "server_unavailable", "server_reason"}
    assert page["server_unavailable"] is False and page["server_reason"] is None
    by_id = {i["id"]: i for i in page["items"]}
    assert set(by_id) == {"c-mine", "c-suno-b", "c-local-b"}
    item = by_id["c-mine"]
    assert set(item) >= {
        "id",
        "job_id",
        "provider",
        "source",
        "suno_account",
        "prompt",
        "lyrics",
        "params",
        "created_at",
        "state",
        "code",
        "count",
        "this_device",
        "tracks",
    }
    assert item["suno_account"] == {"id": acc["id"], "name": acc["label"]}
    assert item["params"] == {
        "provider": "suno_mcp",
        "duration": 30,
        "count": 1,
        "suno_account_id": acc["id"],
    }
    (track,) = item["tracks"]
    assert track["availability"] == "local_file"
    assert track["file"]["file"] == path.name and track["file"]["audio_url"].endswith(
        path.name
    )
    suno_b = by_id["c-suno-b"]
    assert suno_b["this_device"] is False
    assert [t["availability"] for t in suno_b["tracks"]] == ["redownload", "redownload"]
    assert [t["label"] for t in suno_b["tracks"]] == ["Suno", "Suno · extra"]
    assert all(t["file"] is None for t in suno_b["tracks"])
    local_b = by_id["c-local-b"]
    assert [t["availability"] for t in local_b["tracks"]] == ["other_device_local"] * 2
    assert all(t["file"] is None for t in local_b["tracks"])
    assert {t["label"] for t in local_b["tracks"]} == {"Gemini"}
    assert other_suno["id"] not in by_id
    assert_no_secrets(page)


def test_history_paginates_with_opaque_cursor(remote):
    for n in range(3):
        remote.fake.add_generation(
            client_id=f"c-{n}", created=f"2026-11-1{n}T10:00:00.000000Z"
        )
    first = _history(remote, limit="2")
    assert [i["id"] for i in first["items"]] == ["c-2", "c-1"] and first["next_cursor"]
    second = _history(remote, limit="2", cursor=first["next_cursor"])
    assert [i["id"] for i in second["items"]] == ["c-0"] and second[
        "next_cursor"
    ] is None
    with pytest.raises(ValueError):
        _history(remote, cursor="%%%")


def test_history_unpaired_falls_back_to_local_index(remote):
    remote.fake.add_generation(client_id="c-server")
    history.record(
        "c-local",
        source="local",
        provider="local",
        prompt="p",
        lyrics="",
        params={"provider": "local"},
        count=1,
        state="completed",
    )
    unpair(remote.profile)
    page = _history(remote)
    assert (
        page["server_unavailable"] is True
        and page["server_reason"] == "pia_server_unpaired"
    )
    assert [i["id"] for i in page["items"]] == ["c-local"]


# --------------------------------------------------------------------------
# DELETE /music/history/<id>
# --------------------------------------------------------------------------
def _downloaded_suno(remote, client_id="c-del"):
    gen = remote.fake.add_generation(client_id=client_id)
    remote.output.mkdir(parents=True, exist_ok=True)
    path = remote.output / ("b" * 32 + ".mp3")
    path.write_bytes(b"ID3")
    history.record(
        client_id,
        source="suno",
        provider="suno_mcp",
        prompt="p",
        lyrics="",
        params={"provider": "suno_mcp"},
        count=1,
        state="completed",
        generation_id=gen["id"],
        suno_account=None,
    )
    remote_suno.save_track(path, history.get(client_id), {"n": 1}, variant=1)
    return gen, path


def test_delete_is_server_hard_delete_plus_tombstone_and_never_removes_the_file(remote):
    gen, path = _downloaded_suno(remote)
    assert web_api.route("DELETE", "/music/history/c-del", {}, {}, remote.context) == {
        "ok": True,
        "id": "c-del",
    }
    assert remote.fake.calls("DELETE", f"/device/music/generations/{gen['id']}")
    assert all(g["id"] != gen["id"] for g in remote.fake.generations)
    assert path.is_file() and path.with_name(path.name + ".json").is_file()
    assert "c-del" in history.entries()[1]
    assert _history(remote)["items"] == []
    remote.fake.offline.set()
    assert _history(remote)["items"] == []  # the tombstone also hides it offline
    assert any(item["file"] == path.name for item in service.library())


def test_delete_offline_is_400_unreachable_and_changes_nothing(remote):
    gen, path = _downloaded_suno(remote)
    remote.fake.offline.set()
    with pytest.raises(ValueError) as err:
        web_api.route("DELETE", "/music/history/c-del", {}, {}, remote.context)
    assert err.value.code == "pia_server_unreachable"
    assert "c-del" not in history.entries()[1]
    assert any(g["id"] == gen["id"] for g in remote.fake.generations)
    assert path.is_file()


def test_delete_unpaired_is_pia_server_unpaired(remote):
    _gen, path = _downloaded_suno(remote)
    unpair(remote.profile)
    with pytest.raises(ValueError) as err:
        web_api.route("DELETE", "/music/history/c-del", {}, {}, remote.context)
    assert err.value.code == "pia_server_unpaired"
    assert "c-del" not in history.entries()[1] and path.is_file()


def test_delete_queued_local_record_unqueues_it(remote):
    remote.fake.offline.set()
    entry = history.record(
        "loc-q",
        source="local",
        provider="local",
        prompt="p",
        lyrics="",
        params={"provider": "local"},
        count=1,
        state="completed",
    )
    assert history.record_local_generation(entry) == "queued"
    remote.fake.offline.clear()
    web_api.route("DELETE", "/music/history/loc-q", {}, {}, remote.context)
    assert history.queued_ids() == [] and "loc-q" in history.entries()[1]
    assert _records(remote.fake) == []


# --------------------------------------------------------------------------
# POST /music/history/<id>/tracks/<n>/redownload
# --------------------------------------------------------------------------
def test_redownload_on_another_pc_is_idempotent_and_saves_to_output(
    remote, monkeypatch
):
    gen = remote.fake.add_generation(client_id="c-re", device_id="device-b")
    gate, started = threading.Event(), threading.Event()
    real = remote_suno.download_track

    def gated(*args, **kwargs):
        started.set()
        assert gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(remote_suno, "download_track", gated)
    path = "/music/history/c-re/tracks/1/redownload"
    first = web_api.route("POST", path, {}, {}, remote.context)
    assert started.wait(10)
    second = web_api.route("POST", path, {}, {}, remote.context)
    assert first == second == {"job_id": first["job_id"]}
    assert len(remote.context.jobs) == 1
    gate.set()
    job = wait_done(remote.context.jobs[first["job_id"]])
    assert job.status == "done", job.events
    event = last(job, "track")
    assert event["history_id"] == "c-re"
    assert event["track"]["availability"] == "local_file" and event["track"]["n"] == 1
    assert event["item"] == event["track"]["file"]
    assert set(event) == {"type", "item", "track", "history_id"}
    assert event["track"]["file"]["file"] and event["track"]["file"][
        "audio_url"
    ].startswith("/api/pia/music/files/")
    done = last(job, "done")
    assert done["result"] == {"track": event["track"], "history_id": "c-re"}
    (meta,) = sidecars(remote.output)
    assert meta["redownloaded"] is True and meta["origin"] is False
    assert meta["generation_id"] == gen["id"]
    item = next(i for i in _history(remote)["items"] if i["id"] == "c-re")
    assert item["tracks"][0]["availability"] == "local_file"
    assert_no_secrets(job.events, meta, remote.logs)


def test_item_deleted_on_another_pc_disappears_here_and_keeps_the_file(remote):
    """QA F1 (CA24/RN25): a2 baixou a faixa; a1 excluiu o item no servidor."""
    gen = remote.fake.add_generation(client_id="c-gone", device_id="device-b")
    job_id = web_api.route(
        "POST", "/music/history/c-gone/tracks/1/redownload", {}, {}, remote.context
    )["job_id"]
    assert wait_done(remote.context.jobs[job_id]).status == "done"
    (meta,) = sidecars(remote.output)
    assert any(i["id"] == "c-gone" for i in _history(remote)["items"])
    with remote.fake.lock:  # o outro PC excluiu (hard delete no servidor)
        remote.fake.generations[:] = [
            g for g in remote.fake.generations if g["id"] != gen["id"]
        ]
    assert all(i["id"] != "c-gone" for i in _history(remote)["items"])
    assert (remote.output / meta["file"]).is_file()
    assert any(item["file"] == meta["file"] for item in service.library())


def test_redownload_dead_track_reports_410_code(remote):
    gen = remote.fake.add_generation(client_id="c-dead")
    remote.fake.dead_tracks.add((gen["id"], 1))
    out = web_api.route(
        "POST", "/music/history/c-dead/tracks/1/redownload", {}, {}, remote.context
    )
    job = wait_done(remote.context.jobs[out["job_id"]])
    error = last(job, "error")
    assert error["code"] == "suno_track_unavailable"
    assert error["error"] == "Esta música não está mais disponível no Suno."
    assert not list(remote.output.glob("*.mp3"))


def test_redownload_rules_for_local_items(remote):
    remote.fake.add_generation(
        client_id="c-loc-b",
        device_id="device-b",
        source="local",
        provider="local",
        suno_account=None,
        tracks=[],
    )
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST", "/music/history/c-loc-b/tracks/1/redownload", {}, {}, remote.context
        )
    assert err.value.code == "not_origin_device"
    remote.fake.add_generation(
        client_id="c-loc-a",
        source="local",
        provider="local",
        suno_account=None,
        tracks=[],
    )
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST", "/music/history/c-loc-a/tracks/1/redownload", {}, {}, remote.context
        )
    assert err.value.code == "local_audio_missing"
    remote.fake.add_generation(client_id="c-s")
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST", "/music/history/c-s/tracks/9/redownload", {}, {}, remote.context
        )
    assert err.value.code == "track_not_found"
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST", "/music/history/nada/tracks/1/redownload", {}, {}, remote.context
        )
    assert err.value.code == "history_item_not_found"
    unpair(remote.profile)
    with pytest.raises(ValueError) as err:
        web_api.route(
            "POST", "/music/history/c-s/tracks/1/redownload", {}, {}, remote.context
        )
    assert err.value.code == "pia_server_unpaired"


def test_track_file_is_null_when_the_local_file_is_gone(remote):
    _gen, path = _downloaded_suno(remote, "c-gone")
    (item,) = _history(remote)["items"]
    assert item["tracks"][0]["availability"] == "local_file"
    assert item["tracks"][0]["file"]["file"] == path.name
    path.unlink()
    (item,) = _history(remote)["items"]
    assert item["tracks"][0]["file"] is None
    assert item["tracks"][0]["availability"] == "redownload"

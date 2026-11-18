"""Music history (T6, requisitos v3.1/v3.2).

* Local index ``OUTPUT/pia-generations-index.json`` linking each generation
  (``client_id``, server ``job_id``/``generation_id``) to its files in OUTPUT,
  with tombstones for items deleted on the server. Atomic writes under a
  lock; rebuilt from the ``.json`` sidecars when missing.
* Queue of local generation records (Local, Gemini...) for
  ``POST /device/music/generations``: ONLY while paired and offline, at most
  500 items / 30 days, oldest dropped (RN14). Not paired: nothing is sent or
  queued. The audio never goes up; prompts never go to a log.
* Merged, paginated history (server + index) and the delete/redownload
  lookups used by ``web_api``.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import quote

from Plugins.Apps.music import service
from Plugins.Connectors.pia_server import remote as device

INDEX_NAME = "pia-generations-index.json"
INDEX_VERSION = 1
PAGE_LIMIT = 100
QUEUE_MAX_ITEMS = 500
QUEUE_MAX_AGE = 30 * 24 * 3600
SERVER_LOOKUP_PAGES = 10
LOG_SECTION = "Apps/music"
PROVIDER_LABELS = {"local": "Local", "gemini": "Gemini", "suno_mcp": "Suno"}
_SIDECAR = re.compile(r"[a-f0-9]{32}\.(mp3|wav|flac)\.json")
_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def track_label(source: str, extra: bool = False, provider: str = "") -> str:
    if source == "suno":
        return "Suno · extra" if extra else "Suno"
    return PROVIDER_LABELS.get(provider, "Local")


# --- index ----------------------------------------------------------------------
def _path() -> Path:
    return service.output_directory() / INDEX_NAME


def _empty() -> dict[str, Any]:
    return {"version": INDEX_VERSION, "items": {}, "tombstones": {}}


def _write(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False)
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _rebuild() -> dict[str, Any]:
    """Index from the existing sidecars (legacy tracks included)."""
    data = _empty()
    root = service.output_directory()
    if not root.is_dir():
        return data
    for sidecar in sorted(root.glob("*.json")):
        if not _SIDECAR.fullmatch(sidecar.name):
            continue
        try:
            item = json.loads(sidecar.read_text(encoding="utf-8"))
            file = item["file"]
            if file != sidecar.name[:-5] or not (root / file).is_file():
                continue
            created = datetime.fromtimestamp(sidecar.stat().st_mtime, timezone.utc)
        except (ValueError, KeyError, OSError, TypeError):
            continue
        provider = str(item.get("provider") or "local")
        source = "suno" if provider == "suno_mcp" else "local"
        identity = str(item.get("client_id") or item.get("batch") or file)
        n = item.get("track_n") or item.get("variant") or 1
        entry = data["items"].setdefault(
            identity,
            {
                "id": identity,
                "job_id": None,
                "generation_id": item.get("generation_id"),
                "source": source,
                "provider": provider,
                "prompt": item.get("prompt") or "",
                "lyrics": item.get("lyrics") or "",
                "params": {
                    "provider": provider,
                    "duration": item.get("requested_duration"),
                },
                "count": 0,
                "state": "completed",
                "code": None,
                "suno_account": item.get("suno_account"),
                "created_at": created.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "origin": item.get("origin") is not False,
                "pending": False,
                "tracks": {},
            },
        )
        entry["tracks"][str(int(n))] = {
            "file": file,
            "title": item.get("title"),
            "duration": item.get("duration"),
            "extra": item.get("extra") is True,
        }
        entry["count"] = max(
            entry["count"], sum(1 for t in entry["tracks"].values() if not t["extra"])
        )
        entry["params"]["count"] = entry["count"]
    return data


def _load() -> dict[str, Any]:
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(data, dict)
            and data.get("version") == INDEX_VERSION
            and isinstance(data.get("items"), dict)
            and isinstance(data.get("tombstones"), dict)
        ):
            return data
    except (OSError, ValueError):
        pass
    data = _rebuild()
    try:
        _write(data)
    except OSError:
        pass
    return data


def _mutate(fn):
    with _lock:
        data = _load()
        result = fn(data)
        _write(data)
        return result


def record(identity: str, **fields: Any) -> dict[str, Any]:
    def change(data):
        entry = data["items"].get(identity) or {
            "id": identity,
            "job_id": None,
            "generation_id": None,
            "code": None,
            "suno_account": None,
            "created_at": now_iso(),
            "origin": True,
            "pending": False,
            "tracks": {},
        }
        entry.update(fields)
        data["items"][identity] = entry
        return dict(entry)

    return _mutate(change)


def update(identity: str, **fields: Any) -> dict[str, Any] | None:
    def change(data):
        entry = data["items"].get(identity)
        if entry is None:
            return None
        entry.update(fields)
        return dict(entry)

    return _mutate(change)


def add_track(
    identity: str, n: int, file: str, *, title=None, duration=None, extra=False
) -> None:
    def change(data):
        entry = data["items"].get(identity)
        if entry is None:
            return
        entry["tracks"][str(int(n))] = {
            "file": file,
            "title": title,
            "duration": duration,
            "extra": bool(extra),
        }

    _mutate(change)


def get(identity: str) -> dict[str, Any] | None:
    with _lock:
        entry = _load()["items"].get(identity)
        return json.loads(json.dumps(entry)) if entry else None


def find_job(server_job_id: str) -> dict[str, Any] | None:
    with _lock:
        for entry in _load()["items"].values():
            if entry.get("job_id") == server_job_id:
                return json.loads(json.dumps(entry))
    return None


def tombstone(identity: str) -> None:
    def change(data):
        data["tombstones"][identity] = now_iso()

    _mutate(change)


def entries() -> tuple[dict[str, Any], dict[str, Any]]:
    with _lock:
        data = _load()
        return json.loads(json.dumps(data["items"])), dict(data["tombstones"])


def pending_suno_jobs() -> list[dict[str, Any]]:
    items, tombstones = entries()
    return [
        e
        for e in items.values()
        if e.get("source") == "suno"
        and e.get("origin")
        and e.get("pending")
        and e.get("job_id")
        and e["id"] not in tombstones
    ]


def local_file(file: str | None) -> dict[str, Any] | None:
    """Same shape/identity as the items of ``library()`` (player, openFolder)."""
    if not file:
        return None
    try:
        path = service.audio_file(file)
        sidecar = path.with_name(path.name + ".json")
        item = json.loads(sidecar.read_text(encoding="utf-8"))
        if item.get("file") != file:
            return None
        return {**item, "modified": sidecar.stat().st_mtime}
    except (ValueError, OSError):
        return None


# --- local generation records (RN14) -------------------------------------------
TABLE = """CREATE TABLE IF NOT EXISTS pia_music_generation_queue(
    client_id TEXT PRIMARY KEY, device TEXT NOT NULL, payload TEXT NOT NULL,
    created REAL NOT NULL)"""


def _log(text: str) -> None:
    try:
        from src.plugin_logs import write

        write(LOG_SECTION, "histórico", text)  # never the prompt
    except Exception:
        pass


def _device_key() -> str | None:
    from src.settings_store import values
    from Plugins.Connectors.pia_server.media import device_key

    if not device.device_paired():
        return None
    return device_key(values(device.SECTION))


def _queue(client_id: str, key: str, payload: dict[str, Any]) -> None:
    from src.settings_store import get_store

    with get_store().connection() as db:
        db.execute(TABLE)
        db.execute(
            "INSERT OR REPLACE INTO pia_music_generation_queue(client_id,device,payload,created) "
            "VALUES(?,?,?,?)",
            (client_id, key, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        db.execute(
            "DELETE FROM pia_music_generation_queue WHERE created<?",
            (time.time() - QUEUE_MAX_AGE,),
        )
        db.execute(
            "DELETE FROM pia_music_generation_queue WHERE device=? AND client_id NOT IN "
            "(SELECT client_id FROM pia_music_generation_queue WHERE device=? "
            "ORDER BY created DESC, rowid DESC LIMIT ?)",
            (key, key, QUEUE_MAX_ITEMS),
        )


def queued_ids() -> list[str]:
    from src.settings_store import get_store

    key = _device_key()
    if key is None:
        return []
    with get_store().connection() as db:
        db.execute(TABLE)
        return [
            r[0]
            for r in db.execute(
                "SELECT client_id FROM pia_music_generation_queue WHERE device=? ORDER BY created, rowid",
                (key,),
            ).fetchall()
        ]


def _unqueue(client_id: str) -> None:
    from src.settings_store import get_store

    with get_store().connection() as db:
        db.execute(TABLE)
        db.execute(
            "DELETE FROM pia_music_generation_queue WHERE client_id=?", (client_id,)
        )


def _send(payload: dict[str, Any]) -> str:
    try:
        result = device.device_call("POST", "music/generations", payload)
    except device.DeviceApiError as exc:
        if exc.code == "pia_server_unreachable":
            return "offline"
        _log("Registro de geração recusado pela PIA Server.")
        return "dropped"
    server_id = result.get("id")
    if isinstance(server_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", server_id):
        update(payload["client_id"], generation_id=server_id)
    return "sent"


def record_local_generation(entry: dict[str, Any]) -> str:
    """Send one local generation record: ``sent``, ``queued``, ``unpaired``
    or ``dropped``. Never raises and never blocks the generation itself."""
    try:
        key = _device_key()
        if key is None:
            return "unpaired"  # RN14: nothing sent, nothing queued
        params = entry.get("params") or {}
        payload = {
            "source": "local",
            "provider": entry.get("provider"),
            "client_id": entry["id"],
            "prompt": entry.get("prompt") or "",
            "lyrics": entry.get("lyrics") or "",
            "count": entry.get("count"),
            "duration": params.get("duration"),
            "state": entry.get("state"),
            "code": entry.get("code"),
            "created": entry.get("created_at"),
        }
        flush_pending()
        outcome = _send(payload)
        if outcome == "offline":
            _queue(entry["id"], key, payload)
            _log("Registro de geração pendente; será enviado quando a conexão voltar.")
            return "queued"
        return outcome
    except Exception:
        _log("Não foi possível registrar a geração na PIA Server.")
        return "dropped"


def flush_pending() -> int:
    """Resend queued records, oldest first; stops at the first offline."""
    from src.settings_store import get_store

    key = _device_key()
    if key is None:
        return 0
    store = get_store()
    with store.connection() as db:
        db.execute(TABLE)
        db.execute(
            "DELETE FROM pia_music_generation_queue WHERE created<?",
            (time.time() - QUEUE_MAX_AGE,),
        )
        rows = db.execute(
            "SELECT client_id,payload FROM pia_music_generation_queue WHERE device=? "
            "ORDER BY created, rowid",
            (key,),
        ).fetchall()
    sent = 0
    for client_id, raw in rows:
        outcome = _send(json.loads(raw))
        if outcome == "offline":
            break
        _unqueue(client_id)
        sent += outcome == "sent"
    return sent


# --- merged history --------------------------------------------------------------
_server_ids: dict[str, str] = {}  # local item id -> server generation id
_server_ids_lock = threading.Lock()


def _encode_cursor(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode_cursor(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        text = str(raw)
        value = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    raise ValueError("Cursor inválido.")


def _active_job_id(entry: dict[str, Any] | None) -> str | None:
    from Plugins.Apps.music import remote_suno

    if entry and entry.get("job_id"):
        job = remote_suno.mirror_for(entry["job_id"])
        return job.id if job is not None else None
    return None


def _tracks(source, provider, this_device, server_tracks, count, local_entry):
    local_tracks = (local_entry or {}).get("tracks") or {}
    merged: dict[int, dict[str, Any]] = {}
    for track in server_tracks or []:
        if isinstance(track, dict) and type(track.get("n")) is int:
            merged[track["n"]] = {
                "title": track.get("title"),
                "duration": track.get("duration"),
                "extra": track.get("extra") is True,
            }
    for n, track in local_tracks.items():
        current = merged.setdefault(
            int(n),
            {
                "title": track.get("title"),
                "duration": track.get("duration"),
                "extra": track.get("extra") is True,
            },
        )
        current["file_name"] = track.get("file")
    if not merged and source == "local":
        merged = {
            n: {"title": None, "duration": None, "extra": False}
            for n in range(1, (count or 0) + 1)
        }
    out = []
    for n in sorted(merged):
        track = merged[n]
        file = local_file(track.pop("file_name", None))
        item = {
            "n": n,
            "title": track["title"],
            "duration": track["duration"],
            "extra": track["extra"],
            "label": track_label(source, track["extra"], provider),
        }
        # ``file``: the library item with local_file, otherwise null.
        item["file"] = file
        if file:
            item["availability"] = "local_file"
        elif source == "suno":
            item["availability"] = "redownload"
        elif not this_device:
            item["availability"] = "other_device_local"
        else:
            # Local audio of THIS PC that is gone: no action (contract gap).
            item["availability"] = None
        out.append(item)
    return out


def _from_local(entry: dict[str, Any]) -> dict[str, Any]:
    params = dict(entry.get("params") or {})
    return {
        "id": entry["id"],
        "job_id": _active_job_id(entry),
        "provider": entry.get("provider"),
        "source": entry.get("source"),
        "suno_account": entry.get("suno_account"),
        "prompt": entry.get("prompt") or "",
        "lyrics": entry.get("lyrics") or "",
        "params": params,
        "created_at": entry.get("created_at"),
        "state": entry.get("state"),
        "code": entry.get("code"),
        "count": entry.get("count"),
        "this_device": entry.get("origin") is not False,
        "tracks": _tracks(
            entry.get("source"),
            entry.get("provider"),
            entry.get("origin") is not False,
            None,
            entry.get("count"),
            entry,
        ),
    }


def _from_server(
    raw: dict[str, Any], local: dict[str, Any] | None
) -> dict[str, Any] | None:
    server_id = raw.get("id")
    if not isinstance(server_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,64}", server_id
    ):
        return None
    identity = str(raw.get("client_id") or server_id)
    with _server_ids_lock:
        if len(_server_ids) > 5000:
            _server_ids.clear()
        _server_ids[identity] = server_id
    source = "suno" if raw.get("source") == "suno" else "local"
    provider = str(raw.get("provider") or ("suno_mcp" if source == "suno" else "local"))
    account = (
        raw.get("suno_account") if isinstance(raw.get("suno_account"), dict) else None
    )
    this_device = raw.get("from_this_device") is True or bool(
        local and local.get("origin")
    )
    params = dict((local or {}).get("params") or {})
    params.setdefault("provider", provider)
    if raw.get("duration") is not None:
        params.setdefault("duration", raw.get("duration"))
    if raw.get("count") is not None:
        params.setdefault("count", raw.get("count"))
    if account and source == "suno":
        params.setdefault("suno_account_id", account.get("id"))
    return {
        "id": identity,
        "job_id": _active_job_id(local),
        "provider": provider,
        "source": source,
        "suno_account": {"id": account.get("id"), "name": account.get("name")}
        if account
        else None,
        "prompt": raw.get("prompt") or "",
        "lyrics": raw.get("lyrics") or "",
        "params": params,
        "created_at": raw.get("created"),
        "state": raw.get("state"),
        "code": raw.get("code"),
        "count": raw.get("count"),
        "this_device": this_device,
        "tracks": _tracks(
            source, provider, this_device, raw.get("tracks"), raw.get("count"), local
        ),
    }


def _sort_key(item: dict[str, Any]):
    running = item.get("state") in ("queued", "running")
    return (0 if running else 1, _neg(item.get("created_at") or ""))


def _neg(text: str):
    # Descending order on ISO strings without parsing them.
    return tuple(-ord(ch) for ch in text)


def _local_items(tombstones, exclude=()) -> list[dict[str, Any]]:
    items, _ = entries()
    out = [
        _from_local(e)
        for e in items.values()
        if e["id"] not in tombstones and e["id"] not in exclude
    ]
    return sorted(out, key=_sort_key)


def list_history(cursor: Any = None, limit: Any = PAGE_LIMIT) -> dict[str, Any]:
    try:
        limit = max(1, min(PAGE_LIMIT, int(limit or PAGE_LIMIT)))
    except (TypeError, ValueError):
        raise ValueError("Limite inválido.") from None
    state = _decode_cursor(cursor)
    local_entries, tombstones = entries()
    reason = None
    if not device.device_paired():
        reason = "pia_server_unpaired"
    elif "o" not in state:
        flush_pending()
        query = f"music/generations?limit={limit}"
        if state.get("s"):
            query += "&cursor=" + quote(str(state["s"]), safe="")
        try:
            page = device.device_call("GET", query)
        except device.DeviceApiError as exc:
            reason = (
                "pia_server_unpaired"
                if exc.code == "pia_server_unpaired"
                else "pia_server_unreachable"
            )
        else:
            raw_items = [r for r in page.get("items") or [] if isinstance(r, dict)]
            items = []
            for raw in raw_items:
                identity = str(raw.get("client_id") or raw.get("id") or "")
                if identity in tombstones:
                    continue
                item = _from_server(raw, local_entries.get(identity))
                if item:
                    items.append(item)
            seen = {str(r.get("client_id") or r.get("id") or "") for r in raw_items}
            next_server = page.get("next_cursor")
            oldest = min((i["created_at"] or "" for i in items), default="")
            upper = state.get("b")
            # Local-only items (queued, never sent, legacy) between the previous
            # page boundary and this one; all the rest on the last page.
            # An entry that already has a server id (synced or re-downloaded)
            # is the server's: if it is not listed, it was deleted, possibly on
            # another PC (CA24/RN25). Hide it; the file stays in the folder.
            synced = {e["id"] for e in local_entries.values() if e.get("generation_id")}
            extra = [
                i
                for i in _local_items(
                    tombstones, exclude=seen | synced | set(state.get("x") or [])
                )
                if (upper is None or (i["created_at"] or "") < upper)
                and (not next_server or (i["created_at"] or "") >= oldest)
            ]
            merged = sorted(items + extra, key=_sort_key)
            next_cursor = None
            if next_server:
                next_cursor = _encode_cursor({"s": next_server, "b": oldest})
            return {
                "items": merged,
                "next_cursor": next_cursor,
                "server_unavailable": False,
                "server_reason": None,
            }
    offset = int(state.get("o") or 0)
    local = [i for i in _local_items(tombstones)]
    page = local[offset : offset + limit]
    next_cursor = (
        _encode_cursor({"o": offset + limit}) if offset + limit < len(local) else None
    )
    return {
        "items": page,
        "next_cursor": next_cursor,
        "server_unavailable": True,
        "server_reason": reason,
    }


def server_item(identity: str) -> dict[str, Any] | None:
    """Find the server item of a local id (cache, index, then a bounded scan)."""
    cursor = None
    for _ in range(SERVER_LOOKUP_PAGES):
        query = f"music/generations?limit={PAGE_LIMIT}"
        if cursor:
            query += "&cursor=" + quote(str(cursor), safe="")
        page = device.device_call("GET", query)
        for raw in page.get("items") or []:
            if isinstance(raw, dict) and identity in (
                raw.get("client_id"),
                raw.get("id"),
            ):
                return raw
        cursor = page.get("next_cursor")
        if not cursor:
            return None
    return None


def server_id_for(identity: str) -> str | None:
    with _server_ids_lock:
        cached = _server_ids.get(identity)
    if cached:
        return cached
    entry = get(identity)
    if entry and entry.get("generation_id"):
        return entry["generation_id"]
    raw = server_item(identity)
    if raw and isinstance(raw.get("id"), str):
        return raw["id"]
    return None


class HistoryError(ValueError):
    """400 {error, code} of the history routes. Codes outside the server
    contract (documented in docs/PLATFORM_SERVICES.md): history_item_not_found,
    track_not_found, local_audio_missing."""

    def __init__(self, code: str, message: str):
        if code == "pia_server_error":  # internal fallback, not a contract code
            code, message = "pia_server_unreachable", device.UNREACHABLE_MESSAGE
        super().__init__(message)
        self.code = code


def delete(identity: str) -> dict[str, Any]:
    """Hard delete on the server (proxy); NEVER removes the local file.
    Success writes a tombstone so the item does not come back from OUTPUT."""
    from Plugins.Apps.music.remote_suno import MESSAGES

    if not device.device_paired():
        raise HistoryError("pia_server_unpaired", MESSAGES["pia_server_unpaired"])
    if identity in queued_ids():
        _unqueue(identity)
        tombstone(identity)
        return {"ok": True, "id": identity}
    try:
        server_id = server_id_for(identity)
        if server_id is None:
            if get(identity) is None:
                raise HistoryError(
                    "history_item_not_found", "Item do histórico não encontrado."
                )
            # Never reached the server (e.g. generated while unpaired): hide it.
        else:
            device.device_call("DELETE", f"music/generations/{server_id}")
    except device.DeviceApiError as exc:
        if exc.status != 404:
            raise HistoryError(exc.code, MESSAGES.get(exc.code) or str(exc)) from None
    tombstone(identity)
    with _server_ids_lock:
        _server_ids.pop(identity, None)
    return {"ok": True, "id": identity}

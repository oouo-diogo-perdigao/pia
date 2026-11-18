import re
import threading
import uuid
from src.pia.service import Job
from Plugins.Apps.music import history
from Plugins.Apps.music import remote_suno
from Plugins.Apps.music import service
from Plugins.Connectors.pia_server import remote as pia_device

_latest = None
_job_lock = threading.Lock()

# CEO decision 1 (CA07): publish a notification for a partial batch (k >= 1).
PARTIAL_BATCH_NOTIFICATION = True
UNEXPECTED_ERROR_MESSAGE = "Falha ao gerar a música."
_FRIENDLY_ERRORS = (RuntimeError, ValueError, OSError)
GENERATE_KEYS = frozenset(
    {
        "prompt",
        "lyrics",
        "provider",
        "duration",
        "count",
        "suno_account_id",
        "instrumental",
    }
)
_LOCAL_ONLY_KEYS = ("count", "suno_account_id", "instrumental")
MAX_RESUMED_JOBS = 5


def error_code(exc: BaseException) -> str:
    """Stable ``code`` of a job error event (cancelled, suno_*, error...)."""
    if isinstance(exc, InterruptedError):
        return "cancelled"
    return str(getattr(exc, "code", None) or "error")


def friendly_error(exc: BaseException, extra=()) -> str:
    """RN06 message for ``event.error``: no "k de N" suffix, no secrets."""
    if isinstance(exc, _FRIENDLY_ERRORS):
        text = service.redact_secrets(str(exc), extra).strip()
        if text:
            return text
    return UNEXPECTED_ERROR_MESSAGE


def partial_notification_text(completed: int, total: int) -> str:
    """ "k de N músicas prontas (geração interrompida)" (singular by total)."""
    return f"{service.tracks_ready_text(completed, total)} (geração interrompida)"


def success_notification_text(completed: int, extra: int = 0) -> str:
    """RN12: "3 música(s) gerada(s) (+1 extra)."."""
    suffix = f" (+{extra} extra)" if extra else ""
    return f"{completed} música(s) gerada(s){suffix}."


def _split(items):
    regular = sum(1 for item in items if not item.get("extra"))
    return regular, len(items) - regular


# --- catalog / resume ----------------------------------------------------------
def providers(context=None):
    catalog = service.providers_catalog()
    active_id = resume(context)
    if active_id:
        for item in catalog["providers"]:
            if item.get("id") == "suno_mcp" and item.get("active_job"):
                item["active_job"]["job_id"] = active_id
    return catalog


def suno_status(context=None):
    remote_suno.invalidate_status()
    item = remote_suno.suno_item(remote_suno.remote_status(fresh=True))
    active_id = resume(context)
    if active_id and item.get("active_job"):
        item["active_job"]["job_id"] = active_id
    return item


def _start_remote(context, runner, data):
    job = Job()
    if not remote_suno.register_mirror(runner.server_job_id, job):
        return remote_suno.mirror_for(runner.server_job_id)
    context.jobs[job.id] = job
    threading.Thread(
        target=_run_job,
        args=(job, context, "generate", "suno_mcp", data, runner.count, runner),
        daemon=True,
        name="pia-music",
    ).start()
    return job


def resume(context):
    """Reopen: mirror the active job of THIS PC (watchJob id) and finish the
    downloads still pending in the local index. Returns the local id of the
    active job's mirror, or None. Never raises."""
    if context is None or not hasattr(context, "jobs"):
        return None
    try:
        status = remote_suno.remote_status()
        active = status.get("active_job")
        targets = []
        if active and active["this_device"]:
            targets.append(remote_suno.RemoteJob.resume(active))
        for entry in history.pending_suno_jobs():
            if active and entry["job_id"] == active["server_job_id"]:
                continue
            targets.append(remote_suno.RemoteJob(entry))
        active_id = None
        for runner in targets[:MAX_RESUMED_JOBS]:
            job = remote_suno.mirror_for(runner.server_job_id)
            if job is None:
                entry = runner.entry
                params = entry.get("params") or {}
                job = _start_remote(
                    context,
                    runner,
                    {
                        "prompt": entry.get("prompt") or "",
                        "lyrics": entry.get("lyrics") or "",
                        "duration": params.get("duration"),
                        "provider": "suno_mcp",
                    },
                )
            if active and runner.server_job_id == active["server_job_id"] and job:
                active_id = job.id
        return active_id
    except Exception:
        return None


# --- redownload (RN16, v3.1/v3.2) ----------------------------------------------
def redownload(identity, n, context):
    job = remote_suno.redownload_job(identity, n)
    if job is not None:
        return {"job_id": job.id}
    if not pia_device.device_paired():
        raise remote_suno.RemoteMusicError("pia_server_unpaired")
    local = history.get(identity)
    raw = None
    try:
        if local is None or local.get("source") == "suno":
            raw = history.server_item(identity)
    except pia_device.DeviceApiError as exc:
        raise remote_suno.remote_error(exc) from None
    if local is None and raw is None:
        raise history.HistoryError(
            "history_item_not_found", "Item do histórico não encontrado."
        )
    source = (local or {}).get("source") or (
        "suno" if (raw or {}).get("source") == "suno" else "local"
    )
    if source != "suno":
        this_device = (
            bool(local and local.get("origin") is not False)
            or (raw or {}).get("from_this_device") is True
        )
        if not this_device:
            raise history.HistoryError(
                "not_origin_device",
                "O áudio desta geração local está no computador que a gerou.",
            )
        raise history.HistoryError(
            "local_audio_missing",
            "O áudio desta geração local não está mais neste computador.",
        )
    tracks = {
        t["n"]: t
        for t in (raw or {}).get("tracks") or []
        if isinstance(t, dict) and type(t.get("n")) is int
    }
    for key, track in ((local or {}).get("tracks") or {}).items():
        tracks.setdefault(int(key), {"n": int(key), **track})
    if n not in tracks:
        raise history.HistoryError("track_not_found", "Faixa não encontrada.")
    generation = (raw or {}).get("id") or (local or {}).get("generation_id")
    generation = remote_suno.safe_id(generation)
    if local is None:
        account = (
            raw.get("suno_account")
            if isinstance(raw.get("suno_account"), dict)
            else None
        )
        local = history.record(
            identity,
            source="suno",
            provider="suno_mcp",
            prompt=raw.get("prompt") or "",
            lyrics=raw.get("lyrics") or "",
            params={
                "provider": "suno_mcp",
                "duration": raw.get("duration"),
                "count": raw.get("count"),
                "suno_account_id": (account or {}).get("id"),
            },
            count=raw.get("count"),
            state=raw.get("state"),
            code=raw.get("code"),
            generation_id=generation,
            suno_account=account,
            created_at=raw.get("created") or history.now_iso(),
            origin=raw.get("from_this_device") is True,
        )
    elif not local.get("generation_id"):
        local = history.update(identity, generation_id=generation)
    job = Job()
    winner = remote_suno.claim_redownload(identity, n, job)
    if winner is not job:
        return {"job_id": winner.id}
    context.jobs[job.id] = job
    track = dict(tracks[n])

    def worker():
        try:
            path = remote_suno.download_track(
                generation, n, cancelled=job.cancelled.is_set
            )
            item = remote_suno.save_track(
                path, local, track, variant=n, redownloaded=True
            )
            payload = {
                "n": n,
                "title": item.get("title"),
                "duration": item.get("duration"),
                "extra": item["extra"],
                "label": item["label"],
                "availability": "local_file",
                "file": history.local_file(path.name),
            }
            job.emit("track", item=payload["file"], track=payload, history_id=identity)
            job.emit("done", result={"track": payload, "history_id": identity})
        except Exception as exc:
            job.emit("error", error=friendly_error(exc), code=error_code(exc))

    threading.Thread(target=worker, daemon=True, name="pia-music").start()
    return {"job_id": job.id}


# --- local routes (/api/pia/music/...) -------------------------------------------
_ATTEMPT = re.compile(r"/music/suno/connect/([A-Za-z0-9_-]{1,64})")
_RENAME = re.compile(r"/music/suno/accounts/([A-Za-z0-9_-]{1,64})/rename")
_HISTORY_ITEM = re.compile(r"/music/history/([A-Za-z0-9_-]{1,64})")
_REDOWNLOAD = re.compile(
    r"/music/history/([A-Za-z0-9_-]{1,64})/tracks/(\d{1,3})/redownload"
)


def route(method, path, data, query, context):
    """Every /music/* route except the T8 /music/suno/legacy-credentials*."""
    query = query or {}
    data = data or {}
    if path == "/music/providers" and method == "GET":
        return providers(context)
    if path == "/music/select" and method == "POST":
        # T9: the Suno account goes only in generate. Other keys (an old body
        # with suno_account_id, the removed suno_mcp_token...) are ignored,
        # as before: nothing is saved for them.
        return service.select_provider(
            provider=data.get("provider"),
            gemini_model=data.get("gemini_model"),
        )
    if path == "/music/suno/status" and method == "GET":
        return suno_status(context)
    if path == "/music/suno/connect" and method == "POST":
        return remote_suno.connect(data)
    match = _ATTEMPT.fullmatch(path)
    if match and method == "GET":
        return remote_suno.connect_attempt(match[1])
    if path == "/music/suno/disconnect" and method == "POST":
        return remote_suno.disconnect(data)
    match = _RENAME.fullmatch(path)
    if match and method == "POST":
        return remote_suno.rename(match[1], data)
    if path == "/music/history" and method == "GET":
        return history.list_history(
            (query.get("cursor") or [None])[0],
            (query.get("limit") or [history.PAGE_LIMIT])[0],
        )
    match = _HISTORY_ITEM.fullmatch(path)
    if match and method == "DELETE":
        return history.delete(match[1])
    match = _REDOWNLOAD.fullmatch(path)
    if match and method == "POST":
        return redownload(match[1], int(match[2]), context)
    raise ValueError("Operação musical desconhecida.")


# --- job worker -----------------------------------------------------------------
def _record_local(provider, data, count, client_id, items, state, code):
    """Local index + RN14 record (prompt never logged)."""
    try:
        entry = history.record(
            client_id,
            source="local",
            provider=provider,
            prompt=data.get("prompt") or "",
            lyrics=data.get("lyrics") or "",
            params={
                "provider": provider,
                "duration": data.get("duration", 30),
                "count": count,
            },
            count=count,
            state=state,
            code=code,
        )
        for item in items:
            history.add_track(client_id, item.get("variant") or 1, item["file"])
        history.record_local_generation(entry)
    except Exception:
        pass


def _run_job(job, context, action, provider, data, count, runner=None):
    suno = provider == "suno_mcp"
    known = service.suno_known_secrets() if suno else []
    connection = {"value": "ok"}

    def report(text):
        secrets = known
        if suno:
            # Re-read on every log: a refresh may rotate the tokens.
            secrets = service.suno_known_secrets()
        job.emit("log", text=service.redact_secrets(text, secrets))

    items = []
    client_id = str(uuid.uuid4())

    def progress(completed, label, state="running"):
        value = {
            "percent": completed / count * 100,
            "completed": completed,
            "total": count,
            "label": label,
            "state": state,
        }
        if suno:
            _regular, extra = _split(items)
            value.update(
                extra_ready=extra,
                ready_text=remote_suno.ready_text(completed, count, extra),
                connection=connection["value"],
            )
        job.emit("progress", value=value)

    try:
        if action == "prepare-local":
            result = service.prepare(report)
        elif suno:
            progress(0, f"Gerando música 1/{count}")

            def on_track(item, completed=None, total=None):
                items.append(item)
                job.emit("track", item=item)
                done, _extra = _split(items)
                progress(
                    done,
                    "Músicas concluídas"
                    if done >= count
                    else f"Gerando música {done + 1}/{count}",
                    "completed" if done >= count else "running",
                )

            def on_progress(value):
                connection["value"] = value.get("connection", "ok")
                job.emit("progress", value=value)

            service.generate_suno_batch(
                prompt=data.get("prompt"),
                lyrics=data.get("lyrics", ""),
                duration=data.get("duration", 30),
                count=count,
                progress=report,
                cancelled=job.cancelled.is_set,
                cancel_event=job.cancelled,
                on_track=on_track,
                on_progress=on_progress,
                runner=runner,
            )
            batch = items[0].get("batch") if items else uuid.uuid4().hex
            result = {"items": items, "batch": batch}
        else:
            group = uuid.UUID(client_id).hex
            arguments = {
                key: value for key, value in data.items() if key not in _LOCAL_ONLY_KEYS
            }
            for index in range(count):
                if job.cancelled.is_set():
                    raise InterruptedError(
                        "Geração cancelada; músicas concluídas foram preservadas."
                    )
                progress(index, f"Gerando música {index + 1}/{count}")
                item = service.generate(
                    **arguments, progress=report, cancelled=job.cancelled.is_set
                )
                item["batch"] = group
                item["variant"] = index + 1
                if action == "generate":
                    item["client_id"] = client_id
                service.save_json(
                    service.audio_file(item["file"]).with_name(item["file"] + ".json"),
                    item,
                )
                items.append(item)
                job.emit("track", item=item)
                progress(
                    index + 1,
                    "Músicas concluídas",
                    "completed" if index + 1 == count else "running",
                )
            result = {"items": items, "batch": group}
        if action == "generate" and hasattr(context, "publish_notification"):
            regular, extra = _split(items) if suno else (len(items), 0)
            context.publish_notification(
                "Apps/music",
                "Músicas prontas",
                success_notification_text(regular, extra),
            )
        job.emit("done", result=result)
        if action == "generate" and not suno:
            _record_local(provider, data, count, client_id, items, "completed", None)
    except Exception as exc:
        if suno:
            # Re-read: a token refreshed during the job must not leak.
            known = service.suno_known_secrets()
        message = friendly_error(exc, known)
        if not isinstance(exc, _FRIENDLY_ERRORS):
            # Detail only in the (redacted) log; event.error stays friendly.
            report(f"{type(exc).__name__}: {exc}")
        if action != "generate":
            job.emit("error", error=message, code=error_code(exc))
            return
        # Tracks saved before the failure stay on disk and in the history.
        regular, extra = _split(items) if suno else (len(items), 0)
        completed = getattr(exc, "completed", None)
        if type(completed) is not int:
            completed = regular
        completed = max(completed, regular)
        total = getattr(exc, "total", None)
        if type(total) is not int or total < 1:
            total = count
        ready = (
            remote_suno.ready_text(completed, total, extra)
            if suno
            else service.tracks_ready_text(completed, total)
        )
        # The worker marks the batch as interrupted; the Panel builds
        # its status line from completed/total.
        value = {
            "percent": completed / total * 100,
            "completed": completed,
            "total": total,
            "label": "Geração interrompida",
            "state": "interrupted",
            "ready_text": ready,
        }
        if suno:
            value.update(extra_ready=extra, connection=connection["value"])
        job.emit("progress", value=value)
        if (
            PARTIAL_BATCH_NOTIFICATION
            and completed >= 1
            and hasattr(context, "publish_notification")
        ):
            context.publish_notification(
                "Apps/music",
                "Músicas prontas",
                partial_notification_text(completed, total),
            )
        job.emit(
            "error",
            error=message,
            code=error_code(exc),
            completed=completed,
            total=total,
            ready_text=ready,
        )
        if not suno:
            if isinstance(exc, InterruptedError):
                state = "cancelled"
            else:
                state = "interrupted" if completed else "failed"
            _record_local(
                provider, data, count, client_id, items, state, error_code(exc)
            )


def handle(action, data, context):
    global _latest
    if action == "providers":
        return providers(context)
    if action == "select":
        return route("POST", "/music/select", data, {}, context)
    if action == "library":
        running = _latest if _latest and _latest.status == "running" else None
        running = running or remote_suno.running_mirror()
        return {
            "items": service.library(),
            "folder": str(service.output_directory()),
            "installed": (service.CACHE / "ace-step/.venv").is_dir(),
            "job": running.id if running else None,
        }
    if action == "cancel":
        context.jobs[data["job"]].cancelled.set()
        return {"ok": True}
    if action not in ("generate", "prepare-local"):
        raise ValueError("Operação musical desconhecida.")
    if action == "generate" and set(data) - GENERATE_KEYS:
        raise ValueError("Parâmetros musicais desconhecidos.")
    count = data.get("count", 1)
    if type(count) is not int or not 1 <= count <= 10:
        raise ValueError("Escolha de 1 a 10 músicas.")
    provider = None
    account = None
    if action == "generate":
        # Provider omitted => the saved MUSIC_PROVIDER (Q5).
        provider = service.resolve_music_provider(data.get("provider"))
        if provider == "suno_mcp":
            # Refused before any Job exists (no job, no credits): 400 {code}.
            refusal = service.suno_job_refusal()
            if refusal is not None:
                raise refusal
            account = service.suno_job_account(data.get("suno_account_id"))
    runner = None
    with _job_lock:
        if (_latest and _latest.status == "running") or remote_suno.running_mirror():
            raise ValueError("Já há uma tarefa musical em andamento.")
        if provider == "suno_mcp":
            # Server job created synchronously: 409 suno_job_active etc. come
            # back as 400 {error, code} without a local job.
            runner = service.suno_backend().create(data, account)
        job = Job()
        context.jobs[job.id] = job
        _latest = job
        if runner is not None:
            remote_suno.register_mirror(runner.server_job_id, job)

    threading.Thread(
        target=_run_job,
        args=(job, context, action, provider, data, count, runner),
        daemon=True,
        name="pia-music",
    ).start()
    return {"job": job.id}

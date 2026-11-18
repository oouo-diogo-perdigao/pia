import threading
import uuid
from src.pia.service import Job
from Plugins.Apps.music import service

_latest = None
_job_lock = threading.Lock()

# CEO decision 1 (CA07): publish a notification for a partial batch (k >= 1).
PARTIAL_BATCH_NOTIFICATION = True
UNEXPECTED_ERROR_MESSAGE = "Falha ao gerar a música."
_FRIENDLY_ERRORS = (RuntimeError, ValueError, OSError)


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


def handle(action, data, context):
    global _latest
    if action == "providers":
        return service.providers_catalog()
    if action == "select":
        return service.select_provider(
            provider=data.get("provider"),
            gemini_model=data.get("gemini_model"),
        )
    if action == "library":
        return {
            "items": service.library(),
            "folder": str(service.output_directory()),
            "installed": (service.CACHE / "ace-step/.venv").is_dir(),
            "job": _latest.id if _latest and _latest.status == "running" else None,
        }
    if action == "cancel":
        context.jobs[data["job"]].cancelled.set()
        return {"ok": True}
    if action not in ("generate", "prepare-local"):
        raise ValueError("Operação musical desconhecida.")
    if action == "generate" and set(data) - {
        "prompt",
        "lyrics",
        "provider",
        "duration",
        "count",
    }:
        raise ValueError("Parâmetros musicais desconhecidos.")
    count = data.get("count", 1)
    if type(count) is not int or not 1 <= count <= 10:
        raise ValueError("Escolha de 1 a 10 músicas.")
    provider = None
    if action == "generate":
        # Provider omitted => the saved MUSIC_PROVIDER (Q5).
        provider = service.resolve_music_provider(data.get("provider"))
        if provider == "suno_mcp":
            refusal = service.suno_job_refusal()
            if refusal is not None:
                # Refused before any Job exists (no job, no credits).
                raise refusal
    with _job_lock:
        if _latest and _latest.status == "running":
            raise ValueError("Já há uma tarefa musical em andamento.")
        job = Job()
        context.jobs[job.id] = job
        _latest = job

    def worker():
        known = service.suno_known_secrets() if provider == "suno_mcp" else []

        def report(text):
            secrets = known
            if provider == "suno_mcp":
                # Re-read on every log: a refresh may rotate the tokens.
                secrets = service.suno_known_secrets()
            job.emit("log", text=service.redact_secrets(text, secrets))

        items = []

        def progress(completed, label, state="running"):
            job.emit(
                "progress",
                value={
                    "percent": completed / count * 100,
                    "completed": completed,
                    "total": count,
                    "label": label,
                    "state": state,
                },
            )

        try:
            if action == "prepare-local":
                result = service.prepare(report)
            elif provider == "suno_mcp":
                progress(0, f"Gerando música 1/{count}")

                def on_track(item, completed=None, total=None):
                    items.append(item)
                    job.emit("track", item=item)
                    done = len(items)
                    progress(
                        done,
                        "Músicas concluídas"
                        if done == count
                        else f"Gerando música {done + 1}/{count}",
                        "completed" if done == count else "running",
                    )

                service.generate_suno_batch(
                    prompt=data.get("prompt"),
                    lyrics=data.get("lyrics", ""),
                    duration=data.get("duration", 30),
                    count=count,
                    progress=report,
                    cancelled=job.cancelled.is_set,
                    cancel_event=job.cancelled,
                    on_track=on_track,
                )
                batch = items[0].get("batch") if items else uuid.uuid4().hex
                result = {"items": items, "batch": batch}
            else:
                group = uuid.uuid4().hex
                arguments = {
                    key: value for key, value in data.items() if key != "count"
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
                    service.save_json(
                        service.audio_file(item["file"]).with_name(
                            item["file"] + ".json"
                        ),
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
                context.publish_notification(
                    "Apps/music",
                    "Músicas prontas",
                    f"{len(items)} música(s) gerada(s).",
                )
            job.emit("done", result=result)
        except Exception as exc:
            if provider == "suno_mcp":
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
            completed = getattr(exc, "completed", None)
            if type(completed) is not int:
                completed = len(items)
            completed = max(completed, len(items))
            total = getattr(exc, "total", None)
            if type(total) is not int or total < 1:
                total = count
            ready = service.tracks_ready_text(completed, total)
            # The worker marks the batch as interrupted; the Panel builds
            # its status line from completed/total.
            job.emit(
                "progress",
                value={
                    "percent": completed / total * 100,
                    "completed": completed,
                    "total": total,
                    "label": "Geração interrompida",
                    "state": "interrupted",
                    "ready_text": ready,
                },
            )
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

    threading.Thread(target=worker, daemon=True, name="pia-music").start()
    return {"job": job.id}

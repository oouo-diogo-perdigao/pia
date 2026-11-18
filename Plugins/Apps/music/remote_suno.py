"""Suno through the PIA Server (T6, contrato v3 final).

The Suno token and OAuth live ONLY on the pia-server. This module asks the
server for the status/accounts, connects and disconnects accounts, creates a
job, follows it (polling with offline backoff) and downloads every ready
track through the server proxy into ``OUTPUT``. No Suno token, audio link or
prompt is ever written to a log.
"""

from __future__ import annotations

from hashlib import sha256
import os
import re
import threading
import time
from typing import Any
import uuid

from Plugins.Connectors.pia_server import remote as device
from Plugins.Apps.music import history
from Plugins.Apps.music import service

CAPABILITY = "suno:3"
STATUS_TTL = 15.0  # RN05: short cache (<= 30 s)
POLL_INTERVAL = 3.0
OFFLINE_BACKOFF_MIN = 5.0  # decision 4: 5 s .. 60 s while offline
OFFLINE_BACKOFF_MAX = 60.0
WAIT_SLICE = 0.25
DOWNLOAD_TIMEOUT = (10, 30)
TERMINAL_STATES = frozenset({"completed", "failed", "interrupted", "cancelled"})
PIA_SERVER_ROUTE = {"view": "settings", "section": "Connectors/pia_server"}
MUSIC_ROUTE = dict(service.SUNO_SETTINGS_ROUTE)
SERVER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
DEFAULT_SETTINGS = {"max_count": 10, "duration": [10, 180], "instrumental": True}

RN09_MESSAGE = (
    "Sem conexão com a PIA Server. A geração continua lá e as músicas serão "
    "baixadas quando a conexão voltar."
)
DOWNLOAD_FAILED_MESSAGE = (
    "Não foi possível baixar a música. Tente de novo pelo Histórico."
)
MESSAGES = {
    "pia_server_unpaired": device.UNPAIRED_MESSAGE,
    "pia_server_unreachable": device.UNREACHABLE_MESSAGE,
    "pia_server_unsupported": device.UNREACHABLE_MESSAGE,
    "suno_not_connected": "Conecte o Suno em Configurações → Música.",
    "suno_credential_expired": (
        "A conexão com o Suno expirou. Reconecte em Configurações → Música."
    ),
    "suno_account_required": "Escolha a conta Suno",
    "suno_account_taken": (
        "Esta conta Suno já está conectada a outra conta PIA. Desconecte-a lá "
        "antes de conectá-la aqui."
    ),
    "suno_job_active": (
        "Já há uma geração do Suno em andamento nesta conta. Aguarde terminar."
    ),
    "suno_track_unavailable": "Esta música não está mais disponível no Suno.",
    "suno_connect_not_found": "Tentativa de conexão não encontrada. Tente conectar de novo.",
    "suno_account_not_found": "Conta Suno não encontrada.",
    "suno_account_mismatch": (
        "A conta autorizada no Suno não é a conta que você pediu para reconectar."
    ),
    "suno_identity_unavailable": (
        "O Suno não informou a identidade da conta. Tente de novo mais tarde."
    ),
    "suno_oauth_denied": "O Suno não autorizou a conexão.",
    "suno_oauth_invalid": "Autorização inválida ou expirada. Conecte de novo pela PIA.",
}
HINT_ROUTES = {
    "pia_server_unpaired": PIA_SERVER_ROUTE,
    "suno_not_connected": MUSIC_ROUTE,
    "suno_credential_expired": MUSIC_ROUTE,
}


class RemoteMusicError(ValueError):
    """Request-time refusal: the local API answers 400 {error, code}."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(
            message or MESSAGES.get(code) or "Falha ao falar com a PIA Server."
        )
        self.code = code


class SunoTrackUnavailableError(service.MusicProviderError):
    code = "suno_track_unavailable"
    default_message = MESSAGES["suno_track_unavailable"]


def remote_error(exc: device.DeviceApiError) -> RemoteMusicError:
    return RemoteMusicError(exc.code, MESSAGES.get(exc.code) or str(exc))


def safe_id(value: Any) -> str:
    text = str(value or "")
    if not SERVER_ID.fullmatch(text):
        raise RemoteMusicError("pia_server_error", "Resposta inválida da PIA Server.")
    return text


def hint(reason: str | None) -> dict[str, Any] | None:
    if not reason:
        return None
    route = HINT_ROUTES.get(reason)
    return {"text": MESSAGES.get(reason, ""), "route": dict(route) if route else None}


# --- status ------------------------------------------------------------------
_status_lock = threading.Lock()
_status_cache: dict[str, Any] = {}


def invalidate_status() -> None:
    with _status_lock:
        _status_cache.clear()


def _cache_key() -> str:
    from src.settings_store import values

    config = values(device.SECTION)
    raw = f"{config.get('PIA_SERVER_URL', '')}\n{config.get(device.TOKEN_FIELD, '')}"
    return sha256(raw.encode()).hexdigest()


def _normalize_account(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        identity = safe_id(raw.get("id"))
    except RemoteMusicError:
        return None
    state = str(raw.get("credential_state") or "unavailable")
    available = raw.get("available") is True and state == "configured"
    # configured | unavailable | refresh_failed (pia-server 0a1fee6 + next
    # adjustment; "expired" still accepted): a listed account that is not
    # usable must be reconnected.
    reason = None if available else "suno_credential_expired"
    label = str(raw.get("label") or raw.get("name") or raw.get("email") or identity)
    return {
        "id": identity,
        "label": label[:80],
        "email": raw.get("email") if isinstance(raw.get("email"), str) else None,
        "name": raw.get("name") if isinstance(raw.get("name"), str) else None,
        "credential_state": state,
        "available": available,
        "expires_at": raw.get("expires_at"),
        "reason": reason,
        "hint": hint(reason),
    }


def _normalize_active(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    state = str(raw.get("state") or "running")
    if state in TERMINAL_STATES:
        return None
    try:
        job_id = safe_id(raw.get("job_id") or raw.get("id"))
    except RemoteMusicError:
        return None

    def number(name):
        value = raw.get(name)
        return value if type(value) is int and value >= 0 else 0

    this_device = raw.get("this_device")
    if this_device is None:
        this_device = raw.get("from_this_device")
    generation = raw.get("generation_id")
    return {
        "server_job_id": job_id,
        "generation_id": generation
        if SERVER_ID.fullmatch(str(generation or ""))
        else None,
        "client_id": raw.get("client_id") or raw.get("client_job_id"),
        "state": state,
        "this_device": this_device is True,
        "suno_account_id": raw.get("suno_account_id"),
        "completed": number("completed"),
        "total": number("total"),
        "extra_ready": number("extra_ready"),
    }


def remote_status(*, fresh: bool = False) -> dict[str, Any]:
    """{reason, accounts, active_job, settings}. ``reason`` is None when the
    server is reachable, paired and supports Suno (it may still have no
    usable account). Never raises."""
    if not device.device_paired():
        return {
            "reason": "pia_server_unpaired",
            "accounts": [],
            "active_job": None,
            "settings": dict(DEFAULT_SETTINGS),
        }
    key = _cache_key()
    with _status_lock:
        cached = _status_cache.get(key)
        if cached and not fresh and cached[0] > time.monotonic():
            return dict(cached[1])
    try:
        account = device.device_call("GET", "account")
        capabilities = account.get("capabilities")
        if not isinstance(capabilities, list) or CAPABILITY not in capabilities:
            raise device.DeviceApiError(
                "pia_server_unsupported", MESSAGES["pia_server_unsupported"]
            )
        raw = device.device_call("GET", "suno/status")
        accounts = [a for a in map(_normalize_account, raw.get("accounts") or []) if a]
        settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
        result = {
            "reason": None,
            "accounts": accounts,
            "active_job": _normalize_active(raw.get("active_job")),
            "default_account_id": raw.get("default_account_id"),
            "settings": {**DEFAULT_SETTINGS, **settings},
        }
    except device.DeviceApiError as exc:
        reason = (
            exc.code
            if exc.code in ("pia_server_unpaired", "pia_server_unsupported")
            else "pia_server_unreachable"
        )
        result = {
            "reason": reason,
            "accounts": [],
            "active_job": None,
            "settings": dict(DEFAULT_SETTINGS),
        }
    with _status_lock:
        _status_cache[key] = (time.monotonic() + STATUS_TTL, dict(result))
    return result


def _item_reason(status: dict[str, Any]) -> str | None:
    if status["reason"]:
        return status["reason"]
    accounts = status["accounts"]
    if any(a["available"] for a in accounts):
        return None
    return "suno_credential_expired" if accounts else "suno_not_connected"


def suno_item(
    status: dict[str, Any] | None = None, *, active_job_id: str | None = None
) -> dict[str, Any]:
    """Catalog item ``suno_mcp`` (VERSÃO FINAL + contrato v3 final)."""
    status = status if status is not None else remote_status()
    reason = _item_reason(status)
    accounts = status["accounts"]
    usable = [a for a in accounts if a["available"]]
    # PO: the fallback exists ONLY with exactly one valid account. With 2+,
    # neither default_account_id nor a saved choice preselects (RN09).
    selected = usable[0]["id"] if len(usable) == 1 else None
    if reason is None:
        credential_state = "configured"
    elif reason == "suno_credential_expired":
        credential_state = "expired"
    else:
        credential_state = "missing"
    active = status.get("active_job")
    active_job = None
    if active:
        active_job = {
            # Local mirror id (watchJob) on this PC; None on another PC.
            "job_id": active_job_id if active["this_device"] else None,
            "state": active["state"],
            "this_device": active["this_device"],
            "suno_account_id": active["suno_account_id"],
            "completed": active["completed"],
            "total": active["total"],
            "extra_ready": active["extra_ready"],
        }
    return {
        "id": "suno_mcp",
        "label": "Suno",
        "name": "Suno",
        "kind": "remote",
        "description": "Suno pela PIA Server",
        "available": reason is None,
        "reason": reason,
        "hint": hint(reason),
        "connected": bool(accounts),
        "credential_state": credential_state,
        "expires_at": next(
            (a["expires_at"] for a in usable if a["id"] == selected), None
        ),
        "settings": status["settings"],
        "accounts": accounts,
        "selected_account_id": selected,
        "active_job": active_job,
        "settings_route": dict(MUSIC_ROUTE),
    }


def resolve_account(requested: Any = None) -> dict[str, Any]:
    """Account for a new job, or RemoteMusicError (400) BEFORE any job exists."""
    status = remote_status(fresh=True)
    if status["reason"]:
        raise RemoteMusicError(status["reason"])
    if status["active_job"]:
        raise RemoteMusicError("suno_job_active")  # RN10: per PIA account
    accounts = status["accounts"]
    if requested not in (None, ""):
        account = next((a for a in accounts if a["id"] == requested), None)
        if account is None:
            raise RemoteMusicError("suno_account_not_found")
        if not account["available"]:
            raise RemoteMusicError(account["reason"] or "suno_not_connected")
        return account
    usable = [a for a in accounts if a["available"]]
    if len(usable) == 1:
        return usable[0]
    if len(usable) > 1:
        raise RemoteMusicError("suno_account_required")
    raise RemoteMusicError(_item_reason(status) or "suno_not_connected")


# --- connect / disconnect ----------------------------------------------------
def connect(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    if set(data) - {"replace_account_id"}:
        raise ValueError("Parâmetros inválidos.")
    body: dict[str, Any] = {}
    if data.get("replace_account_id") not in (None, ""):
        body["replace_account_id"] = safe_id(data["replace_account_id"])
    try:
        result = device.device_call("POST", "suno/connect", body)
    except device.DeviceApiError as exc:
        raise remote_error(exc) from None
    url = str(result.get("url") or "")
    if not url.startswith("https://"):
        raise RemoteMusicError("pia_server_error", "Resposta inválida da PIA Server.")
    expires = result.get("expires_in")
    return {
        "auth_url": url,
        "attempt_id": safe_id(result.get("attempt_id")),
        "expires_in": expires if type(expires) is int else 600,
    }


def connect_attempt(attempt_id: Any) -> dict[str, Any]:
    identity = safe_id(attempt_id)
    try:
        result = device.device_call("GET", f"suno/connect/{identity}")
    except device.DeviceApiError as exc:
        if exc.code in ("not_found", "suno_connect_not_found") or exc.status == 404:
            raise RemoteMusicError("suno_connect_not_found") from None
        raise remote_error(exc) from None
    state = str(result.get("state") or "")
    if state == "expired":
        # Agreed with the frontend: expired or missing attempt -> 400.
        invalidate_status()
        raise RemoteMusicError("suno_connect_not_found")
    if state not in ("pending", "connected", "failed"):
        raise RemoteMusicError("pia_server_error", "Resposta inválida da PIA Server.")
    out: dict[str, Any] = {"state": state}
    if result.get("account_id") and SERVER_ID.fullmatch(str(result["account_id"])):
        out["account_id"] = str(result["account_id"])
    if state == "failed":
        code = str(result.get("code") or "error")
        out["code"] = code if re.fullmatch(r"[a-z0-9_]{1,64}", code) else "error"
    if state != "pending":
        invalidate_status()
    return out


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
LABEL_MAX = 60


def rename(account_id: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Nickname of one Suno account (RN07): PATCH /device/suno/accounts/:id."""
    data = dict(payload or {})
    if set(data) - {"label"}:
        raise ValueError("Parâmetros inválidos.")
    label = data.get("label")
    if not isinstance(label, str):
        raise RemoteMusicError("invalid_label", "Informe o apelido da conta Suno.")
    label = label.strip()
    if not label or len(label) > LABEL_MAX or _CONTROL.search(label):
        raise RemoteMusicError(
            "invalid_label",
            f"O apelido da conta Suno deve ter de 1 a {LABEL_MAX} caracteres, sem caracteres de controle.",
        )
    identity = safe_id(account_id)
    try:
        device.device_call("PATCH", f"suno/accounts/{identity}", {"label": label})
    except device.DeviceApiError as exc:
        raise remote_error(exc) from None
    invalidate_status()
    return {"ok": True, "provider": suno_item(remote_status(fresh=True))}


def disconnect(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    identity = safe_id(data.get("account_id"))
    try:
        device.device_call("DELETE", f"suno/accounts/{identity}")
    except device.DeviceApiError as exc:
        raise remote_error(exc) from None
    invalidate_status()
    return {"ok": True, "provider": suno_item(remote_status(fresh=True))}


# --- jobs ---------------------------------------------------------------------
def ready_text(completed: int, total: int, extra: int = 0) -> str:
    text = service.tracks_ready_text(completed, total)
    return f"{text} (+{extra} extra)" if extra else text


_JOB_ERRORS = {
    "suno_credential_expired": (
        service.SunoAuthError,
        "A autorização da conta Suno {name} expirou. Reconecte em Configurações → Música",
    ),
    "suno_not_connected": (service.SunoAuthError, MESSAGES["suno_not_connected"]),
    "suno_no_credits": (
        service.SunoNoCreditsError,
        "A conta Suno {name} está sem créditos.",
    ),
    "suno_unavailable": (service.SunoUnavailableError, None),
    "suno_timeout": (service.SunoTimeoutError, None),
    "download_failed": (service.SunoDownloadError, DOWNLOAD_FAILED_MESSAGE),
    "suno_track_unavailable": (SunoTrackUnavailableError, None),
}


def job_error(
    code: Any, account_name: str = "", completed: int = 0, total: int = 0
) -> BaseException:
    """Typed job exception for a server ``code`` (RN11 texts, CA10)."""
    code = str(code or "")
    if not re.fullmatch(r"[a-z0-9_]{1,64}", code):
        code = "error"
    if code == "incomplete_batch":
        exc: BaseException = service.SunoIncompleteBatchError(completed, total)
    elif code in _JOB_ERRORS:
        cls, template = _JOB_ERRORS[code]
        exc = cls(template.format(name=account_name or "") if template else None)
    elif code in MESSAGES:
        exc = service.MusicProviderError(MESSAGES[code])
    elif code == "interrupted":
        exc = service.MusicProviderError(
            "A geração foi interrompida na PIA Server; as músicas prontas foram salvas."
        )
    else:
        exc = service.MusicProviderError()
    exc.code = code  # instance attr: the server code wins (CA10)
    return exc


def download_track(generation_id: str, n: int, *, cancelled=lambda: False):
    """Stream one track through the server proxy into OUTPUT (.part + replace).

    100 MiB limit, Content-Length and X-Content-SHA256 checked when sent.
    Raises SunoTrackUnavailableError (410), DeviceApiError for connection
    problems and SunoDownloadError for anything else. Never leaves a .part.
    """
    destination = service.output_directory()
    try:
        response = device.device_call(
            "GET",
            f"music/generations/{safe_id(generation_id)}/tracks/{int(n)}/audio",
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
        )
    except device.DeviceApiError as exc:
        if exc.code == "suno_track_unavailable" or exc.status == 410:
            raise SunoTrackUnavailableError() from None
        if exc.code in ("pia_server_unreachable", "pia_server_unpaired"):
            raise
        raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE) from None
    part = None
    try:
        ctype = (
            str(response.headers.get("Content-Type") or "")
            .split(";")[0]
            .strip()
            .lower()
        )
        if not (ctype.startswith("audio/") or ctype == "application/octet-stream"):
            raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE)
        declared = None
        if response.headers.get("Content-Length"):
            try:
                declared = int(response.headers["Content-Length"])
            except (TypeError, ValueError):
                raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE) from None
            if declared > service.MAX_AUDIO_BYTES:
                raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE)
        expected = str(response.headers.get("X-Content-SHA256") or "").strip().lower()
        extension = service._AUDIO_CONTENT_EXTENSIONS.get(ctype, "mp3")
        destination.mkdir(parents=True, exist_ok=True)
        final = destination / (uuid.uuid4().hex + "." + extension)
        part = final.with_name(final.name + ".part")
        digest = sha256()
        size = 0
        try:
            with open(part, "wb") as handle:
                for chunk in response.iter_content(service._AUDIO_CHUNK):
                    if cancelled():
                        raise InterruptedError(service.SUNO_CANCEL_MESSAGE)
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > service.MAX_AUDIO_BYTES:
                        raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE)
                    digest.update(chunk)
                    handle.write(chunk)
        except (InterruptedError, service.MusicProviderError):
            raise
        except Exception:
            raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE) from None
        if size == 0 or (declared is not None and size != declared):
            raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE)
        if expected and expected != digest.hexdigest():
            raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE)
        os.replace(part, final)
        part = None
        return final
    except OSError:
        raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE) from None
    finally:
        response.close()
        if part is not None:
            service._discard(part)


def save_track(
    path,
    entry: dict[str, Any],
    track: dict[str, Any],
    *,
    variant: int,
    redownloaded: bool = False,
) -> dict[str, Any]:
    """Sidecar .json (provider=suno_mcp, no link, RN19) + local index."""
    extra = track.get("extra") is True
    result = {
        "file": path.name,
        "provider": "suno_mcp",
        "prompt": entry.get("prompt") or "",
        "lyrics": entry.get("lyrics") or "",
        "requested_duration": entry.get("params", {}).get("duration"),
        "audio_url": "/api/pia/music/files/" + path.name,
        "batch": entry["id"].replace("-", ""),
        "variant": variant,
        "client_id": entry["id"],
        "generation_id": entry.get("generation_id"),
        "track_n": int(track["n"]),
        "extra": extra,
        "label": history.track_label("suno", extra),
    }
    if entry.get("suno_account"):
        result["suno_account"] = entry["suno_account"]
    title = str(track.get("title") or "").strip()
    if title:
        result["title"] = title[:200]
    if type(track.get("duration")) in (int, float):
        result["duration"] = track["duration"]
    if redownloaded:
        result["redownloaded"] = True
    if entry.get("origin") is False:
        result["origin"] = False  # Suno track redownloaded on another PC
    metadata = path.with_name(path.name + ".json")
    try:
        service.save_json(metadata, result)
    except Exception:
        service._discard(path)
        service._discard(metadata)
        raise service.SunoDownloadError(DOWNLOAD_FAILED_MESSAGE) from None
    history.add_track(
        entry["id"],
        int(track["n"]),
        path.name,
        title=result.get("title"),
        duration=result.get("duration"),
        extra=extra,
    )
    from Plugins.Connectors.pia_server.media import enqueue

    enqueue(path)  # RN15: media queue like the other generators
    return result


class RemoteJob:
    """One server job followed by this PC (new or resumed)."""

    def __init__(self, entry: dict[str, Any]):
        self.entry = entry
        self.server_job_id = safe_id(entry["job_id"])
        self.count = int(entry.get("count") or 1)
        self.account_name = (entry.get("suno_account") or {}).get("name") or ""
        self.saved: list[dict[str, Any]] = []
        self.failures: list[BaseException] = []
        self.connection = "ok"

    @classmethod
    def create(cls, data: dict[str, Any], account: dict[str, Any]) -> "RemoteJob":
        prompt, lyrics = data.get("prompt"), data.get("lyrics", "")
        duration, count = data.get("duration", 30), data.get("count", 1)
        service._validate_generation_input(prompt, lyrics, duration)
        if type(count) is not int or not 1 <= count <= 10:
            raise ValueError("Quantidade deve estar entre 1 e 10.")
        client_id = str(uuid.uuid4())
        body = {
            "prompt": prompt,
            "lyrics": lyrics,
            "duration": duration,
            "count": count,
            "client_job_id": client_id,
            "suno_account_id": account["id"],
        }
        if isinstance(data.get("instrumental"), bool):
            body["instrumental"] = data["instrumental"]
        try:
            result = device.device_call("POST", "suno/jobs", body)
        except device.DeviceApiError as exc:
            raise remote_error(exc) from None
        invalidate_status()
        params = {
            "provider": "suno_mcp",
            "suno_account_id": account["id"],
            "duration": duration,
            "count": count,
        }
        if "instrumental" in body:
            params["instrumental"] = body["instrumental"]
        generation = result.get("generation_id")
        entry = history.record(
            client_id,
            source="suno",
            provider="suno_mcp",
            prompt=prompt,
            lyrics=lyrics,
            params=params,
            count=count,
            state="running",
            job_id=safe_id(result.get("job_id")),
            generation_id=generation
            if SERVER_ID.fullmatch(str(generation or ""))
            else None,
            suno_account={"id": account["id"], "name": account["label"]},
            pending=True,
        )
        return cls(entry)

    @classmethod
    def resume(cls, active: dict[str, Any]) -> "RemoteJob":
        entry = history.find_job(active["server_job_id"])
        if entry is None:
            # Index lost: rebuild the minimum from the status (no prompt).
            client_id = str(active.get("client_id") or uuid.uuid4())
            entry = history.record(
                client_id,
                source="suno",
                provider="suno_mcp",
                prompt="",
                lyrics="",
                params={
                    "provider": "suno_mcp",
                    "suno_account_id": active.get("suno_account_id"),
                    "count": active["total"] or 1,
                },
                count=active["total"] or 1,
                state="running",
                job_id=active["server_job_id"],
                generation_id=active.get("generation_id"),
                suno_account={"id": active.get("suno_account_id"), "name": ""}
                if active.get("suno_account_id")
                else None,
                pending=True,
            )
        return cls(entry)

    # -- counters ---------------------------------------------------------------
    def counts(self) -> tuple[int, int]:
        regular = sum(1 for item in self.saved if not item.get("extra"))
        return regular, len(self.saved) - regular

    def _downloaded(self) -> set[int]:
        return {
            int(n)
            for n, t in (history.get(self.entry["id"]) or {}).get("tracks", {}).items()
            if t.get("file")
        }

    def progress_value(self, label: str, state: str = "running") -> dict[str, Any]:
        completed, extra = self.counts()
        total = self.count
        return {
            "percent": min(100.0, completed / total * 100) if total else 0,
            "completed": completed,
            "total": total,
            "extra_ready": extra,
            "label": label,
            "state": state,
            "ready_text": ready_text(completed, total, extra),
            "connection": self.connection,
        }

    def follow(
        self, *, cancelled, wait, on_track, on_progress, log
    ) -> list[dict[str, Any]]:
        """Poll until a terminal state, downloading every ready track.

        Offline: progress.connection "lost" + RN09 text, backoff 5 s..60 s,
        never gives up (no deadline in the v3 final contract).
        """
        backoff = OFFLINE_BACKOFF_MIN
        cancel_sent = False
        final_pass = False
        while True:
            if cancelled() and not cancel_sent:
                cancel_sent = True
                try:
                    device.device_call(
                        "POST", f"suno/jobs/{self.server_job_id}/cancel", {}
                    )
                except device.DeviceApiError:
                    pass
                final_pass = True
            try:
                data = device.device_call("GET", f"suno/jobs/{self.server_job_id}")
            except device.DeviceApiError as exc:
                if exc.code not in ("pia_server_unreachable",):
                    raise remote_error(exc) from None
                if final_pass:
                    raise InterruptedError(service.SUNO_CANCEL_MESSAGE) from None
                if self.connection != "lost":
                    self.connection = "lost"
                    log(RN09_MESSAGE)
                    on_progress(self.progress_value(RN09_MESSAGE))
                wait(backoff)
                backoff = min(OFFLINE_BACKOFF_MAX, backoff * 2)
                continue
            backoff = OFFLINE_BACKOFF_MIN
            if self.connection == "lost":
                self.connection = "ok"
                on_progress(
                    self.progress_value("Conexão com a PIA Server restabelecida")
                )
            generation = data.get("generation_id")
            if SERVER_ID.fullmatch(str(generation or "")) and not self.entry.get(
                "generation_id"
            ):
                self.entry = history.update(self.entry["id"], generation_id=generation)
            if not self._download_ready(data, cancelled, on_track, on_progress, log):
                continue  # connection dropped mid-download: retry later
            state = str(data.get("state") or "running")
            if state in TERMINAL_STATES or final_pass:
                return self._finish(state, data, cancel_sent)
            wait(POLL_INTERVAL)

    def _download_ready(self, data, cancelled, on_track, on_progress, log) -> bool:
        generation = self.entry.get("generation_id") or self.server_job_id
        done = self._downloaded()
        failed = {getattr(f, "track_n", None) for f in self.failures}
        for track in data.get("tracks") or []:
            if not isinstance(track, dict) or type(track.get("n")) is not int:
                continue
            n = track["n"]
            if n in done or n in failed or track.get("state", "ready") != "ready":
                continue
            try:
                path = download_track(generation, n, cancelled=cancelled)
            except device.DeviceApiError:
                if self.connection != "lost":
                    self.connection = "lost"
                    log(RN09_MESSAGE)
                    on_progress(self.progress_value(RN09_MESSAGE))
                return False
            except service.MusicProviderError as exc:
                exc.track_n = n
                self.failures.append(exc)
                log("Falha ao baixar uma faixa do Suno.")
                continue
            item = save_track(path, self.entry, track, variant=len(self.saved) + 1)
            self.saved.append(item)
            completed, _extra = self.counts()
            on_track(item, completed, self.count)
        return True

    def _finish(self, state, data, cancel_sent) -> list[dict[str, Any]]:
        completed, _ = self.counts()
        code = data.get("code")
        if cancel_sent or state == "cancelled":
            history.update(
                self.entry["id"],
                state="cancelled",
                pending=state not in TERMINAL_STATES,
            )
            raise InterruptedError(service.SUNO_CANCEL_MESSAGE)
        if state == "completed" and not code and not self.failures:
            history.update(self.entry["id"], state="completed", pending=False)
            return list(self.saved)
        history.update(self.entry["id"], state=state, code=code or None, pending=False)
        if state == "completed" and not code:
            raise self.failures[0]
        raise job_error(
            code or ("interrupted" if state == "interrupted" else "error"),
            self.account_name,
            completed,
            self.count,
        )


# --- local registry of followed jobs (watchJob mirrors) -----------------------
_mirror_lock = threading.Lock()
_mirrors: dict[str, Any] = {}  # server_job_id -> local Job


def mirror_for(server_job_id: str):
    with _mirror_lock:
        job = _mirrors.get(server_job_id)
        return job if job is not None and job.status == "running" else None


def register_mirror(server_job_id: str, job) -> bool:
    with _mirror_lock:
        current = _mirrors.get(server_job_id)
        if current is not None and current.status == "running":
            return False
        _mirrors[server_job_id] = job
        return True


def running_mirror():
    with _mirror_lock:
        return next((j for j in _mirrors.values() if j.status == "running"), None)


def make_wait(cancel_event):
    """Interruptible wait (Event slices), never a blind time.sleep."""

    def wait(seconds: float) -> None:
        end = time.monotonic() + max(0.0, seconds)
        while not cancel_event.is_set():
            left = end - time.monotonic()
            if left <= 0:
                return
            cancel_event.wait(min(WAIT_SLICE, left))

    return wait


def run_batch(
    runner: RemoteJob, *, progress, cancelled, cancel_event, on_track, on_progress
):
    """Follow ``runner`` and annotate any exception with completed/total/items."""
    event = cancel_event or threading.Event()
    try:
        return runner.follow(
            cancelled=cancelled,
            wait=make_wait(event),
            on_track=on_track or (lambda *a: None),
            on_progress=on_progress or (lambda value: None),
            log=progress or (lambda text: None),
        )
    except BaseException as exc:
        completed, extra = runner.counts()
        try:
            exc.completed = completed
            exc.total = runner.count
            exc.extra_ready = extra
            exc.items = list(runner.saved)
        except AttributeError:
            pass
        raise


# --- redownload jobs (RN16, v3.2) ---------------------------------------------
_redownload_lock = threading.Lock()
_redownloads: dict[tuple[str, int], Any] = {}


def redownload_job(identity: str, n: int):
    with _redownload_lock:
        job = _redownloads.get((identity, n))
        return job if job is not None and job.status == "running" else None


def claim_redownload(identity: str, n: int, job) -> Any:
    """Register ``job`` unless one is already running (returns the winner)."""
    with _redownload_lock:
        current = _redownloads.get((identity, n))
        if current is not None and current.status == "running":
            return current
        _redownloads[(identity, n)] = job
        return job


class RemoteSunoBackend:
    """``service.suno_backend()``: create the server job / follow it."""

    @staticmethod
    def create(data: dict[str, Any], account: dict[str, Any]) -> RemoteJob:
        return RemoteJob.create(data, account)

    @staticmethod
    def run(runner: RemoteJob, **kwargs) -> list[dict[str, Any]]:
        return run_batch(runner, **kwargs)


BACKEND = RemoteSunoBackend()

from src.settings_store import get as setting

"""Music providers. Local ACE-Step is isolated from PIA's Torch environment."""
import atexit
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import uuid
import requests
from src.config_paths import BASE_DIR
from src.settings_store import values as section_values, document, save_document
from src.resource_plugins import save_json

ROOT = Path(__file__).resolve().parent
CACHE = BASE_DIR / "cache/Apps/music"


def default_music_folder():
    home = Path.home()
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                return (
                    Path(os.path.expandvars(winreg.QueryValueEx(key, "My Music")[0]))
                    / "PIA"
                )
        except OSError:
            pass
    else:
        file = (
            Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "user-dirs.dirs"
        )
        if file.is_file():
            match = re.search(
                r'^XDG_MUSIC_DIR="([^"]+)"', file.read_text(encoding="utf-8"), re.M
            )
            if match:
                return Path(match.group(1).replace("$HOME", str(home))) / "PIA"
    return home / "Music/PIA"


from src.user_paths import user_path

OUTPUT = user_path("music")
LEGACY_OUTPUT = OUTPUT
REVISION = "ca1e85fe9430179831e6bc6be790c332190a3866"
_engine = None
_token = secrets.token_urlsafe(40)
_lock = threading.Lock()
_generation_lock = threading.Lock()


def settings():
    return section_values("Apps/music")


MUSIC_PROVIDERS = ("local", "gemini", "suno_mcp")


class MusicProviderError(RuntimeError):
    """Provider error with a friendly, secret-free message and a stable ``code``."""

    code = "error"
    default_message = "Falha ao gerar a música."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.default_message)


class SunoAuthError(MusicProviderError):
    code = "suno_auth"
    default_message = "Autorização do Suno expirou. Reconecte em Configurações → Música"


class SunoUnavailableError(MusicProviderError):
    code = "suno_unavailable"
    default_message = "Suno indisponível no momento, tente de novo ou use outro gerador"


class SunoTimeoutError(MusicProviderError):
    code = "suno_timeout"
    default_message = (
        "O Suno não respondeu a tempo; a geração pode ter sido concluída lá"
    )


class SunoProtocolError(MusicProviderError):
    """Unexpected/incompatible answer from the Suno MCP (code ``error``)."""

    default_message = "O Suno recusou ou não entendeu a solicitação; nenhuma nova tentativa foi feita."


class SunoNoCreditsError(MusicProviderError):
    """Identifiable lack of credits (HTTP 402 or explicit credits code, Q7)."""

    code = "suno_no_credits"
    default_message = "Sem créditos no Suno. Verifique sua conta."


class SunoDownloadError(MusicProviderError):
    """The clip was generated but its audio could not be fetched/saved (Q2)."""

    code = "download_failed"
    default_message = (
        "Não foi possível baixar o áudio gerado pelo Suno, tente de novo ou "
        "use outro gerador"
    )


class SunoClipFailedError(MusicProviderError):
    """A clip came back failed/without audio; the batch stops there (Q8)."""

    default_message = (
        "O Suno não conseguiu gerar uma das músicas; as que ficaram prontas "
        "foram salvas."
    )


def tracks_ready_text(completed: int, total: int) -> str:
    """ "k de N músicas prontas" (singular when total == 1)."""
    noun = "música pronta" if total == 1 else "músicas prontas"
    return f"{completed} de {total} {noun}"


class SunoIncompleteBatchError(MusicProviderError):
    """The Suno returned fewer clips than requested (Q1); saved ones are kept."""

    code = "incomplete_batch"
    # No "k de N" suffix: that lives in the notification, completed/total and
    # the job's ready_text (TechLead decision (b)).
    default_message = "O Suno devolveu menos músicas que o esperado."

    def __init__(self, completed: int = 0, total: int = 0):
        super().__init__()
        self.completed = completed
        self.total = total


SUNO_SETTINGS_ROUTE = {"view": "settings", "section": "Apps/music"}
# RN08: cancel stops the wait; a generation already sent keeps going there.
SUNO_CANCEL_MESSAGE = (
    "A espera foi cancelada. O Suno pode continuar a geração já enviada e "
    "consumir créditos."
)
SUNO_CANCEL_BEFORE_SEND_MESSAGE = (
    "Geração cancelada antes de enviar ao Suno; nenhum crédito foi consumido."
)
# --- Suno provider boundary (RN01/RN18/RN20) -------------------------------
# The Suno OAuth and token live only on the PIA Server. This computer never
# holds a Suno credential: the local/manual mode (URL, command, bearer,
# MUSIC_SUNO_MCP_TOKEN, local OAuth/PKCE/DCR and the direct MCP adapter) was
# removed in T8. T6 plugs the PIA Server client into the two seams below:
# ``_remote_suno_status()`` and ``suno_backend()``. Everything else (catalog,
# refusal, job worker, errors) reads them and does not change.

SUNO_REMOTE_SETTINGS = {"max_count": 10, "duration": [10, 180], "instrumental": True}

# RN02: hint per unavailability reason (stable codes, also used as the
# refusal ``code`` of a Suno job).
SUNO_HINTS = {
    "pia_server_unpaired": (
        "Para usar o Suno, entre na PIA Server em Configurações → PIA Server.",
        {"view": "settings", "section": "Connectors/pia_server"},
    ),
    "suno_not_connected": (
        "Conecte o Suno em Configurações → Música.",
        dict(SUNO_SETTINGS_ROUTE),
    ),
    "suno_credential_expired": (
        "A conexão com o Suno expirou. Reconecte em Configurações → Música.",
        dict(SUNO_SETTINGS_ROUTE),
    ),
    "pia_server_unreachable": (
        "Não foi possível falar com a PIA Server agora. O Suno volta a aparecer "
        "quando a conexão voltar.",
        None,
    ),
    "pia_server_unsupported": (
        "Não foi possível falar com a PIA Server agora. O Suno volta a aparecer "
        "quando a conexão voltar.",
        None,
    ),
}
SUNO_UNAVAILABLE_REASONS = tuple(SUNO_HINTS)


def suno_hint(reason: str | None) -> dict[str, Any] | None:
    if not reason:
        return None
    text, route = SUNO_HINTS.get(reason, SUNO_HINTS["pia_server_unreachable"])
    # route is the object navigate() takes (VERSÃO FINAL item 5), not a string.
    return {"text": text, "route": dict(route) if route else None}


def _remote_suno_status() -> dict[str, Any]:
    """Suno status as reported by the PIA Server (T6).

    ``GET /device/account`` (capability ``suno:3``) + ``GET /device/suno/status``
    through ``remote_suno`` (short cache). Keys: available, reason, connected,
    credential_state, expires_at, accounts, selected_account_id, settings,
    active_job. Never returns a token.
    """
    from Plugins.Apps.music import remote_suno

    return remote_suno.suno_item()


def suno_status() -> dict[str, Any]:
    """Public, secret-free Suno status used by catalog, refusal and worker."""
    try:
        remote = dict(_remote_suno_status() or {})
    except Exception:
        remote = {"available": False, "reason": "pia_server_unreachable"}
    available = remote.get("available") is True
    reason = None
    if not available:
        reason = str(remote.get("reason") or "")
        if reason not in SUNO_UNAVAILABLE_REASONS:
            reason = "pia_server_unreachable"
    return {
        "id": "suno_mcp",
        "label": "Suno",
        "name": "Suno",
        "kind": "remote",
        "available": available,
        "reason": reason,
        "hint": suno_hint(reason),
        "connected": remote.get("connected") is True,
        "credential_state": str(remote.get("credential_state") or "missing"),
        "expires_at": remote.get("expires_at"),
        "settings": json.loads(
            json.dumps(remote.get("settings") or SUNO_REMOTE_SETTINGS)
        ),
        "accounts": list(remote.get("accounts") or []),
        "selected_account_id": remote.get("selected_account_id"),
        "active_job": remote.get("active_job"),
        "settings_route": dict(SUNO_SETTINGS_ROUTE),
    }


SUNO_CONNECT_MESSAGE = SUNO_HINTS["suno_not_connected"][0]


class SunoJobRefusedError(ValueError):
    """Suno job refused before it is created. A ValueError (HTTP 400) with a
    stable ``code``: the unavailability reason (``suno_not_connected``,
    ``suno_credential_expired``, ``pia_server_unpaired``…)."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def resolve_music_provider(provider: Any = None) -> str:
    """Requested provider, or the saved ``MUSIC_PROVIDER`` when omitted."""
    if provider is None or (isinstance(provider, str) and not provider.strip()):
        provider = settings().get("MUSIC_PROVIDER") or "local"
    return str(provider).strip().lower()


def suno_job_refusal() -> SunoJobRefusedError | None:
    """Error to raise when a Suno job must be refused before it exists, or None."""
    status = suno_status()
    if status.get("available"):
        return None
    reason = status.get("reason") or "pia_server_unreachable"
    if reason == "suno_credential_expired":
        return SunoJobRefusedError(SunoAuthError.default_message, reason)
    return SunoJobRefusedError(suno_hint(reason)["text"], reason)


def suno_job_account(suno_account_id: Any = None) -> dict[str, Any]:
    """Suno account of a new job (RN09/RN10), or a 400 ``RemoteMusicError``:
    ``suno_account_required`` with 2+ valid accounts and no explicit id (no
    fallback to default_account_id or the saved choice), ``suno_job_active``
    while the PIA account has a job, ``suno_account_not_found``..."""
    from Plugins.Apps.music import remote_suno

    return remote_suno.resolve_account(suno_account_id)


def suno_backend() -> Any:
    """PIA Server client of the batch worker (T6): ``create(data, account)``
    starts the job on the server and ``run(runner, ...)`` follows it and
    downloads every ready track. Never talks to the Suno directly."""
    from Plugins.Apps.music import remote_suno

    return remote_suno.BACKEND


def suno_known_secrets() -> list[str]:
    """Secrets known right now for ``redact_secrets``. No Suno token exists on
    this computer (RN16); the PIA Server device token is the only credential
    the Suno flow uses. Never raises: redaction must not break the worker.
    """
    try:
        token = str(
            section_values("Connectors/pia_server").get("PIA_SERVER_DEVICE_TOKEN") or ""
        ).strip()
    except Exception:
        token = ""
    return [token] if token else []


_AMZ_PARAM_RE = re.compile(r"(?i)\bx-amz-[a-z0-9-]+\s*[=:]\s*[^&\s'\"]*")
_REDACTED = "••••"
_MIN_KNOWN_SECRET = 6


def redact_secrets(text: Any, extra: Any = (), limit: int = 2000) -> str:
    """Text safe for job logs/errors/notifications (CA10).

    Masks URLs (no query), ``Bearer …``, ``token=``/``sig=``/``signature=``
    (``mcp_connectors.redact_error_text``), any ``X-Amz-*`` parameter, and the
    literal value of known secrets passed in ``extra``. Never raises.
    """
    from src.mcp_connectors import redact_error_text

    try:
        out = str(text if text is not None else "")
        for secret in sorted(
            {str(s) for s in (extra or ()) if s}, key=len, reverse=True
        ):
            if len(secret) >= _MIN_KNOWN_SECRET:
                out = out.replace(secret, _REDACTED)
        out = _AMZ_PARAM_RE.sub(_REDACTED, out)
        return redact_error_text(out, limit=limit)
    except Exception:
        return ""


def providers_catalog():
    cfg = settings()
    selected = str(cfg.get("MUSIC_PROVIDER") or "local").strip().lower()
    if selected not in MUSIC_PROVIDERS:
        selected = "local"
    local_installed = (CACHE / "ace-step/.venv").is_dir()
    from src.config import STT_GEMINI_API_KEY, setting
    from Plugins.Apps.music import suno_legacy

    gemini_key = bool(
        setting("GEMINI_API_KEY") or setting("AGE_GEMINI_API_KEY") or STT_GEMINI_API_KEY
    )
    suno = suno_status()
    try:
        legacy = suno_legacy.legacy_state()
        suno["legacy_credentials"] = {
            "present": legacy["present"],
            "prompt": legacy["prompt"],
        }
    except Exception:
        suno["legacy_credentials"] = {"present": False, "prompt": False}
    suno["description"] = "Geração pelo Suno conectado na PIA Server"
    return {
        "providers": [
            {
                "id": "local",
                "name": "Criador de músicas local",
                "kind": "local",
                "description": "ACE-Step local offline",
                "installed": local_installed,
                "available": True,
            },
            {
                "id": "gemini",
                "name": "Gemini",
                "kind": "remote",
                "description": "Geração de música via Gemini (Lyria)",
                "model": str(cfg.get("MUSIC_GEMINI_MODEL") or "lyria-3.5"),
                "credential_state": "configured" if gemini_key else "missing",
                "available": gemini_key,
            },
            suno,
        ],
        "selection": {
            "provider": selected,
            "gemini_model": str(cfg.get("MUSIC_GEMINI_MODEL") or "lyria-3.5"),
        },
    }


def select_provider(
    *,
    provider: str | None = None,
    gemini_model: str | None = None,
):
    from src.settings_store import get_store

    updates = {}
    if provider is not None:
        norm = str(provider).strip().lower()
        if norm not in MUSIC_PROVIDERS:
            raise ValueError(
                "Provedor de música inválido. Escolha local, gemini ou suno_mcp."
            )
        updates["MUSIC_PROVIDER"] = norm
    if gemini_model is not None and str(gemini_model).strip():
        updates["MUSIC_GEMINI_MODEL"] = str(gemini_model).strip()
    if updates:
        get_store().save("Apps/music", updates)
    return providers_catalog()


def output_directory():
    return OUTPUT


def base_url():
    url = settings().get("MUSIC_LOCAL_URL") or "http://127.0.0.1:8015"
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "ACE-Step deve usar uma URL HTTP de loopback sem caminho ou credenciais."
        )
    return url.rstrip("/")


def prepare(report=lambda text: None):
    uv = shutil.which("uv")
    git = shutil.which("git")
    if not uv or not git:
        raise RuntimeError("Instale uv e Git para preparar o motor local.")
    CACHE.mkdir(parents=True, exist_ok=True)
    repo = CACHE / "ace-step"
    flags = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if sys.platform == "win32"
        else {}
    )
    with _lock:
        if not (repo / ".git").exists():
            report("Baixando código oficial do ACE-Step para um ambiente separado…")
            subprocess.run(
                [
                    git,
                    "clone",
                    "--filter=blob:none",
                    "https://github.com/ace-step/ACE-Step-1.5.git",
                    str(repo),
                ],
                check=True,
                capture_output=True,
                timeout=300,
                **flags,
            )
        subprocess.run(
            [git, "-C", str(repo), "checkout", "--detach", REVISION],
            check=True,
            capture_output=True,
            timeout=120,
            **flags,
        )
        report(
            "Instalando dependências do motor local. O download pode ocupar vários GB."
        )
        subprocess.run(
            [uv, "sync", "--project", str(repo), "--python", "3.12"],
            check=True,
            capture_output=True,
            timeout=3600,
            **flags,
        )
    report("Motor instalado. Os pesos serão baixados pelo ACE-Step no primeiro início.")
    return {"installed": True}


def _json(response):
    try:
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"O provedor musical retornou HTTP {response.status_code}. Confira acesso, cotas e credenciais."
            )
        return response.json()
    finally:
        response.close()


def engine(session, progress, cancelled):
    global _engine
    url = base_url()
    key = (
        _token
        if _engine is not None and _engine.poll() is None
        else settings().get("MUSIC_LOCAL_KEY", "")
    )
    headers = {"Authorization": "Bearer " + key} if key else {}
    try:
        health = _json(
            session.get(
                url + "/health", headers=headers, timeout=2, allow_redirects=False
            )
        )
        if health.get("data", {}).get("service") != "ACE-Step API":
            raise RuntimeError("O endereço local não é um motor ACE-Step.")
        return url, headers
    except requests.ConnectionError:
        pass
    with _lock:
        repo = CACHE / "ace-step"
        uv = shutil.which("uv")
        if not uv or not (repo / ".venv").is_dir():
            raise RuntimeError(
                "Prepare o motor local pelo botão Instalar motor local no app Música."
            )
        if _engine is None or _engine.poll() is not None:
            env = os.environ.copy()
            env.update(
                ACESTEP_API_HOST="127.0.0.1",
                ACESTEP_API_PORT=str(urlsplit(url).port or 80),
                ACESTEP_API_KEY=_token,
                ACESTEP_LM_BACKEND="pt",
                ACESTEP_OFFLOAD_TO_CPU="true",
                ACESTEP_USE_FLASH_ATTENTION="false",
                HF_HOME=str(CACHE / "models"),
            )
            log = BASE_DIR / "logs/plugins/Apps/music-engine.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("ab") as stream:
                python = repo / (
                    ".venv/Scripts/python.exe"
                    if sys.platform == "win32"
                    else ".venv/bin/python"
                )
                _engine = subprocess.Popen(
                    [str(python), "-c", "from acestep.api_server import main; main()"],
                    cwd=repo,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if sys.platform == "win32"
                        else {}
                    ),
                )
    headers = {"Authorization": "Bearer " + _token}
    progress("Iniciando ACE-Step e carregando modelos…")
    for _ in range(600):
        if cancelled():
            raise InterruptedError("Geração musical cancelada.")
        if _engine.poll() is not None:
            raise RuntimeError(
                "O motor local encerrou. Consulte o log music-engine.log."
            )
        try:
            _json(
                session.get(
                    url + "/health", headers=headers, timeout=2, allow_redirects=False
                )
            )
            return url, headers
        except (requests.RequestException, RuntimeError):
            time.sleep(2)
    raise RuntimeError("O motor não ficou pronto em 20 minutos. Consulte seus logs.")


def stop_engine():
    global _engine
    with _lock:
        process = _engine
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        _engine = None


atexit.register(stop_engine)


def audio_file(name):
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp3|wav|flac)", name):
        raise ValueError("Áudio inválido.")
    for root in (output_directory(), LEGACY_OUTPUT):
        path = root / name
        if path.is_file() and not path.is_symlink():
            return path
    raise ValueError("Áudio não encontrado.")


def library():
    items = {}
    for root in (LEGACY_OUTPUT, output_directory()):
        if not root.is_dir():
            continue
        for path in root.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{32}\.(mp3|wav|flac)\.json", path.name):
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("file") != path.name[:-5]:
                    continue
                if (root / item["file"]).is_file():
                    items[item["file"]] = {**item, "modified": path.stat().st_mtime}
            except (ValueError, KeyError, OSError):
                continue
    return sorted(items.values(), key=lambda item: item["modified"], reverse=True)[:100]


# --- Suno audio download helpers (T6) ---------------------------------------
# Shared with remote_suno.download_track (proxy of the PIA Server). The direct
# download of Suno audio links and the per-call MCP batch were removed in T9.
MAX_AUDIO_BYTES = 100 * 1024**2
_AUDIO_CHUNK = 64 * 1024
_AUDIO_CONTENT_EXTENSIONS = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


def _discard(path: Path) -> None:
    """Best-effort removal of a temp/orphan file (never masks the real error)."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _validate_generation_input(prompt: Any, lyrics: Any, duration: Any) -> None:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
        raise ValueError("Descrição obrigatória (até 8000 caracteres).")
    if not isinstance(lyrics, str) or len(lyrics) > 16000:
        raise ValueError("Letra inválida.")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int)
        or not 10 <= duration <= 180
    ):
        raise ValueError("Duração deve estar entre 10 e 180 segundos.")


def generate_suno_batch(
    prompt: str,
    lyrics: str = "",
    duration: int = 30,
    count: int = 1,
    *,
    progress: Any = lambda text: None,
    cancelled: Any = lambda: False,
    cancel_event: Any = None,
    on_track: Any = None,
    on_progress: Any = None,
    runner: Any = None,
    suno_account_id: Any = None,
) -> list[dict[str, Any]]:
    """Generate ``count`` Suno tracks on the PIA Server (T6).

    ``runner`` comes from ``suno_backend().create`` (or is created here) and
    every ready track, extras included, is downloaded into OUTPUT (RN12).
    Every raised exception carries ``completed``, ``total`` and ``items``.
    """
    backend = suno_backend()
    if runner is None:
        try:
            refusal = suno_job_refusal()
            if refusal is not None:
                raise refusal
            data = {
                "prompt": prompt,
                "lyrics": lyrics,
                "duration": duration,
                "count": count,
            }
            runner = backend.create(data, suno_job_account(suno_account_id))
        except BaseException as exc:
            exc.completed, exc.total, exc.items = 0, count, []
            raise
    return backend.run(
        runner,
        progress=progress,
        cancelled=cancelled,
        cancel_event=cancel_event,
        on_track=on_track,
        on_progress=on_progress,
    )


def generate(
    prompt,
    lyrics="",
    provider=None,
    duration=30,
    progress=lambda text: None,
    cancelled=lambda: False,
):
    if provider is None:
        provider = str(settings().get("MUSIC_PROVIDER") or "local").strip().lower()
    _validate_generation_input(prompt, lyrics, duration)
    if provider not in MUSIC_PROVIDERS:
        raise ValueError(
            "Escolha local, gemini ou suno_mcp. Flow Music é usado na interface oficial."
        )
    if provider == "suno_mcp":
        # One requested track; an extra clip is saved too (RN12) but the
        # caller gets the requested one.
        items = generate_suno_batch(
            prompt, lyrics, duration, 1, progress=progress, cancelled=cancelled
        )
        return next((i for i in items if not i.get("extra")), items[0])
    if not _generation_lock.acquire(blocking=False):
        raise RuntimeError("Já existe uma geração musical em andamento.")
    try:
        if cancelled():
            raise InterruptedError("Geração musical cancelada antes de iniciar.")
        with requests.Session() as session:
            session.trust_env = False
            if provider == "local":
                url, headers = engine(session, progress, cancelled)
                result = _json(
                    session.post(
                        url + "/release_task",
                        headers=headers,
                        json={
                            "prompt": prompt,
                            "lyrics": lyrics or "[Instrumental]",
                            "audio_duration": duration,
                            "batch_size": 1,
                            "audio_format": "mp3",
                            "thinking": False,
                        },
                        timeout=30,
                        allow_redirects=False,
                    )
                )
                identity = result["data"]["task_id"]
                progress("Gerando música localmente…")
                for _ in range(900):
                    if cancelled():
                        raise InterruptedError(
                            "A espera foi cancelada. O motor ACE-Step pode continuar sua tarefa em segundo plano."
                        )
                    response = _json(
                        session.post(
                            url + "/query_result",
                            headers=headers,
                            json={"task_id_list": [identity]},
                            timeout=10,
                            allow_redirects=False,
                        )
                    )
                    rows = response.get("data", [])
                    if rows and rows[0]["status"] == 2:
                        raise RuntimeError(
                            "ACE-Step não conseguiu gerar a música. Consulte o log do motor."
                        )
                    if rows and rows[0]["status"] == 1:
                        result = rows[0]["result"]
                        entries = (
                            json.loads(result) if isinstance(result, str) else result
                        )
                        resource = entries[0]["file"]
                        parsed = urlsplit(resource)
                        if parsed.scheme or parsed.netloc or parsed.path != "/v1/audio":
                            raise RuntimeError(
                                "O motor retornou um endereço de áudio inválido."
                            )
                        response = session.get(
                            url + resource,
                            headers=headers,
                            timeout=60,
                            allow_redirects=False,
                        )
                        try:
                            if response.status_code != 200:
                                raise RuntimeError(
                                    "Não foi possível obter o áudio do motor."
                                )
                            raw = response.content
                        finally:
                            response.close()
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError("O motor musical excedeu 30 minutos.")
                extension = "mp3"
            else:
                from src.config import STT_GEMINI_API_KEY

                key = (
                    setting("GEMINI_API_KEY")
                    or setting("AGE_GEMINI_API_KEY")
                    or STT_GEMINI_API_KEY
                )
                if not key:
                    raise RuntimeError(
                        "Configure a chave Gemini da PIA. A autorização Gmail/Drive não concede acesso à API Lyria."
                    )
                progress("Gerando música com Lyria pela API Gemini…")
                data = _json(
                    session.post(
                        "https://generativelanguage.googleapis.com/v1beta/interactions",
                        headers={"x-goog-api-key": key},
                        json={
                            "model": settings().get("MUSIC_GEMINI_MODEL")
                            or "lyria-3.5",
                            "input": f"{prompt}\nTarget duration: {duration} seconds.\n"
                            + (
                                "Lyrics:\n" + lyrics
                                if lyrics
                                else "Instrumental only. No vocals."
                            ),
                        },
                        timeout=600,
                    )
                )
                audios = [
                    content
                    for step in data.get("steps", [])
                    if step.get("type") == "model_output"
                    for content in step.get("content", [])
                    if content.get("type") == "audio"
                ]
                if not audios:
                    raise RuntimeError(
                        "Gemini não retornou áudio. Verifique a disponibilidade do modelo e as cotas de sua API."
                    )
                raw = base64.b64decode(audios[0]["data"], validate=True)
                extension = (
                    "wav" if audios[0].get("mime_type") == "audio/wav" else "mp3"
                )
            if cancelled():
                raise InterruptedError("Geração cancelada antes de salvar o resultado.")
            if not raw or len(raw) > MAX_AUDIO_BYTES:
                raise RuntimeError("Áudio musical vazio ou maior que 100 MiB.")
            destination = output_directory()
            destination.mkdir(parents=True, exist_ok=True)
            name = uuid.uuid4().hex + "." + extension
            (destination / name).write_bytes(raw)
            result = {
                "file": name,
                "provider": provider,
                "prompt": prompt,
                "lyrics": lyrics,
                "requested_duration": duration,
                "audio_url": "/api/pia/music/files/" + name,
            }
            save_json(destination / (name + ".json"), result)
            from Plugins.Connectors.pia_server.media import enqueue

            enqueue(destination / name)
            return result
    finally:
        try:
            if provider == "local":
                stop_engine()
        finally:
            _generation_lock.release()

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
_SUNO_MCP_SERVER_ID = "suno_mcp"


def _suno_connector_state() -> dict[str, Any]:
    state = {
        "auth_type": "none",
        "oauth_connected": False,
        "oauth_client_id": "",
        "oauth_auth_url": "",
        "oauth_token_url": "",
        "oauth_scopes": "",
        "has_token": False,
    }
    try:
        from src.mcp_connectors import get_mcp_manager

        mgr = get_mcp_manager()
        srv = mgr.get_server(_SUNO_MCP_SERVER_ID)
    except Exception:
        return state

    accounts = srv.get("accounts") or []
    acc = accounts[0] if accounts else {}
    oauth = acc.get("oauth") or {}
    has_token = bool(
        srv.get("has_bearer_token")
        or acc.get("has_bearer_token")
        or oauth.get("connected")
    )
    state.update(
        {
            "auth_type": str(
                acc.get("auth_type")
                or (
                    "oauth"
                    if oauth.get("client_id") or oauth.get("connected")
                    else ("bearer" if has_token else "none")
                )
            ),
            "oauth_connected": bool(oauth.get("connected")),
            "oauth_client_id": str(oauth.get("client_id") or ""),
            "oauth_auth_url": str(oauth.get("auth_url") or ""),
            "oauth_token_url": str(oauth.get("token_url") or ""),
            "oauth_scopes": str(oauth.get("scopes") or ""),
            "has_token": has_token,
        }
    )
    return state


def _ensure_suno_mcp_server(
    *,
    suno_url: str | None = None,
    suno_cmd: str | None = None,
    suno_token: str | None = None,
    oauth_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.mcp_connectors import get_mcp_manager

    cfg = settings()
    url = (
        str(suno_url).strip()
        if suno_url is not None
        else str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
    )
    cmd = (
        str(suno_cmd).strip()
        if suno_cmd is not None
        else str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
    )
    mgr = get_mcp_manager()
    try:
        existing = mgr.get_server(_SUNO_MCP_SERVER_ID)
    except KeyError:
        existing = None

    transport = "stdio" if (cmd and not url) else "http_streaming"
    payload: dict[str, Any] = {
        "id": _SUNO_MCP_SERVER_ID,
        "name": "Suno (MCP)",
        "transport": transport,
        "url": url,
        "command": cmd,
        "enabled": True,
    }
    if suno_token is not None and str(suno_token).strip():
        payload["bearer_token"] = str(suno_token).strip()

    if oauth_payload:
        existing_accounts = list((existing or {}).get("accounts") or [])
        acc = (
            dict(existing_accounts[0])
            if existing_accounts
            else {"id": "default", "name": "Suno OAuth"}
        )
        oauth = dict(acc.get("oauth") or {})
        for key in ("client_id", "auth_url", "token_url", "scopes", "redirect_uri"):
            if key in oauth_payload and oauth_payload[key] is not None:
                oauth[key] = str(oauth_payload[key]).strip()
        if oauth_payload.get("client_secret"):
            oauth["client_secret"] = str(oauth_payload["client_secret"]).strip()
        acc["oauth"] = oauth
        if oauth_payload.get("auth_type"):
            acc["auth_type"] = str(oauth_payload["auth_type"]).strip()
        elif oauth.get("client_id") or oauth.get("auth_url"):
            acc["auth_type"] = "oauth"
        payload["accounts"] = [acc]

    return mgr.save_server(payload, server_id=_SUNO_MCP_SERVER_ID)


def _resolve_suno_mcp_credentials(cfg: dict[str, Any]) -> tuple[str, str, str]:
    suno_url = str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
    suno_cmd = str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
    suno_tok = str(cfg.get("MUSIC_SUNO_MCP_TOKEN") or "").strip()
    try:
        from src.mcp_connectors import get_mcp_manager

        mgr = get_mcp_manager()
        raw = mgr._find_raw(_SUNO_MCP_SERVER_ID)
        suno_url = suno_url or str(raw.get("url") or "").strip()
        suno_cmd = suno_cmd or str(raw.get("command") or "").strip()
        accounts = [a for a in (raw.get("accounts") or []) if a.get("enabled", True)]
        acc = accounts[0] if accounts else None
        headers, _ = mgr._resolve_credentials(raw, acc)
        auth_header = headers.get("Authorization") or ""
        if auth_header.startswith("Bearer "):
            vault_tok = auth_header[len("Bearer ") :].strip()
            if vault_tok:
                suno_tok = vault_tok
    except Exception:
        pass
    return suno_url, suno_cmd, suno_tok


def suno_oauth_start(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    from src.mcp_connectors import get_mcp_manager

    _ensure_suno_mcp_server(oauth_payload=data)
    mgr = get_mcp_manager()
    return mgr.start_oauth(
        _SUNO_MCP_SERVER_ID,
        account_id=data.get("account_id"),
        payload=data,
    )


def suno_oauth_callback(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    from src.mcp_connectors import get_mcp_manager

    _ensure_suno_mcp_server()
    mgr = get_mcp_manager()
    return mgr.complete_oauth(_SUNO_MCP_SERVER_ID, payload=data)


def suno_oauth_disconnect() -> dict[str, Any]:
    from src.mcp_connectors import get_mcp_manager

    mgr = get_mcp_manager()
    try:
        servers = mgr._raw_servers()
        srv = next((s for s in servers if s.get("id") == _SUNO_MCP_SERVER_ID), None)
        if srv:
            for acc in srv.get("accounts") or []:
                mgr._set_secret(
                    _SUNO_MCP_SERVER_ID, acc["id"], "oauth_access_token", ""
                )
                mgr._set_secret(
                    _SUNO_MCP_SERVER_ID, acc["id"], "oauth_refresh_token", ""
                )
                oauth = acc.setdefault("oauth", {})
                oauth["connected"] = False
                oauth["token_masked"] = ""
            mgr._save_raw_servers(servers)
    except Exception:
        pass
    return {"ok": True, **providers_catalog()}


def providers_catalog():
    cfg = settings()
    selected = str(cfg.get("MUSIC_PROVIDER") or "local").strip().lower()
    if selected not in MUSIC_PROVIDERS:
        selected = "local"
    local_installed = (CACHE / "ace-step/.venv").is_dir()
    from src.config import STT_GEMINI_API_KEY, setting

    gemini_key = bool(
        setting("GEMINI_API_KEY") or setting("AGE_GEMINI_API_KEY") or STT_GEMINI_API_KEY
    )
    suno_url = str(cfg.get("MUSIC_SUNO_MCP_URL") or "").strip()
    suno_cmd = str(cfg.get("MUSIC_SUNO_MCP_COMMAND") or "").strip()
    suno_state = _suno_connector_state()
    suno_token = (
        bool(str(cfg.get("MUSIC_SUNO_MCP_TOKEN") or "").strip())
        or suno_state["has_token"]
    )
    suno_configured = bool(suno_url or suno_cmd)
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
            {
                "id": "suno_mcp",
                "name": "Suno (MCP)",
                "kind": "mcp",
                "description": "Conexão com servidor MCP do Suno",
                "url": suno_url,
                "command": suno_cmd,
                "credential_state": "configured" if suno_configured else "missing",
                "token_configured": suno_token,
                "auth_type": suno_state["auth_type"],
                "oauth_connected": suno_state["oauth_connected"],
                "oauth_client_id": suno_state["oauth_client_id"],
                "oauth_auth_url": suno_state["oauth_auth_url"],
                "oauth_token_url": suno_state["oauth_token_url"],
                "oauth_scopes": suno_state["oauth_scopes"],
                "available": suno_configured,
            },
        ],
        "selection": {
            "provider": selected,
            "gemini_model": str(cfg.get("MUSIC_GEMINI_MODEL") or "lyria-3.5"),
            "suno_mcp_url": suno_url,
            "suno_mcp_command": suno_cmd,
            "suno_mcp_token_configured": suno_token,
            "suno_mcp_auth_type": suno_state["auth_type"],
            "suno_mcp_oauth_connected": suno_state["oauth_connected"],
            "suno_mcp_oauth_client_id": suno_state["oauth_client_id"],
            "suno_mcp_oauth_auth_url": suno_state["oauth_auth_url"],
            "suno_mcp_oauth_token_url": suno_state["oauth_token_url"],
            "suno_mcp_oauth_scopes": suno_state["oauth_scopes"],
        },
    }


def select_provider(
    *,
    provider: str | None = None,
    gemini_model: str | None = None,
    suno_mcp_url: str | None = None,
    suno_mcp_command: str | None = None,
    suno_mcp_token: str | None = None,
    suno_mcp_auth_type: str | None = None,
    suno_mcp_client_id: str | None = None,
    suno_mcp_client_secret: str | None = None,
    suno_mcp_auth_url: str | None = None,
    suno_mcp_token_url: str | None = None,
    suno_mcp_scopes: str | None = None,
    suno_mcp_redirect_uri: str | None = None,
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
    if suno_mcp_url is not None:
        raw_url = str(suno_mcp_url).strip()
        if raw_url:
            parsed = urlsplit(raw_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("URL do Suno MCP deve usar http:// ou https://.")
        updates["MUSIC_SUNO_MCP_URL"] = raw_url
    if suno_mcp_command is not None:
        updates["MUSIC_SUNO_MCP_COMMAND"] = str(suno_mcp_command).strip()
    if suno_mcp_token is not None:
        updates["MUSIC_SUNO_MCP_TOKEN"] = str(suno_mcp_token).strip()
    if updates:
        get_store().save("Apps/music", updates)

    oauth_fields = {
        k: v
        for k, v in {
            "auth_type": suno_mcp_auth_type,
            "client_id": suno_mcp_client_id,
            "client_secret": suno_mcp_client_secret,
            "auth_url": suno_mcp_auth_url,
            "token_url": suno_mcp_token_url,
            "scopes": suno_mcp_scopes,
            "redirect_uri": suno_mcp_redirect_uri,
        }.items()
        if v is not None
    }
    if (
        suno_mcp_url is not None
        or suno_mcp_command is not None
        or suno_mcp_token is not None
        or oauth_fields
    ):
        _ensure_suno_mcp_server(
            suno_url=suno_mcp_url,
            suno_cmd=suno_mcp_command,
            suno_token=suno_mcp_token,
            oauth_payload=oauth_fields or None,
        )
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
    if provider not in MUSIC_PROVIDERS:
        raise ValueError(
            "Escolha local, gemini ou suno_mcp. Flow Music é usado na interface oficial."
        )
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
            elif provider == "suno_mcp":
                from src.mcp_chat_tools import call_suno_mcp

                cfg = settings()
                suno_url, suno_cmd, suno_tok = _resolve_suno_mcp_credentials(cfg)
                progress("Gerando música via Suno (MCP)…")
                data = call_suno_mcp(
                    prompt,
                    lyrics=lyrics,
                    duration=duration,
                    suno_url=suno_url,
                    suno_cmd=suno_cmd,
                    suno_token=suno_tok,
                )
                if isinstance(data.get("content"), list):
                    for part in data["content"]:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            try:
                                parsed = json.loads(part["text"])
                                if isinstance(parsed, dict):
                                    data = parsed
                                    break
                            except Exception:
                                pass
                if isinstance(data.get("audio_base64"), str):
                    raw = base64.b64decode(data["audio_base64"], validate=True)
                    extension = "wav" if data.get("format") == "wav" else "mp3"
                elif isinstance(data.get("audio_url"), str) and data[
                    "audio_url"
                ].startswith(("http://", "https://")):
                    raw = session.get(
                        data["audio_url"], timeout=120, allow_redirects=False
                    ).content
                    extension = "wav" if data["audio_url"].endswith(".wav") else "mp3"
                else:
                    raise RuntimeError(
                        "Resposta do servidor Suno (MCP) não trouxe áudio."
                    )
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
            if not raw or len(raw) > 100 * 1024**2:
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

"""Unified external model provider status, official quota, session usage, and routing helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import re
import threading
import weakref

import requests

from src.settings_store import get as setting, get_store

PROVIDERS_ORDER = (
    "codex",
    "agy",
    "openrouter",
    "gemini",
    "groq",
    "cloudflare",
    "local",
)

STATUS_LABELS = {
    "connected": "Conectado",
    "login_required": "Login necessário",
    "not_installed": "Não instalado",
    "error": "Erro de autenticação",
}

AUTOMATIC_OPTIONS = (
    {"id": "free", "label": "Gratuito (free)"},
    {"id": "paid", "label": "Pago (paid)"},
)

PROVIDER_META = {
    "codex": {
        "id": "codex",
        "name": "Codex CLI",
        "auth_type": "cli",
        "login_command": "codex login",
        "docs_url": "https://developers.openai.com/codex/cli/",
    },
    "agy": {
        "id": "agy",
        "name": "Google Antigravity (AGY)",
        "auth_type": "cli",
        "login_command": "agy",
        "docs_url": "https://antigravity.google/cli",
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "auth_type": "api_key",
        "key_name": "OPENROUTER_API_KEY",
        "fallback_keys": (),
        "docs_url": "https://openrouter.ai/keys",
    },
    "gemini": {
        "id": "gemini",
        "name": "Gemini",
        "auth_type": "api_key",
        "key_name": "AGE_GEMINI_API_KEY",
        "fallback_keys": ("GEMINI_API_KEY",),
        "docs_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "id": "groq",
        "name": "Groq",
        "auth_type": "api_key",
        "key_name": "GROQ_API_KEY",
        "fallback_keys": (),
        "docs_url": "https://console.groq.com/keys",
    },
    "cloudflare": {
        "id": "cloudflare",
        "name": "Cloudflare",
        "auth_type": "api_key",
        "key_name": "CLOUDFLARE_API_KEY",
        "fallback_keys": ("CLOUDFLARE_API_TOKEN",),
        "docs_url": "https://developers.cloudflare.com/workers-ai/",
    },
    "local": {
        "id": "local",
        "name": "Ollama Local",
        "auth_type": "local",
        "docs_url": "https://ollama.com",
    },
}

_ACTIVE_TRACKER_LOCK = threading.Lock()
_ACTIVE_TRACKER_REF: weakref.ref | None = None

_SECRET_PATTERN = re.compile(
    r"(Bearer\s+[A-Za-z0-9._\-]+|sk-[A-Za-z0-9._\-]{8,}|AIza[A-Za-z0-9_\-]{10,}|gsk_[A-Za-z0-9_\-]{10,}|x-goog-api-key:\s*\S+)",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format with Z suffix (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_error(message: object, secrets_to_mask: tuple[str, ...] = ()) -> str:
    """Remove any tokens, API keys, or auth headers from error messages."""
    text = str(message or "").strip()
    if not text:
        return "Erro desconhecido."
    for secret in secrets_to_mask:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[oculta]")
    text = _SECRET_PATTERN.sub("[oculta]", text)
    return text


def format_usd_ptbr(amount: float) -> str:
    """Format USD amount in pt-BR truncated to 2 decimal places without rounding up."""
    try:
        dec = Decimal(str(amount))
    except Exception:
        dec = Decimal("0")
    if dec < Decimal("0"):
        dec = Decimal("0")
    truncated = dec.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    integer_part, frac_part = f"{truncated:.2f}".split(".")
    # Format thousands with '.'
    groups = []
    while len(integer_part) > 3:
        groups.append(integer_part[-3:])
        integer_part = integer_part[:-3]
    groups.append(integer_part)
    formatted_int = ".".join(reversed(groups))
    return f"US$ {formatted_int},{frac_part} disponíveis"


def register_active_tracker(tracker: "ModelSessionTracker") -> None:
    """Register the active WorkspaceService session tracker using a weak reference."""
    global _ACTIVE_TRACKER_REF
    with _ACTIVE_TRACKER_LOCK:
        _ACTIVE_TRACKER_REF = weakref.ref(tracker)


def get_active_tracker() -> "ModelSessionTracker | None":
    """Return the currently active WorkspaceService tracker if still alive."""
    with _ACTIVE_TRACKER_LOCK:
        return _ACTIVE_TRACKER_REF() if _ACTIVE_TRACKER_REF is not None else None


def _empty_usage() -> dict:
    return {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "tokens_reported": False,
    }


class ModelSessionTracker:
    """In-memory session usage and quota cache for the active PIA workspace session."""

    def __init__(self):
        self._lock = threading.RLock()
        self.session_started_at = utc_now_iso()
        self.usage_by_provider = {pid: _empty_usage() for pid in PROVIDERS_ORDER}
        self.quota_cache: dict[str, dict] = {}
        self.local_models_cache: list[str] = []

    def reset(self) -> None:
        with self._lock:
            self.session_started_at = utc_now_iso()
            self.usage_by_provider = {pid: _empty_usage() for pid in PROVIDERS_ORDER}

    def record_usage(
        self,
        provider: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        if provider not in self.usage_by_provider:
            return
        with self._lock:
            entry = self.usage_by_provider[provider]
            entry["requests"] += 1
            p_int = (
                int(prompt_tokens)
                if isinstance(prompt_tokens, (int, float))
                and not isinstance(prompt_tokens, bool)
                and prompt_tokens >= 0
                else None
            )
            c_int = (
                int(completion_tokens)
                if isinstance(completion_tokens, (int, float))
                and not isinstance(completion_tokens, bool)
                and completion_tokens >= 0
                else None
            )
            t_int = (
                int(total_tokens)
                if isinstance(total_tokens, (int, float))
                and not isinstance(total_tokens, bool)
                and total_tokens >= 0
                else None
            )
            if p_int is not None or c_int is not None or t_int is not None:
                entry["tokens_reported"] = True
                p_val = p_int or 0
                c_val = c_int or 0
                t_val = t_int if t_int is not None else (p_val + c_val)
                entry["prompt_tokens"] += p_val
                entry["completion_tokens"] += c_val
                entry["total_tokens"] += t_val

    def snapshot_usage(self, provider: str) -> dict:
        with self._lock:
            return dict(self.usage_by_provider.get(provider, _empty_usage()))

    def total_requests(self) -> int:
        with self._lock:
            return sum(item["requests"] for item in self.usage_by_provider.values())

    def get_quota(self, provider: str) -> dict | None:
        with self._lock:
            cached = self.quota_cache.get(provider)
            return dict(cached) if cached else None

    def set_quota(self, provider: str, quota: dict) -> None:
        with self._lock:
            self.quota_cache[provider] = dict(quota)


def _read_provider_key(provider: str) -> str:
    meta = PROVIDER_META.get(provider)
    if not meta or meta["auth_type"] != "api_key":
        return ""
    primary = meta["key_name"]
    val = str(setting(primary, "") or "").strip()
    if val:
        return val
    for fallback in meta.get("fallback_keys", ()):
        val = str(setting(fallback, "") or "").strip()
        if val:
            return val
    return ""


def _local_host() -> str:
    from src import config

    return (
        str(setting("LLM_LOCAL_API_BASE", "") or "").strip()
        or config.LLM_LOCAL_API_BASE
        or "http://localhost:11434"
    ).rstrip("/")


def default_quota_for(provider: str) -> dict:
    """Return the default non-invented quota payload for a provider."""
    if provider == "codex":
        return {
            "quota_available": False,
            "quota_status": "unavailable",
            "quota_remaining": None,
            "quota_currency": None,
            "quota_label": "Saldo não informado pelo provedor",
            "quota_detail": "A integração via login do Codex CLI não disponibiliza consulta oficial de saldo.",
            "quota_checked_at": None,
        }
    if provider == "local":
        return {
            "quota_available": False,
            "quota_status": "unavailable",
            "quota_remaining": None,
            "quota_currency": None,
            "quota_label": "Saldo não informado pelo provedor · Execução local (sem cota externa)",
            "quota_detail": None,
            "quota_checked_at": None,
        }
    return {
        "quota_available": False,
        "quota_status": "unavailable",
        "quota_remaining": None,
        "quota_currency": None,
        "quota_label": "Saldo não informado pelo provedor",
        "quota_detail": None,
        "quota_checked_at": None,
    }


def fetch_provider_quota(provider: str, api_key: str | None = None) -> dict:
    """Fetch official provider quota on demand (only OpenRouter has an official endpoint)."""
    if provider != "openrouter":
        return default_quota_for(provider)
    key = (api_key if api_key is not None else _read_provider_key("openrouter")).strip()
    if not key:
        return default_quota_for("openrouter")

    checked_at = utc_now_iso()
    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/credits", headers=headers, timeout=8
        )
        if resp.status_code == 200:
            payload = resp.json() or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                total_credits = data.get("total_credits")
                total_usage = data.get("total_usage")
                if isinstance(total_credits, (int, float)) and isinstance(
                    total_usage, (int, float)
                ):
                    remaining = max(0.0, float(total_credits) - float(total_usage))
                    return {
                        "quota_available": True,
                        "quota_status": "available",
                        "quota_remaining": round(remaining, 6),
                        "quota_currency": "USD",
                        "quota_label": format_usd_ptbr(remaining),
                        "quota_detail": None,
                        "quota_checked_at": checked_at,
                    }
                limit_remaining = data.get("limit_remaining")
                if isinstance(limit_remaining, (int, float)):
                    remaining = max(0.0, float(limit_remaining))
                    return {
                        "quota_available": True,
                        "quota_status": "available",
                        "quota_remaining": round(remaining, 6),
                        "quota_currency": "USD",
                        "quota_label": format_usd_ptbr(remaining),
                        "quota_detail": None,
                        "quota_checked_at": checked_at,
                    }
        # Fallback to /api/v1/key if /credits didn't return balance fields
        key_resp = requests.get(
            "https://openrouter.ai/api/v1/key", headers=headers, timeout=8
        )
        if key_resp.status_code == 200:
            payload = key_resp.json() or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict) and isinstance(
                data.get("limit_remaining"), (int, float)
            ):
                remaining = max(0.0, float(data["limit_remaining"]))
                return {
                    "quota_available": True,
                    "quota_status": "available",
                    "quota_remaining": round(remaining, 6),
                    "quota_currency": "USD",
                    "quota_label": format_usd_ptbr(remaining),
                    "quota_detail": None,
                    "quota_checked_at": checked_at,
                }
            # Key is valid, but OpenRouter did not expose credit balance on /key
            return {
                "quota_available": False,
                "quota_status": "unavailable",
                "quota_remaining": None,
                "quota_currency": None,
                "quota_label": "Saldo não informado pelo provedor",
                "quota_detail": "Não foi possível consultar o saldo agora.",
                "quota_checked_at": checked_at,
            }
        return {
            "quota_available": False,
            "quota_status": "error",
            "quota_remaining": None,
            "quota_currency": None,
            "quota_label": "Saldo não informado pelo provedor",
            "quota_detail": "Não foi possível consultar o saldo agora.",
            "quota_checked_at": checked_at,
        }
    except Exception:
        return {
            "quota_available": False,
            "quota_status": "error",
            "quota_remaining": None,
            "quota_currency": None,
            "quota_label": "Saldo não informado pelo provedor",
            "quota_detail": "Não foi possível consultar o saldo agora.",
            "quota_checked_at": checked_at,
        }


def verify_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    """Perform a lightweight, non-paid verification of an API key."""
    key = (api_key or "").strip()
    if not key:
        return False, "Informe uma chave de API válida."
    meta = PROVIDER_META.get(provider)
    if not meta or meta["auth_type"] != "api_key":
        return False, "Provedor inválido para verificação por chave."
    pname = meta["name"]
    try:
        if provider == "openrouter":
            resp = requests.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                return True, ""
        elif provider == "gemini":
            resp = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": key},
                timeout=8,
            )
            if resp.status_code == 200:
                return True, ""
        elif provider == "groq":
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                return True, ""
        elif provider == "cloudflare":
            resp = requests.get(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                body = resp.json() if resp.content else {}
                if not isinstance(body, dict) or body.get("success", True) is not False:
                    return True, ""
        if resp.status_code in (400, 401, 403):
            return (
                False,
                f"A chave foi recusada pelo {pname}. Confira se copiou a chave inteira e tente de novo.",
            )
        return False, f"{pname} retornou erro temporário (HTTP {resp.status_code})."
    except Exception as exc:
        return False, sanitize_error(
            f"Não foi possível verificar a chave no {pname}: {exc}", (key,)
        )


def verify_ollama(host: str | None = None) -> tuple[str, str, list[str]]:
    """Check local Ollama service via /api/tags without paid generation."""
    base = (host or _local_host()).rstrip("/")
    try:
        resp = requests.get(f"{base}/api/tags", timeout=3)
        if resp.status_code != 200:
            return (
                "not_installed",
                f"O Ollama não respondeu em {base}. Abra o Ollama ou instale pelo site oficial.",
                [],
            )
        data = resp.json() if resp.content else {}
        models = []
        if isinstance(data, dict):
            for item in data.get("models", []) or []:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("name"), str)
                    and item["name"].strip()
                ):
                    models.append(item["name"].strip())
        return "connected", "", models
    except Exception:
        return (
            "not_installed",
            f"O Ollama não respondeu em {base}. Abra o Ollama ou instale pelo site oficial.",
            [],
        )


DEFAULT_PROVIDER_MODELS = {
    "openrouter": (
        {
            "id": "openrouter/openrouter/auto",
            "label": "Auto (OpenRouter)",
            "tier": "paid",
        },
        {
            "id": "openrouter/openai/gpt-4o-mini",
            "label": "openai/gpt-4o-mini",
            "tier": "paid",
        },
        {
            "id": "openrouter/anthropic/claude-3.5-sonnet",
            "label": "anthropic/claude-3.5-sonnet",
            "tier": "paid",
        },
        {
            "id": "openrouter/google/gemini-2.5-flash",
            "label": "google/gemini-2.5-flash",
            "tier": "paid",
        },
    ),
    "cloudflare": (
        {
            "id": "cloudflare/@cf/meta/llama-3.1-8b-instruct",
            "label": "@cf/meta/llama-3.1-8b-instruct",
            "tier": "free",
        },
    ),
    "groq": (
        {
            "id": "groq/openai/gpt-oss-120b",
            "label": "openai/gpt-oss-120b",
            "tier": "free",
        },
    ),
    "local": ({"id": "ollama/qwen3:8b", "label": "qwen3:8b", "tier": "local"},),
}


def _models_for_provider(
    provider: str, local_models: list[str] | None = None
) -> list[dict]:
    if provider == "codex":
        return [{"id": "codex", "label": "Padrão da conta (Codex CLI)"}]
    if provider == "agy":
        return [{"id": "agy", "label": "Padrão da conta (Google Antigravity)"}]

    from src.llm_routing import GEMINI_FREE_MODELS, catalog

    items = []
    seen = set()
    for entry in catalog():
        if entry.provider == provider and entry.model not in seen:
            seen.add(entry.model)
            label = (
                entry.model.split("/", 1)[1]
                if entry.model.startswith(provider + "/")
                else entry.model
            )
            items.append({"id": entry.model, "label": label, "tier": entry.tier})
    if provider == "local" and local_models:
        for name in local_models:
            qualified = name if name.startswith("ollama/") else f"ollama/{name}"
            if qualified not in seen and name not in seen:
                seen.add(qualified)
                items.append({"id": qualified, "label": name, "tier": "local"})
    if not items:
        if provider == "gemini":
            items = [
                {"id": f"gemini/{name}", "label": name, "tier": "free"}
                for name in GEMINI_FREE_MODELS
            ]
        else:
            items = [dict(item) for item in DEFAULT_PROVIDER_MODELS.get(provider, ())]
    return items


def build_provider_record(
    provider: str,
    tracker: ModelSessionTracker,
    *,
    verify_live: bool = False,
    refresh_quota: bool = False,
    override_status: tuple[str, str] | None = None,
) -> dict:
    """Build the status card dictionary for one canonical provider without leaking secrets."""
    meta = PROVIDER_META[provider]
    auth_type = meta["auth_type"]
    status = "login_required"
    status_detail = ""
    configured = False
    executable = None
    local_models: list[str] = []

    if auth_type == "cli":
        from Plugins.Connectors.agents import service as agents_service

        cli_info = agents_service.login_status(provider)
        status = cli_info.get("status", "not_installed")
        status_detail = (
            sanitize_error(cli_info.get("detail", "")) if cli_info.get("detail") else ""
        )
        executable = cli_info.get("executable")
        configured = status == "connected"
    elif auth_type == "api_key":
        key = _read_provider_key(provider)
        configured = bool(key)
        if override_status is not None:
            status, status_detail = override_status
        elif not key:
            status = "login_required"
        elif verify_live:
            ok, err = verify_api_key(provider, key)
            status = "connected" if ok else "error"
            status_detail = err
        else:
            status = "connected"
    elif auth_type == "local":
        if verify_live:
            status, status_detail, local_models = verify_ollama()
            if local_models:
                tracker.local_models_cache = list(local_models)
        else:
            status, status_detail, local_models = verify_ollama()
            if local_models:
                tracker.local_models_cache = list(local_models)
        configured = status == "connected"

    if override_status is not None and auth_type != "api_key":
        status, status_detail = override_status

    if provider == "openrouter":
        if refresh_quota or (verify_live and configured and status == "connected"):
            quota = fetch_provider_quota("openrouter")
            tracker.set_quota("openrouter", quota)
        else:
            quota = tracker.get_quota("openrouter") or default_quota_for("openrouter")
    else:
        quota = default_quota_for(provider)

    return {
        "id": provider,
        "name": meta["name"],
        "auth_type": auth_type,
        "status": status,
        "status_label": STATUS_LABELS.get(status, "Erro de autenticação"),
        "status_detail": status_detail,
        "configured": configured,
        "executable": executable,
        "login_command": meta.get("login_command"),
        "docs_url": meta["docs_url"],
        "models": _models_for_provider(
            provider, local_models or tracker.local_models_cache
        ),
        "session_usage": tracker.snapshot_usage(provider),
        "provider_quota": quota,
    }


def build_status_payload(
    store,
    tracker: ModelSessionTracker,
    *,
    verify_live: bool = False,
    refresh_quota: bool = False,
) -> dict:
    """Build the full GET/POST /api/pia/models/status payload."""
    from src import config

    default_sel = store.get("models:default", {}) if store is not None else {}
    if not isinstance(default_sel, dict):
        default_sel = {}
    default_provider = str(default_sel.get("provider", "") or "")
    default_model = str(default_sel.get("model", "") or "")
    effective_default_label = (
        default_model or default_provider or str(config.LLM_MODEL or "free")
    )

    providers = [
        build_provider_record(
            pid, tracker, verify_live=verify_live, refresh_quota=refresh_quota
        )
        for pid in PROVIDERS_ORDER
    ]
    return {
        "session_started_at": tracker.session_started_at,
        "total_requests": tracker.total_requests(),
        "default_provider": default_provider,
        "default_model": default_model,
        "effective_default_label": effective_default_label,
        "automatic_options": list(AUTOMATIC_OPTIONS),
        "providers": providers,
    }


def save_provider_key(provider: str, api_key: str) -> None:
    """Persist an API key into SystemVault via settings_store."""
    meta = PROVIDER_META.get(provider)
    if not meta or meta["auth_type"] != "api_key":
        raise ValueError("Provedor não utiliza chave de API.")
    get_store().save("general", {meta["key_name"]: (api_key or "").strip()})


def clear_provider_key(provider: str) -> None:
    """Remove an API key from SystemVault via settings_store."""
    meta = PROVIDER_META.get(provider)
    if not meta or meta["auth_type"] != "api_key":
        raise ValueError("Provedor não utiliza chave de API.")
    updates = {meta["key_name"]: ""}
    for fb in meta.get("fallback_keys", ()):
        updates[fb] = ""
    get_store().save("general", updates)


def infer_provider_from_selector(
    provider: str | None, model: str | None
) -> tuple[str, str]:
    """Normalize (provider, model) and detect if an explicit provider was requested."""
    prov = (provider or "").strip().lower()
    mod = (model or "").strip()

    if (
        prov in ("", "default", "free", "paid", "all", "my-agent", "gemini-local")
        and not mod
    ):
        return "", ""
    if not prov and mod in ("free", "paid", "all", "my-agent", "gemini-local"):
        return "", mod
    if prov in PROVIDERS_ORDER:
        return prov, mod
    if mod:
        lowered = mod.lower()
        for pid in ("codex", "agy"):
            if lowered == pid or lowered.startswith(pid + "/"):
                return pid, "" if lowered in (pid, f"{pid}/default") else mod.split(
                    "/", 1
                )[1]
        for pid in ("openrouter", "gemini", "groq", "cloudflare"):
            if lowered == pid or lowered.startswith(pid + "/"):
                return pid, mod
        if lowered == "local" or lowered.startswith("ollama/"):
            return "local", mod
    return prov, mod


def check_explicit_provider_ready(
    provider: str, tracker: ModelSessionTracker | None = None
) -> dict:
    """Validate that an explicit provider is connected; raise RuntimeError with pt-BR message if not."""
    if provider not in PROVIDERS_ORDER:
        raise ValueError(f"Provedor desconhecido: {provider}")
    active_tracker = tracker or ModelSessionTracker()
    record = build_provider_record(provider, active_tracker, verify_live=False)
    status = record["status"]
    name = record["name"]
    if status == "connected":
        return record
    if status == "not_installed":
        detail = (
            record.get("status_detail")
            or f"O {name} não está instalado neste computador."
        )
        raise RuntimeError(detail)
    if status == "login_required":
        if record["auth_type"] == "cli":
            raise RuntimeError(
                f"O {name} precisa de login para responder. Conecte em Provedores de modelos."
            )
        raise RuntimeError(
            f"O {name} precisa de uma chave configurada no Cofre da PIA para responder."
        )
    detail = (
        record.get("status_detail")
        or f"O {name} está com erro de autenticação. Reconecte em Provedores de modelos."
    )
    raise RuntimeError(detail)


def extract_usage_counts(
    response_or_chunk,
) -> tuple[int | None, int | None, int | None]:
    """Extract (prompt_tokens, completion_tokens, total_tokens) from a LiteLLM response/chunk or dict."""
    if response_or_chunk is None:
        return None, None, None
    usage = (
        response_or_chunk.get("usage")
        if isinstance(response_or_chunk, dict)
        else getattr(response_or_chunk, "usage", None)
    )
    if usage is None:
        return None, None, None
    if isinstance(usage, dict):
        p = usage.get("prompt_tokens", usage.get("input_tokens"))
        c = usage.get("completion_tokens", usage.get("output_tokens"))
        t = usage.get("total_tokens")
    else:
        p = getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", None))
        c = getattr(usage, "completion_tokens", getattr(usage, "output_tokens", None))
        t = getattr(usage, "total_tokens", None)
    return p, c, t


def explicit_model_candidate(expression: str | None):
    """Build a Model candidate when an explicit supported provider/model is requested outside LLM_PROVIDERS."""
    if not isinstance(expression, str) or not expression.strip():
        return None
    prov, mod = infer_provider_from_selector(None, expression)
    if prov not in ("openrouter", "gemini", "groq", "cloudflare", "local"):
        return None
    from src.llm_routing import Model

    if not mod or mod.lower() == prov:
        defaults = _models_for_provider(prov)
        if not defaults:
            return None
        qualified = defaults[0]["id"]
    elif prov == "local":
        qualified = mod if mod.startswith("ollama/") else f"ollama/{mod}"
    else:
        qualified = mod if mod.startswith(f"{prov}/") else f"{prov}/{mod}"

    api_key_env = ""
    meta = PROVIDER_META.get(prov, {})
    if meta.get("auth_type") == "api_key":
        primary = meta.get("key_name", "")
        if primary and not str(setting(primary, "") or "").strip():
            for fb in meta.get("fallback_keys", ()):
                if str(setting(fb, "") or "").strip():
                    api_key_env = fb
                    break
    return Model(
        prov, qualified, "local" if prov == "local" else "paid", api_key_env=api_key_env
    )

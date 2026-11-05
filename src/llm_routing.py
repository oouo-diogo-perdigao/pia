"""Ordered model catalog and selection expressions for chat-capable LLMs."""
from __future__ import annotations
from src.settings_store import get as setting

from dataclasses import dataclass
import json
import os
import re

from . import config

TIERS = {"local": {"local"}, "free": {"free", "local"},
         "paid": {"paid", "free", "local"}, "all": {"paid", "free", "local"}}
GEMINI_FREE_MODELS = (
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash",
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite",
)


@dataclass(frozen=True)
class Model:
    provider: str
    model: str
    tier: str
    api_key_env: str = ""
    api_base_env: str = ""

    @property
    def key(self):
        return self.provider, self.model

    def params(self):
        if self.tier == "local":
            base = setting(self.api_base_env, "") if self.api_base_env else config.LLM_LOCAL_API_BASE
            return {"model": self.model, "api_base": base or config.LLM_LOCAL_API_BASE}
        key_name = self.api_key_env or {
            "gemini": "AGE_GEMINI_API_KEY", "groq": "GROQ_API_KEY",
        }.get(self.provider, self.provider.upper() + "_API_KEY")
        key = setting(key_name, "").strip()
        if self.provider == "gemini" and not self.api_key_env:
            key = config.AGE_GEMINI_API_KEY or setting("GEMINI_API_KEY", "").strip()
        if self.provider == "groq" and not self.api_key_env:
            key = config.GROQ_API_KEY
        if not key:
            return None
        params = {"model": self.model, "api_key": key}
        base_name = self.api_base_env or "LLM_" + self.provider.upper() + "_API_BASE"
        if base := setting(base_name, "").strip():
            params["api_base"] = base
        return params


def _names(name, default):
    return tuple(value.strip() for value in setting(name, default).split(",") if value.strip())


def catalog():
    """Keep provider priority and each provider's configured model order."""
    entries = []
    providers = tuple(dict.fromkeys(config.LLM_PROVIDERS or ("local",)))
    for provider in providers:
        prefix = "LLM_" + provider.upper()
        if provider == "local":
            entries.extend(Model(provider, name, "local") for name in _names("LLM_LOCAL_MODELS", config.LLM_LOCAL_MODEL))
            continue
        default = ",".join(GEMINI_FREE_MODELS) if provider == "gemini" else (
            config.LLM_GROQ_MODEL if provider == "groq" else "")
        for tier in ("free", "paid"):
            for name in _names(prefix + "_" + tier.upper() + "_MODELS", default if tier == "free" else ""):
                # Catalog names use LiteLLM's provider-qualified IDs.
                model = name if name.startswith(provider + "/") else provider + "/" + name
                entries.append(Model(provider, model, tier))
    # Optional custom providers, tier classification and credential/base bindings.
    for item in json.loads(config.LLM_MODEL_CATALOG):
        entry = Model(**item)
        if entry.tier not in ("local", "free", "paid") or not re.fullmatch(r"[a-z][a-z0-9_]*", entry.provider):
            raise ValueError("Provider ou tier inválido em LLM_MODEL_CATALOG.")
        if not entry.model:
            raise ValueError("Modelo vazio em LLM_MODEL_CATALOG.")
        entries.append(entry)
    return tuple(dict.fromkeys(entries))


def select_models(expression=None, models=None):
    models = catalog() if models is None else models
    expression = config.LLM_MODEL if expression is None else expression
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("O modelo/seletor LLM deve ser texto não vazio.")
    expression = expression.strip()
    # Legacy public aliases continue to use the configured default policy.
    if expression in ("my-agent", "gemini-local"):
        expression = config.LLM_MODEL
    # Exact IDs can contain '-' and '+', so resolve them before parsing selectors.
    exact = [m for m in models if expression == m.model]
    if exact:
        return tuple(dict.fromkeys(exact))
    providers = {m.provider for m in models} | {"gemini", "groq", "local", "openrouter", "cloudflare"}
    token = re.compile(r"([+-]?)([a-z][a-z0-9_]*)(?:=(all|paid|free|local))?")
    selected = set()
    position = 0
    first = True
    while position < len(expression):
        match = token.match(expression, position)
        if not match or (not first and not match[1]):
            raise ValueError(f"Seletor LLM inválido: {expression}")
        sign, name, tier = match.groups()
        if name not in TIERS and name not in providers:
            raise ValueError(f"Provider LLM desconhecido: {name}")
        if tier and name not in providers:
            raise ValueError("Qualificadores '=tier' exigem um provider.")
        if first and sign == "-":
            selected.update(models)
        levels = TIERS[tier or name] if (tier or name) in TIERS else TIERS["all"]
        matches = {m for m in models if m.tier in levels and (name in TIERS and not tier or m.provider == name)}
        if sign == "-":
            selected.difference_update(matches)
        else:
            selected.update(matches)
        position = match.end()
        first = False
    return tuple(m for m in models if m in selected)

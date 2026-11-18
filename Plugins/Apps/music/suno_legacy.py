"""Old local Suno credentials on this computer (RN17/CA15).

Before the PIA Server took over the Suno OAuth, the PIA kept Suno credentials
locally: ``mcp:connector:suno_mcp:*`` vault/keyring entries, the
``MUSIC_SUNO_MCP_*`` settings (token included) and the local MCP server
``suno_mcp``. The PIA no longer reads any of them (RN18).

Nothing here deletes automatically: not on startup, import or profile sync.
Detection only reads names (``vault_entries``, settings rows, the server
list), never a secret value. ``remove_legacy`` deletes only after an explicit
``confirm: true``; ``dismiss_legacy`` ("Agora não") deletes nothing.
"""

from __future__ import annotations

from typing import Any

LEGACY_SERVER_ID = "suno_mcp"
LEGACY_VAULT_PREFIX = "mcp:connector:suno_mcp:"
LEGACY_SETTINGS_SECTION = "Apps/music"
LEGACY_SETTINGS = (
    "MUSIC_SUNO_MCP_TOKEN",
    "MUSIC_SUNO_MCP_URL",
    "MUSIC_SUNO_MCP_COMMAND",
    "MUSIC_SUNO_MCP_TOOL",
    "MUSIC_SUNO_TIMEOUT",
)
# Device-local flag (values_store, not exported nor synced): "Agora não".
DISMISSED_KEY = "music:suno_legacy_credentials_dismissed"
_VAULT_FIELDS = {
    "oauth_access_token": "Token de acesso OAuth",
    "oauth_refresh_token": "Token de renovação OAuth",
    "oauth_client_secret": "Client secret OAuth",
    "bearer_token": "Token bearer",
}
_SETTING_LABELS = {
    "MUSIC_SUNO_MCP_TOKEN": "Token do Suno nas configurações de Música",
    "MUSIC_SUNO_MCP_URL": "URL do Suno MCP nas configurações de Música",
    "MUSIC_SUNO_MCP_COMMAND": "Comando do Suno MCP nas configurações de Música",
    "MUSIC_SUNO_MCP_TOOL": "Ferramenta do Suno MCP nas configurações de Música",
    "MUSIC_SUNO_TIMEOUT": "Tempo limite do Suno nas configurações de Música",
}
SERVER_LABEL = "Servidor MCP local do Suno (suno_mcp)"
CONFIRMATION_MESSAGE = (
    "Confirme a remoção das credenciais antigas do Suno deste computador."
)


class LegacyConfirmationRequired(ValueError):
    """``remove`` without ``confirm: true``: HTTP 400 with a stable code."""

    code = "confirmation_required"

    def __init__(self) -> None:
        super().__init__(CONFIRMATION_MESSAGE)


def _setting_ref(name: str) -> str:
    return f"setting:{LEGACY_SETTINGS_SECTION}:{name}"


def _stores(store: Any = None, manager: Any = None) -> tuple[Any, Any]:
    if store is None:
        from src.settings_store import get_store

        store = get_store()
    if manager is None:
        from src.mcp_connectors import get_mcp_manager

        manager = get_mcp_manager()
    return store, manager


def _vault_label(name: str) -> str:
    rest = name[len(LEGACY_VAULT_PREFIX) :]
    scope, _, field = rest.rpartition(":")
    base = _VAULT_FIELDS.get(field, "Credencial")
    where = "servidor" if scope == "_server" else f"conta {scope or 'padrão'}"
    return f"{base} do Suno ({where})"


def _legacy_server(manager: Any) -> dict[str, Any] | None:
    try:
        servers = manager._raw_servers()
    except Exception:
        return None
    return next(
        (s for s in servers if isinstance(s, dict) and s.get("id") == LEGACY_SERVER_ID),
        None,
    )


def _registered_names(store: Any) -> list[str]:
    return sorted(
        str(row[0])
        for row in store.rows("vault_entries")
        if str(row[0]).startswith(LEGACY_VAULT_PREFIX)
    )


def _legacy_setting_names(store: Any) -> list[str]:
    present = {
        str(row[1])
        for row in store.rows("settings")
        if row[0] == LEGACY_SETTINGS_SECTION and row[1] in LEGACY_SETTINGS
    }
    registered = {str(row[0]) for row in store.rows("vault_entries")}
    present.update(n for n in LEGACY_SETTINGS if _setting_ref(n) in registered)
    return [n for n in LEGACY_SETTINGS if n in present]


def legacy_items(store: Any = None, manager: Any = None) -> list[dict[str, str]]:
    """Labels of the old Suno entries found. Names only, never values."""
    store, manager = _stores(store, manager)
    items = [
        {"kind": "vault", "label": _vault_label(n)} for n in _registered_names(store)
    ]
    items += [
        {"kind": "setting", "label": _SETTING_LABELS[n]}
        for n in _legacy_setting_names(store)
    ]
    if _legacy_server(manager) is not None:
        items.append({"kind": "mcp_server", "label": SERVER_LABEL})
    return items


def _dismissed(manager: Any) -> bool:
    try:
        return bool(manager.store.get(DISMISSED_KEY, False))
    except Exception:
        return False


def legacy_state(store: Any = None, manager: Any = None) -> dict[str, Any]:
    """``GET /music/suno/legacy-credentials``: {present, prompt, items}."""
    store, manager = _stores(store, manager)
    items = legacy_items(store, manager)
    present = bool(items)
    return {
        "present": present,
        "prompt": present and not _dismissed(manager),
        "items": items,
    }


def dismiss_legacy(store: Any = None, manager: Any = None) -> dict[str, Any]:
    """ "Agora não": deletes nothing; only turns the first-start question off."""
    store, manager = _stores(store, manager)
    manager.store.set(DISMISSED_KEY, True)
    return {"ok": True, **legacy_state(store, manager), "prompt": False}


def remove_legacy(
    payload: dict[str, Any] | None = None, store: Any = None, manager: Any = None
) -> dict[str, Any]:
    """Delete the old Suno entries, only with ``{"confirm": true}``."""
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise LegacyConfirmationRequired()
    store, manager = _stores(store, manager)
    before = legacy_items(store, manager)

    server = _legacy_server(manager)
    scopes = {"_server", "default"}
    for acc in (server or {}).get("accounts") or []:
        if isinstance(acc, dict) and acc.get("id"):
            scopes.add(str(acc["id"]))
    # Delete by name: registered names plus the known per-account names (a
    # keyring entry may exist without its vault_entries row). No value is read.
    names = set(_registered_names(store))
    names.update(
        f"{LEGACY_VAULT_PREFIX}{scope}:{field}"
        for scope in scopes
        for field in _VAULT_FIELDS
    )
    failed = []
    for name in sorted(names):
        try:
            manager.vault.delete(name)
        except Exception:
            failed.append(name)
    refs = [_setting_ref(n) for n in LEGACY_SETTINGS]
    for ref in refs:
        try:
            store.vault.delete(ref)
        except Exception:
            failed.append(ref)
    removed_names = (names | set(refs)) - set(failed)
    with store.connection() as db:
        db.executemany(
            "DELETE FROM vault_entries WHERE name=?",
            ((name,) for name in sorted(removed_names)),
        )
        db.executemany(
            "DELETE FROM settings WHERE section=? AND name=?",
            (
                (LEGACY_SETTINGS_SECTION, n)
                for n in LEGACY_SETTINGS
                if _setting_ref(n) not in failed
            ),
        )
    if server is not None:
        try:
            with manager._store_lock:
                manager.delete_server(LEGACY_SERVER_ID)
        except KeyError:
            pass
    manager.store.set(DISMISSED_KEY, True)
    after = legacy_items(store, manager)
    removed = [item["label"] for item in before if item not in after]
    if failed:
        raise RuntimeError(
            "Não foi possível remover todas as credenciais antigas do Suno do cofre. "
            "Tente de novo."
        )
    return {"ok": True, "removed": removed, "present": bool(after), "prompt": False}

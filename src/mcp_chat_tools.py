"""Compatibility shim delegating native plugin tools through PluginHost."""

from __future__ import annotations

from typing import Any

from .integrations.plugins.host import get_plugin_host
from .user_paths import user_path

_STORAGE_FACTORY: Any = None


def _get_storage() -> Any:
    if _STORAGE_FACTORY is not None:
        return _STORAGE_FACTORY()
    mod = get_plugin_host().load_tools_module("object_storage")
    return mod._get_storage()


def take_screenshot() -> dict[str, Any]:
    return get_plugin_host().call_tool(
        "screenshots", "pia_screenshot", user_path_fn=user_path
    )


def storage_list(
    *,
    account: str | None = None,
    bucket: str | None = None,
    prefix: str = "",
    query: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    return get_plugin_host().call_tool(
        "object_storage",
        "pia_storage_list",
        account=account,
        bucket=bucket,
        prefix=prefix,
        query=query,
        limit=limit,
        storage_factory=_get_storage,
    )


def storage_get(
    key: str,
    *,
    account: str | None = None,
    bucket: str | None = None,
    max_chars: int = 24000,
) -> dict[str, Any]:
    return get_plugin_host().call_tool(
        "object_storage",
        "pia_storage_get",
        key,
        account=account,
        bucket=bucket,
        max_chars=max_chars,
        storage_factory=_get_storage,
    )


def rpg_sessions(
    *,
    action: str = "latest",
    campaign: str = "",
    session: str = "",
    max_chars: int = 18000,
) -> dict[str, Any]:
    return get_plugin_host().call_tool(
        "podcast_automation",
        "pia_rpg_sessions",
        action=action,
        campaign=campaign,
        session=session,
        max_chars=max_chars,
        storage_factory=_get_storage,
        user_path_fn=user_path,
    )


def call_suno_mcp(
    prompt: str,
    *,
    lyrics: str = "",
    duration: int = 30,
    suno_url: str = "",
    suno_cmd: str = "",
    suno_token: str = "",
) -> dict[str, Any]:
    return get_plugin_host().call_tool(
        "music",
        "pia_music_suno_mcp",
        prompt,
        lyrics=lyrics,
        duration=duration,
        suno_url=suno_url,
        suno_cmd=suno_cmd,
        suno_token=suno_token,
    )

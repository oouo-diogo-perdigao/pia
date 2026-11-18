"""Suno clip helpers owned by the music plugin.

The direct Suno MCP client (``call_suno_mcp``, ``SunoMcpAdapter``, tool
discovery and the ``pia_music_suno_mcp`` chat tool) was removed in T8 (RN18):
the PIA Server is the only one that talks to the Suno. What is left are pure
helpers used to save a clip (``service._save_suno_clip``).
"""

from __future__ import annotations

from typing import Any

TASK_ID_FIELDS = ("clip_id", "task_id", "song_id", "id")
FAILED_STATES = {"error", "failed", "failure", "cancelled", "canceled"}


def extract_clips(data: dict[str, Any]) -> list[dict[str, Any]]:
    """All clips of a normalized result (``clips``/``songs``/``data``/``results``)."""
    for key in ("clips", "songs", "data", "results"):
        items = data.get(key)
        if isinstance(items, list) and items:
            return [dict(c) for c in items if isinstance(c, dict)]
    if any(k in data for k in ("audio_url", "audio_base64", *TASK_ID_FIELDS)):
        return [dict(data)]
    return []


def clip_id(clip: dict[str, Any]) -> str:
    for field in TASK_ID_FIELDS:
        value = clip.get(field)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def clip_state(clip: dict[str, Any]) -> str:
    """``ready`` (has audio), ``failed`` or ``pending`` (still generating)."""
    if (isinstance(clip.get("audio_base64"), str) and clip["audio_base64"]) or (
        isinstance(clip.get("audio_url"), str) and clip["audio_url"]
    ):
        return "ready"
    status = str(clip.get("status") or "").strip().lower()
    if status in FAILED_STATES or clip.get("error") or not clip_id(clip):
        return "failed"
    return "pending"


def register_tools(ctx: Any) -> None:
    """No chat tool: Suno in the chat (Q6) will go through the PIA Server."""
    return None

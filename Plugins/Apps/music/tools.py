"""Chat tools of the music plugin.

The direct Suno MCP client (``call_suno_mcp``, ``SunoMcpAdapter``, tool
discovery and the ``pia_music_suno_mcp`` chat tool) was removed in T8 (RN18)
and the clip helpers of the per-call MCP batch in T9: the PIA Server is the
only one that talks to the Suno (``remote_suno``).
"""

from __future__ import annotations

from typing import Any


def register_tools(ctx: Any) -> None:
    """No chat tool: Suno in the chat (Q6) will go through the PIA Server."""
    return None

"""Workspace API route registration."""

from __future__ import annotations

from . import bots, chat, mcp, plugins, settings, skills, tts


def register_all(router) -> None:
    for mod in (tts, chat, mcp, plugins, skills, settings, bots):
        mod.register(router)

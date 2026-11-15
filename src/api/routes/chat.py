"""Chat routes for /api/pia/chat/*."""

from __future__ import annotations

from src.ai.llm import available_chat_models


def _chat_models(ctx, data, query):
    return available_chat_models()


def register(router) -> None:
    router.add(
        "GET",
        "/chat/models",
        _chat_models,
        description="Listar modelos de chat disponíveis",
    )

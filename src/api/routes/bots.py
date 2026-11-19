"""Bots routes for /api/pia/bots/*."""

from __future__ import annotations


def _list_bots(ctx, data, query):
    return ctx.bot_records()


def _bot_chat(ctx, data, query):
    bot_id = data.get("bot_id") or data.get("agent_id") or "secretaria"
    chat = data.get("chat")
    if not chat:
        key = f"bot_chat:{bot_id}"
        chat = ctx.store.get(key)
        if not chat or not any(c["id"] == chat for c in ctx.store.chat_records()):
            chat = ctx.store.new_chat(f"Bot · {bot_id}")
            ctx.store.set(key, chat)
    job = ctx.send(
        chat,
        data["text"],
        data.get("request"),
        model=data.get("model"),
        bot_id=bot_id,
        system_prompt=data.get("system_prompt"),
    )
    return {"job": job, "chat": chat, "bot_id": bot_id}


def register(router) -> None:
    router.add("GET", "/bots", _list_bots, description="Listar bots disponíveis")
    router.add(
        "POST", "/bots/chat", _bot_chat, description="Enviar mensagem direta a um bot"
    )

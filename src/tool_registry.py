"""One tool catalogue for the workspace, skills, MCP and agent transports."""

import base64
import json


def spec(name, description, properties, required=()):
    return dict(
        name=name,
        description=description,
        inputSchema=dict(
            type="object",
            properties=properties,
            required=list(required),
            additionalProperties=False,
        ),
    )


TOOLS = [
    spec("pia_accounts", "Listar contas dos conectores, sem credenciais.", {}),
    spec(
        "pia_resources",
        "Consultar recursos de uma conta explicitamente escolhida.",
        {
            "plugin": {"type": "string", "enum": ["google", "microsoft"]},
            "account": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["mail.list", "calendar.list", "files.list", "drive.folders"],
            },
            "params": {"type": "object"},
        },
        ("plugin", "account", "operation"),
    ),
    spec(
        "pia_camera",
        "Tirar uma foto da câmera somente quando solicitado.",
        {"device": {"type": "integer", "minimum": 0, "maximum": 16}},
    ),
    spec(
        "pia_image",
        "Gerar imagem com a PIA.",
        {"prompt": {"type": "string"}},
        ("prompt",),
    ),
    spec(
        "pia_music",
        "Gerar uma música com descrição e letra opcional (local, gemini ou suno_mcp).",
        {
            "prompt": {"type": "string"},
            "lyrics": {"type": "string"},
            "provider": {"type": "string", "enum": ["local", "gemini", "suno_mcp"]},
            "duration": {"type": "integer", "minimum": 10, "maximum": 180},
        },
        ("prompt",),
    ),
    spec(
        "pia_screenshot",
        "Capturar um print da tela atual do computador e retornar a URL da imagem.",
        {},
    ),
    spec(
        "pia_storage_list",
        "Listar buckets ou objetos no conector Object Storage (S3/R2).",
        {
            "account": {"type": "string"},
            "bucket": {"type": "string"},
            "prefix": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
    ),
    spec(
        "pia_storage_get",
        "Ler o conteúdo de texto de um arquivo no bucket Object Storage.",
        {
            "key": {"type": "string"},
            "account": {"type": "string"},
            "bucket": {"type": "string"},
        },
        ("key",),
    ),
    spec(
        "pia_rpg_sessions",
        "Consultar campanhas e sessões de RPG nos buckets/cache (list, latest ou transcript com busca aproximada).",
        {
            "action": {"type": "string", "enum": ["list", "latest", "transcript"]},
            "campaign": {"type": "string"},
            "session": {"type": "string"},
        },
    ),
    spec(
        "pia_delegate",
        "Perguntar ao Codex CLI ou Google Antigravity CLI (agy), usando seu login existente.",
        {
            "provider": {"type": "string", "enum": ["codex", "agy"]},
            "prompt": {"type": "string"},
        },
        ("provider", "prompt"),
    ),
    spec(
        "delegate_to_bot",
        "Delegar uma tarefa para um Bot Dinâmico (OpenBot) habilitado.",
        {
            "bot_id": {"type": "string"},
            "task": {"type": "string"},
        },
        ("bot_id", "task"),
    ),
]


def call(name, arguments, resources=None):
    from jsonschema import validate

    entry = next((t for t in TOOLS if t["name"] == name), None)
    if not entry:
        raise ValueError("Ferramenta desconhecida.")
    validate(arguments, entry["inputSchema"])
    if name in ("pia_accounts", "pia_resources"):
        from .resource_plugins import get_resources

        resources = resources or get_resources()
        if name == "pia_accounts":
            return resources.accounts()
        return resources.call(
            arguments["plugin"],
            arguments["operation"],
            account=arguments["account"],
            **arguments.get("params", {}),
        )
    if name == "pia_camera":
        from .camera import capture

        return {
            "mimeType": "image/png",
            "data": base64.b64encode(capture(arguments.get("device", 0))).decode(),
        }
    if name == "pia_image":
        from .chat_tools import ChatTools

        return {"markdown": ChatTools().generate_image(arguments["prompt"])}
    if name == "delegate_to_bot":
        from Plugins.OpenBot.runtime import get_openbot_runtime

        return get_openbot_runtime().delegate_to_bot(
            target_bot_id=arguments["bot_id"],
            task=arguments["task"],
        )
    if name == "pia_music":
        from Plugins.Apps.music.service import generate

        return generate(**arguments)
    if name == "pia_screenshot":
        from .mcp_chat_tools import take_screenshot

        return take_screenshot()
    if name == "pia_storage_list":
        from .mcp_chat_tools import storage_list

        return storage_list(**arguments)
    if name == "pia_storage_get":
        from .mcp_chat_tools import storage_get

        return storage_get(**arguments)
    if name == "pia_rpg_sessions":
        from .mcp_chat_tools import rpg_sessions

        return rpg_sessions(**arguments)
    if name == "pia_delegate":
        from Plugins.Connectors.agents.service import ask

        return ask(**arguments)


def complete_with_tools(
    agent, messages, model=None, allowed=None, on_delta=None, return_meta=False
):
    """Bounded real function calling. Model-supplied names cannot bypass allowlists."""
    selected = [t for t in TOOLS if t["name"] in (allowed or ())]
    history = list(messages)
    tools_used = []
    attachments = []
    for _ in range(6):
        response = agent.complete(
            history,
            model=model,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["inputSchema"],
                    },
                }
                for t in selected
            ],
        )
        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None)
        if not calls:
            text = message.content or ""
            if on_delta:
                on_delta(text)
            if return_meta:
                return {
                    "text": text,
                    "tools_used": tools_used,
                    "attachments": attachments,
                }
            return text
        history.append(message.model_dump(exclude_none=True))
        for tool in calls:
            if tool.function.name not in {t["name"] for t in selected}:
                raise ValueError("Ferramenta não autorizada nesta conversa.")
            tools_used.append(f"mcp:{tool.function.name}")
            try:
                result = call(tool.function.name, json.loads(tool.function.arguments))
                if isinstance(result, dict):
                    if result.get("image_url"):
                        attachments.append(
                            {"type": "image", "url": result["image_url"]}
                        )
                    if result.get("audio_url"):
                        attachments.append(
                            {"type": "audio", "url": result["audio_url"]}
                        )
            except Exception as exc:
                result = {"error": str(exc)}
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tool.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
    raise RuntimeError("Limite de chamadas de ferramentas excedido.")

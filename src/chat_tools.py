from src.user_paths import user_path

"""Workspace tools route explicit requests to PIA; generated assets survive API cache expiry."""
import base64
import io
import json
from pathlib import Path
import re
import unicodedata
import uuid
import requests
from . import app_access
from .config_paths import BASE_DIR

MARKDOWN_INSTRUCTION = "Responda sempre em Markdown legível, em português. Use títulos, listas, tabelas e blocos de código quando ajudarem. Não envolva a resposta inteira em uma cerca de código Markdown. Não afirme que executou uma ação ou criou uma imagem se uma ferramenta não foi executada."


def save_camera(result):
    root = user_path("chat")
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ".png"
    (root / name).write_bytes(base64.b64decode(result["data"], validate=True))
    return "![Foto da câmera](/api/pia/chat/assets/" + name + ")"


def allowed_tools(text, history=None):
    plain = (
        unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    )
    tools = set()
    if re.search(
        r"\b(agenda|compromissos?|email|gmail|drive|arquivos|contas|calendario)\b",
        plain,
    ):
        tools.update(("pia_accounts", "pia_resources"))
    if re.search(r"\b(codex|agy|antigravity)\b", plain):
        tools.add("pia_delegate")
    if re.search(r"\b(print|screenshot|captura de tela|capture a tela|tela)\b", plain):
        tools.add("pia_screenshot")
    if re.search(
        r"\b(bucket|buckets|s3|r2|sessao|sessoes|rpg|transcricao|transcricoes|campanha|origem|destructo|destructor|arquivo|arquivos)\b",
        plain,
    ):
        tools.update(("pia_storage_list", "pia_storage_get", "pia_rpg_sessions"))
    if re.search(r"\b(musica|musicas|cancao|cancoes|suno|song|music|melodia)\b", plain):
        tools.add("pia_music")
    if re.search(
        r"\b(bloco de notas|notepad|calculadora|explorador|skill|executar|abrir|iniciar)\b",
        plain,
    ):
        tools.add("pia_run_skill")
    try:
        from .mcp_connectors import get_mcp_manager

        for cspec in get_mcp_manager().chat_tool_specs():
            sname = (
                unicodedata.normalize("NFKD", cspec["server_name"].lower())
                .encode("ascii", "ignore")
                .decode()
            )
            tname = cspec["tool_name"].lower()
            if (
                "mcp" in plain
                or any(tok in plain for tok in sname.split() if len(tok) > 2)
                or tname.replace("_", " ") in plain
            ):
                tools.add(cspec["name"])
    except Exception:
        pass
    return tools


def image_intent(text):
    plain = "".join(
        c
        for c in unicodedata.normalize("NFD", text.lower())
        if not unicodedata.combining(c)
    ).strip()
    if re.match(r"^(como|explique|o que|qual|nao|não)\b", plain):
        return False
    image = re.search(
        r"\b(imagem|imagens|image|images|ilustracao|foto|fotografia|desenho|arte)\b",
        plain,
    )
    purpose = re.search(
        r"\b(texto|explicacao|tutorial|codigo|prompt|instrucoes)\b", plain
    )
    if image and purpose and purpose.start() < image.start():
        return False
    # Explicit imperatives and polite requests; questions about image generation stay textual.
    return bool(
        re.match(
            r"^(?:(?:por favor[, ]*|pia[, ]*|agora[, ]*)|(?:voce (?:pode|consegue)\s+)|(?:pode\s+))*"
            r"(?:(?:gere|gerar|crie|criar|faca|fazer|generate|create)\b[^\n]{0,100}\b(?:imagem|imagens|image|images|ilustracao|foto|fotografia|desenho|arte)\b|(?:desenhe|draw|ilustre)\b)",
            plain,
        )
    )


def _strip_accents(text: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", (text or "").lower())
        if not unicodedata.combining(c)
    ).strip()


def music_intent(text: str) -> bool:
    plain = _strip_accents(text)
    if re.match(r"^(como|explique|o que|qual|nao)\b", plain):
        return False
    purpose = re.search(
        r"\b(texto|explicacao|tutorial|codigo|prompt|instrucoes)\b", plain
    )
    music = re.search(
        r"\b(musica|musicas|cancao|cancoes|song|music|melodia|suno)\b", plain
    )
    if music and purpose and purpose.start() < music.start():
        return False
    return bool(
        re.match(
            r"^(?:(?:por favor[, ]*|pia[, ]*|agora[, ]*)|(?:voce (?:pode|consegue)\s+)|(?:pode\s+))*"
            r"(?:(?:gere|gerar|crie|criar|faca|fazer|componha|compor|generate|create)\b[^\n]{0,120}\b(?:musica|musicas|cancao|cancoes|song|music|melodia|suno)\b)",
            plain,
        )
    )


def parse_music_request(text: str) -> dict[str, str | None]:
    raw = (text or "").strip()
    plain = _strip_accents(raw)
    provider = "suno_mcp" if re.search(r"\bsuno\b", plain) else None

    cleaned = re.sub(
        r"^(?:(?:por favor|pia|agora)[, ]+|(?:voce\s+(?:pode|consegue)|pode)\s+)*",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^(?:gere|gerar|crie|criar|faça|faca|componha|compor|generate|create)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^(?:no\s+suno|na\s+suno|usando\s+(?:o\s+)?suno|com\s+(?:o\s+)?suno)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^(?:uma\s+|um\s+)?(?:m[uú]sica|can[cç][aã]o|melodia|song|music)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^(?:no\s+suno|na\s+suno|usando\s+(?:o\s+)?suno|com\s+(?:o\s+)?suno)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^(?:sobre|de|com\s+o\s+tema|about)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    prompt = cleaned or raw
    style = "Alegre / Pop" if "alegre" in plain or "feliz" in plain else "Personalizado"
    style_match = re.search(
        r"\b(?:estilo|genero|no\s+estilo|style)\s+([^,.;\n]+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if style_match:
        style = style_match.group(1).strip()

    title_words = [w for w in re.split(r"\s+", prompt) if w][:6]
    title = " ".join(title_words).strip(" .!?\"'").title() or "Nova Música"
    return {
        "prompt": prompt,
        "provider": provider,
        "title": title,
        "style": style,
    }


class ChatTools:
    def __init__(self, root=None, base_url=None, session=None, timeout=3600):
        self.root = Path(root or user_path("chat"))
        self.base_url = base_url
        self.session = session or requests.Session()
        self.timeout = timeout
        self.last_meta: dict = {}
        if session is None:
            self.session.trust_env = False

    def execute(self, text):
        self.last_meta = {}
        plain = (
            unicodedata.normalize("NFKD", text.lower())
            .encode("ascii", "ignore")
            .decode()
        )
        if re.search(
            r"\b(tire|tirar|capture|capturar|fotografe)\b", plain
        ) and re.search(r"\b(camera|webcam)\b", plain):
            from .tool_registry import call

            self.last_meta = {"tools_used": ["pia_camera"]}
            return save_camera(call("pia_camera", {}))
        if music_intent(text):
            return self.generate_music(text)
        if not image_intent(text):
            return None
        self.last_meta = {"tools_used": ["pia_image"]}
        return self.generate_image(text)

    def generate_music(self, text: str) -> str:
        from Plugins.Apps.music import service as music_service

        parsed = parse_music_request(text)
        prompt = parsed["prompt"] or text
        provider = parsed["provider"]
        title = parsed["title"] or "Nova Música"
        style = parsed["style"] or "Personalizado"
        try:
            item = music_service.generate(
                prompt=prompt,
                provider=provider,
            )
        except Exception as exc:
            self.last_meta = {"tools_used": ["pia_music"]}
            return (
                "### Não foi possível concluir a geração musical\n\n"
                f"- **Prompt:** {prompt}\n"
                f"- **Provedor:** `{provider or 'padrão'}`\n"
                f"- **Motivo:** {exc}\n\n"
                "Verifique a configuração do provedor em **Configurações → Música** e tente novamente."
            )

        audio_url = item.get("url") or ""
        used_provider = item.get("provider") or provider or "music"
        attachment = {
            "type": "audio",
            "title": title,
            "prompt": prompt,
            "style": style,
            "provider": used_provider,
            "url": audio_url,
            "file": item.get("file"),
        }
        self.last_meta = {
            "tools_used": ["pia_music"],
            "attachments": [attachment] if audio_url else [],
        }
        lines = [
            f"### Música criada: {title}",
            "",
            f"- **Tema / Prompt:** {prompt}",
            f"- **Estilo:** {style}",
            f"- **Provedor:** `{used_provider}`",
        ]
        if audio_url:
            lines.append(f"- **Áudio:** [Ouvir ou baixar música]({audio_url})")
        return "\n".join(lines)

    def generate_image(self, prompt):
        context = app_access.issue("pia_chat", routes={"/v1/images/generations"})
        try:
            settings = json.loads(context)
            base = self.base_url or settings["url"]
            try:
                response = self.session.post(
                    base.rstrip("/") + "/v1/images/generations",
                    json={"prompt": prompt, "n": 1, "response_format": "b64_json"},
                    headers={"X-PIA-App-Token": settings["token"]},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise RuntimeError(
                    "Não foi possível acessar a rota de geração de imagens da PIA."
                ) from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    "A rota de imagens não retornou JSON válido."
                ) from exc
            if response.status_code >= 400:
                detail = (
                    data.get("error", {}).get("message", "Falha na geração de imagem.")
                    if isinstance(data, dict)
                    else "Falha na geração de imagem."
                )
                raise RuntimeError(
                    f"PIA: geração de imagem retornou HTTP {response.status_code}. {detail}"
                )
            entries = data.get("data", []) if isinstance(data, dict) else []
            if not entries:
                raise RuntimeError("A PIA não retornou uma imagem gerada.")
            from PIL import Image

            links = []
            for entry in entries[:4]:
                encoded = entry.get("b64_json", "")
                if not isinstance(encoded, str) or len(encoded) > 40 * 1024**2:
                    raise RuntimeError(
                        "A imagem retornada é inválida ou excede 30 MiB."
                    )
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    with Image.open(io.BytesIO(raw)) as image:
                        kind = image.format
                        image.verify()
                    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[kind]
                except Exception as exc:
                    raise RuntimeError(
                        "A PIA retornou dados de imagem inválidos."
                    ) from exc
                self.root.mkdir(parents=True, exist_ok=True)
                name = uuid.uuid4().hex + "." + extension
                (self.root / name).write_bytes(raw)
                links.append(
                    "![Imagem gerada pela PIA](/api/pia/chat/assets/" + name + ")"
                )
            return "\n\n".join(links)
        finally:
            app_access.revoke(context)

"""Modelos, validação e sanitização segura de SVG para Bots Dinâmicos (OpenBot)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

MAX_SVG_BYTES = 256 * 1024
MAX_SVG_NODES = 1000
MAX_SVG_DEPTH = 32

FACE_TYPES = (
    "orb",
    "visor",
    "owl",
    "spark",
    "fox",
    "astro",
    "neko",
    "knight",
    "lotus",
    "pixel",
    "flame",
    "sonar",
)

_ALLOWED_SVG_TAGS = {
    "svg",
    "g",
    "defs",
    "style",
    "title",
    "desc",
    "path",
    "circle",
    "ellipse",
    "rect",
    "polygon",
    "polyline",
    "line",
    "lineargradient",
    "radialgradient",
    "stop",
    "clippath",
    "mask",
    "use",
}

_ALLOWED_ATTRS = {
    "xmlns",
    "viewbox",
    "width",
    "height",
    "class",
    "id",
    "role",
    "aria-label",
    "fill",
    "fill-opacity",
    "fill-rule",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-opacity",
    "stroke-dasharray",
    "opacity",
    "transform",
    "transform-origin",
    "d",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "points",
    "offset",
    "stop-color",
    "stop-opacity",
    "gradientunits",
    "gradienttransform",
    "clip-path",
    "mask",
    "style",
    "data-role",
    "href",
}

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_CSS_FORBIDDEN_RE = re.compile(
    r"(?:url\s*\(|@import|expression\s*\(|javascript:|data:text/html)", re.IGNORECASE
)


class OpenBotError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        code: str = "invalid_request",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details or {}


def validate_bot_fields(
    data: dict[str, Any], *, partial: bool = False
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not partial or "name" in data:
        name = data.get("name")
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
            raise OpenBotError("Nome do bot deve ter entre 1 e 80 caracteres.")
        out["name"] = name.strip()

    if not partial or "description" in data:
        desc = data.get("description", "")
        if not isinstance(desc, str) or len(desc) > 2000:
            raise OpenBotError("Descrição do bot deve ter no máximo 2000 caracteres.")
        out["description"] = desc.strip()

    if not partial or "instructions" in data:
        inst = data.get("instructions", "")
        if not isinstance(inst, str) or len(inst) > 32000:
            raise OpenBotError(
                "Instruções do bot devem ter no máximo 32000 caracteres."
            )
        out["instructions"] = inst

    if not partial or "enabled" in data:
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise OpenBotError("enabled deve ser booleano.")
        out["enabled"] = enabled

    if not partial or "speak_replies" in data:
        speak_replies = data.get("speak_replies", True)
        if not isinstance(speak_replies, bool):
            raise OpenBotError("speak_replies deve ser booleano.")
        out["speak_replies"] = speak_replies

    if not partial or "llm_tier" in data:
        tier = str(data.get("llm_tier") or "free").strip()
        if len(tier) > 64:
            raise OpenBotError("llm_tier inválido.")
        out["llm_tier"] = tier

    if not partial or "avatar_id" in data:
        aid = data.get("avatar_id")
        if aid is not None:
            if not isinstance(aid, str) or not re.fullmatch(r"[a-f0-9]{16,64}", aid):
                raise OpenBotError("avatar_id inválido.")
        out["avatar_id"] = aid

    if "face_type" in data:
        face_type = data.get("face_type")
        if face_type is not None:
            if not isinstance(face_type, str) or face_type.strip() not in FACE_TYPES:
                raise OpenBotError("face_type inválido.")
            out["face_type"] = face_type.strip()
        else:
            out["face_type"] = None

    if not partial or "avatar_colors" in data:
        colors = data.get("avatar_colors")
        if colors is not None:
            if not isinstance(colors, dict):
                raise OpenBotError("avatar_colors inválido.")
            clean_colors = {}
            for key in ("primary", "accent", "eyes"):
                if key in colors and colors[key] is not None:
                    val = str(colors[key]).strip()
                    if not _HEX_COLOR_RE.fullmatch(val):
                        raise OpenBotError(f"Cor inválida em avatar_colors.{key}.")
                    clean_colors[key] = val
            out["avatar_colors"] = clean_colors
        elif not partial:
            out["avatar_colors"] = {
                "primary": "#8B5CF6",
                "accent": "#65D9FF",
                "eyes": "#FAF4FF",
            }

    if not partial or "tool_ids" in data:
        tids = data.get("tool_ids", [])
        if not isinstance(tids, list) or any(
            not isinstance(t, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,64}", t)
            for t in tids
        ):
            raise OpenBotError("tool_ids inválido.")
        out["tool_ids"] = list(dict.fromkeys(tids))

    if not partial or "delegation_targets" in data:
        targets = data.get("delegation_targets", [])
        if not isinstance(targets, list) or any(
            not isinstance(t, str) or not re.fullmatch(r"[a-f0-9-]{8,64}", t)
            for t in targets
        ):
            raise OpenBotError("delegation_targets inválido.")
        out["delegation_targets"] = list(dict.fromkeys(targets))

    return out


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def sanitize_svg(svg_text: str) -> str:
    """Valida e sanitiza um SVG via parser XML estrito (sem script, on*, foreignObject ou URLs externas)."""
    if not isinstance(svg_text, str) or not svg_text.strip():
        raise OpenBotError("Conteúdo SVG vazio.")
    raw_bytes = svg_text.encode("utf-8")
    if len(raw_bytes) > MAX_SVG_BYTES:
        raise OpenBotError("SVG excede o limite de 256 KiB.")

    lower_head = svg_text[:4096].lower()
    if "<!doctype" in lower_head or "<!entity" in lower_head:
        raise OpenBotError("SVG não pode conter DTD ou entidades XML.")

    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise OpenBotError(f"SVG malformado: {exc}") from None

    if _local_tag(root.tag) != "svg":
        raise OpenBotError("O elemento raiz deve ser <svg>.")

    node_count = 0

    def walk(elem: ET.Element, depth: int) -> None:
        nonlocal node_count
        if depth > MAX_SVG_DEPTH:
            raise OpenBotError("SVG excede a profundidade máxima permitida.")
        node_count += 1
        if node_count > MAX_SVG_NODES:
            raise OpenBotError("SVG excede o número máximo de elementos.")

        tag = _local_tag(elem.tag)
        if tag in (
            "script",
            "foreignobject",
            "iframe",
            "object",
            "embed",
            "audio",
            "video",
        ):
            raise OpenBotError(f"Elemento proibido no SVG: <{tag}>.")
        if tag not in _ALLOWED_SVG_TAGS:
            raise OpenBotError(f"Elemento SVG não permitido: <{tag}>.")

        if tag == "style" and elem.text and _CSS_FORBIDDEN_RE.search(elem.text):
            raise OpenBotError(
                "CSS no SVG contém referência externa ou expressão proibida."
            )

        for attr_name, attr_val in list(elem.attrib.items()):
            lname = _local_tag(attr_name)
            if lname.startswith("on"):
                raise OpenBotError(f"Atributo de evento proibido no SVG: {lname}.")
            if lname not in _ALLOWED_ATTRS:
                raise OpenBotError(f"Atributo não permitido no SVG: {lname}.")
            if lname == "href":
                if not attr_val.strip().startswith("#"):
                    raise OpenBotError(
                        "Referências href externas não são permitidas no SVG."
                    )
            if lname == "style" and _CSS_FORBIDDEN_RE.search(attr_val):
                raise OpenBotError("Estilo inline proibido no SVG.")

        for child in list(elem):
            walk(child, depth + 1)

    walk(root, 1)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="unicode")

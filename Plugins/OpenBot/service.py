"""Serviço CRUD, projeção de voz e gerenciamento de avatares para Bots Dinâmicos."""

from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from src.tts_service import TTSServiceError, get_tts_service
from src.user_paths import user_path
from .models import OpenBotError, sanitize_svg, validate_bot_fields
from .repository import OpenBotRepository


class OpenBotService:
    def __init__(self, repo: OpenBotRepository | None = None):
        self.repo = repo or OpenBotRepository()

    def _project_bot(self, doc: dict[str, Any]) -> dict[str, Any]:
        svc = get_tts_service()
        voice = svc.get_speaker_voice(f"dynamic:{doc['id']}")
        avatar_id = doc.get("avatar_id")
        return {
            **doc,
            "kind": "dynamic",
            "avatar_url": f"/api/pia/openbot/avatars/{avatar_id}"
            if avatar_id
            else "/pia.svg",
            "voice": voice,
        }

    def list_bots(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        try:
            lim = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            raise OpenBotError("limit inválido.") from None
        all_bots = self.repo.list_bots()
        start = 0
        if cursor:
            for i, item in enumerate(all_bots):
                if item["id"] == cursor:
                    start = i + 1
                    break
        slice_items = all_bots[start : start + lim]
        next_cursor = (
            slice_items[-1]["id"]
            if (start + lim) < len(all_bots) and slice_items
            else None
        )
        return {
            "items": [self._project_bot(b) for b in slice_items],
            "next_cursor": next_cursor,
        }

    def get_bot(self, bot_id: str) -> dict[str, Any]:
        doc = self.repo.get_bot(bot_id)
        if not doc or doc.get("deleted"):
            raise OpenBotError(
                "Bot dinâmico não encontrado.", status=404, code="not_found"
            )
        return self._project_bot(doc)

    def create_bot(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise OpenBotError("Esperado objeto JSON.")
        fields = validate_bot_fields(data, partial=False)
        bot_id = str(uuid.uuid4())
        record = {"id": bot_id, **fields}
        created = self.repo.create_bot(record)
        if isinstance(data.get("voice"), dict):
            v = data["voice"]
            try:
                get_tts_service().set_speaker_voice(
                    f"dynamic:{bot_id}",
                    mode=str(v.get("mode") or "inherit"),
                    profile=v.get("profile"),
                )
            except TTSServiceError as exc:
                self.repo.delete_bot(bot_id)
                raise OpenBotError(
                    exc.message, status=exc.status, code=exc.code
                ) from exc
        return self._project_bot(created)

    def update_bot(self, bot_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if bot_id in ("secretaria", "native:secretaria"):
            raise OpenBotError(
                "Bots nativos não podem ser editados pela rota dinâmica.",
                status=404,
                code="not_found",
            )
        if not isinstance(data, dict):
            raise OpenBotError("Esperado objeto JSON.")
        expected_rev = data.get("revision")
        if expected_rev is not None:
            try:
                expected_rev = int(expected_rev)
            except (TypeError, ValueError):
                raise OpenBotError("revision inválido.") from None
        fields = validate_bot_fields(data, partial=True)
        updated = self.repo.update_bot(bot_id, fields, expected_revision=expected_rev)
        if isinstance(data.get("voice"), dict):
            v = data["voice"]
            try:
                get_tts_service().set_speaker_voice(
                    f"dynamic:{bot_id}",
                    mode=str(v.get("mode") or "inherit"),
                    profile=v.get("profile"),
                    revision=v.get("revision"),
                )
            except TTSServiceError as exc:
                raise OpenBotError(
                    exc.message, status=exc.status, code=exc.code
                ) from exc
        return self._project_bot(updated)

    def delete_bot(
        self,
        bot_id: str,
        *,
        expected_revision: int | None = None,
        has_active_run: bool = False,
    ) -> None:
        if bot_id in ("secretaria", "native:secretaria"):
            raise OpenBotError(
                "Não é permitido excluir bots nativos.",
                status=403,
                code="forbidden",
            )
        if has_active_run:
            raise OpenBotError(
                "Não é possível excluir um bot com execução ativa.",
                status=409,
                code="bot_running",
            )
        self.repo.delete_bot(bot_id, expected_revision=expected_revision)

    def upload_avatar(self, svg_text: str) -> dict[str, str]:
        clean_svg = sanitize_svg(svg_text)
        avatar_id = uuid.uuid4().hex
        avatars_dir = user_path("openbot", "avatars")
        avatars_dir.mkdir(parents=True, exist_ok=True)
        dest = (avatars_dir / f"{avatar_id}.svg").resolve()
        if not dest.is_relative_to(avatars_dir.resolve()):
            raise OpenBotError("Caminho de avatar inválido.")
        dest.write_text(clean_svg, encoding="utf-8")
        return {
            "avatar_id": avatar_id,
            "url": f"/api/pia/openbot/avatars/{avatar_id}",
        }

    def get_avatar_bytes(self, avatar_id: str) -> bytes:
        if not re.fullmatch(r"[a-f0-9]{16,64}", avatar_id or ""):
            raise OpenBotError("Avatar não encontrado.", status=404, code="not_found")
        avatars_dir = user_path("openbot", "avatars").resolve()
        file = (avatars_dir / f"{avatar_id}.svg").resolve()
        if not file.is_relative_to(avatars_dir) or not file.is_file():
            raise OpenBotError("Avatar não encontrado.", status=404, code="not_found")
        return file.read_bytes()

    def workspace_bot_records(self) -> list[dict[str, Any]]:
        records = []
        for b in self.repo.list_bots():
            proj = self._project_bot(b)
            records.append(
                {
                    "id": proj["id"],
                    "kind": "dynamic",
                    "name": proj["name"],
                    "avatar": proj["avatar_url"],
                    "avatar_colors": proj.get("avatar_colors"),
                    "description": proj.get("description", ""),
                    "enabled": proj.get("enabled", True),
                    "voice": proj["voice"],
                }
            )
        return records


_openbot_service: OpenBotService | None = None
_openbot_lock = threading.Lock()


def get_openbot_service() -> OpenBotService:
    global _openbot_service
    with _openbot_lock:
        if _openbot_service is None:
            _openbot_service = OpenBotService()
        return _openbot_service

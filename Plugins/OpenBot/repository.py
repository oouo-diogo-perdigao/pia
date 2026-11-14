"""Repositório transacional para Bots Dinâmicos e Execuções via settings_store."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from src import settings_store
from .models import OpenBotError

_INDEX_KEY = "openbot/index"
_BOT_PREFIX = "openbot/bot/"
_RUN_PREFIX = "openbot/run/"


class OpenBotRepository:
    def __init__(self):
        self._lock = threading.RLock()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_bot_ids(self) -> list[str]:
        idx = settings_store.document(_INDEX_KEY, [])
        return list(idx) if isinstance(idx, list) else []

    def get_bot(self, bot_id: str) -> dict[str, Any] | None:
        doc = settings_store.document(_BOT_PREFIX + bot_id)
        return dict(doc) if isinstance(doc, dict) else None

    def list_bots(self) -> list[dict[str, Any]]:
        result = []
        for bid in self.list_bot_ids():
            doc = self.get_bot(bid)
            if doc and not doc.get("deleted"):
                result.append(doc)
        return result

    def create_bot(self, record: dict[str, Any]) -> dict[str, Any]:
        bot_id = record["id"]
        now = self._now()
        full = {
            **record,
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            store = settings_store.get_store()
            with store.connection() as db:
                row = db.execute(
                    "SELECT value FROM documents WHERE name=?", (_INDEX_KEY,)
                ).fetchone()
                ids = json.loads(row[0]) if row else []
                if bot_id not in ids:
                    ids.append(bot_id)
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?)",
                    (_INDEX_KEY, json.dumps(ids)),
                )
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?)",
                    (_BOT_PREFIX + bot_id, json.dumps(full)),
                )
        return full

    def update_bot(
        self,
        bot_id: str,
        patch: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            store = settings_store.get_store()
            with store.connection() as db:
                row = db.execute(
                    "SELECT value FROM documents WHERE name=?", (_BOT_PREFIX + bot_id,)
                ).fetchone()
                if not row:
                    raise OpenBotError(
                        "Bot dinâmico não encontrado.", status=404, code="not_found"
                    )
                current = json.loads(row[0])
                if current.get("deleted"):
                    raise OpenBotError(
                        "Bot dinâmico não encontrado.", status=404, code="not_found"
                    )
                cur_rev = int(current.get("revision", 1))
                if expected_revision is not None and int(expected_revision) != cur_rev:
                    raise OpenBotError(
                        "Conflito de revisão ao atualizar bot.",
                        status=409,
                        code="revision_conflict",
                        details={"current_revision": cur_rev},
                    )
                updated = {
                    **current,
                    **patch,
                    "id": bot_id,
                    "revision": cur_rev + 1,
                    "created_at": current.get("created_at"),
                    "updated_at": self._now(),
                }
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?)",
                    (_BOT_PREFIX + bot_id, json.dumps(updated)),
                )
        return updated

    def delete_bot(self, bot_id: str, *, expected_revision: int | None = None) -> None:
        with self._lock:
            store = settings_store.get_store()
            with store.connection() as db:
                row = db.execute(
                    "SELECT value FROM documents WHERE name=?", (_BOT_PREFIX + bot_id,)
                ).fetchone()
                if not row:
                    raise OpenBotError(
                        "Bot dinâmico não encontrado.", status=404, code="not_found"
                    )
                current = json.loads(row[0])
                cur_rev = int(current.get("revision", 1))
                if expected_revision is not None and int(expected_revision) != cur_rev:
                    raise OpenBotError(
                        "Conflito de revisão ao excluir bot.",
                        status=409,
                        code="revision_conflict",
                        details={"current_revision": cur_rev},
                    )
                idx_row = db.execute(
                    "SELECT value FROM documents WHERE name=?", (_INDEX_KEY,)
                ).fetchone()
                ids = [
                    x
                    for x in (json.loads(idx_row[0]) if idx_row else [])
                    if x != bot_id
                ]
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?)",
                    (_INDEX_KEY, json.dumps(ids)),
                )
                db.execute(
                    "DELETE FROM documents WHERE name=?", (_BOT_PREFIX + bot_id,)
                )
                db.execute(
                    "DELETE FROM documents WHERE name=?",
                    (f"tts/speakers/dynamic:{bot_id}",),
                )

    def save_run(self, run: dict[str, Any]) -> None:
        settings_store.save_document(_RUN_PREFIX + run["run_id"], run)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        doc = settings_store.document(_RUN_PREFIX + run_id)
        return dict(doc) if isinstance(doc, dict) else None

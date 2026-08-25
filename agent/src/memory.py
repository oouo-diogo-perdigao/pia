from __future__ import annotations

import json
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return " ".join(value.split())


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return

        self._write(
            {
                "version": 1,
                "profile": {},
                "facts": [],
                "learned_actions": [],
                "pending_learning": None,
            }
        )

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def get_pending_learning(self) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("pending_learning")

    def set_pending_learning(self, pending: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            pending = dict(pending)
            pending["created_at"] = datetime.now(timezone.utc).isoformat()
            data["pending_learning"] = pending
            self._write(data)

    def clear_pending_learning(self) -> None:
        with self._lock:
            data = self._read()
            data["pending_learning"] = None
            self._write(data)

    def add_learned_action(
        self,
        trigger: str,
        description: str,
        action_type: str,
        value: str,
        aliases: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            item = {
                "id": f"learned_{uuid.uuid4().hex[:10]}",
                "description": description,
                "triggers": [trigger] + (aliases or []),
                "action": {
                    "type": action_type,
                    "value": value,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data.setdefault("learned_actions", []).append(item)
            data["pending_learning"] = None
            self._write(data)
            return item

    def get_learned_action(self, action_id: str) -> dict[str, Any] | None:
        data = self.snapshot()
        for item in data.get("learned_actions", []):
            if item.get("id") == action_id:
                return item
        return None

    def match_learned_action(
        self,
        utterance: str,
        threshold: float = 0.94,
    ) -> dict[str, Any] | None:
        needle = normalize_text(utterance)
        if not needle:
            return None

        best_item = None
        best_score = 0.0

        data = self.snapshot()
        for item in data.get("learned_actions", []):
            for trigger in item.get("triggers", []):
                candidate = normalize_text(trigger)
                if not candidate:
                    continue

                if candidate == needle:
                    return item

                score = SequenceMatcher(None, needle, candidate).ratio()
                if score > best_score:
                    best_score = score
                    best_item = item

        if best_item is not None and best_score >= threshold:
            return best_item

        return None

    def remember_fact(self, key: str, value: str) -> None:
        with self._lock:
            data = self._read()
            facts = data.setdefault("facts", [])
            normalized_key = normalize_text(key)

            for fact in facts:
                if normalize_text(str(fact.get("key", ""))) == normalized_key:
                    fact["value"] = value
                    fact["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write(data)
                    return

            facts.append(
                {
                    "key": key,
                    "value": value,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._write(data)

    def context_for_model(self) -> dict[str, Any]:
        data = self.snapshot()
        return {
            "profile": data.get("profile", {}),
            "facts": data.get("facts", []),
            "learned_actions": [
                {
                    "id": item.get("id"),
                    "description": item.get("description"),
                    "triggers": item.get("triggers", []),
                    "action_type": item.get("action", {}).get("type"),
                    # O valor é incluído porque o agente pode precisar saber
                    # o que a memória já conhece, mas a execução final ainda
                    # ocorre somente pelo executor local.
                    "value": item.get("action", {}).get("value"),
                }
                for item in data.get("learned_actions", [])
            ],
        }

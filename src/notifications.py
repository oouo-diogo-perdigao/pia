"""Persistent local app/bot notifications shared by every entry point."""

from datetime import datetime, timezone
import inspect
import threading
import uuid
import re
import logging
from urllib.parse import urlsplit


class NotificationCenter:
    def __init__(self, store, notify, speak):
        self.store, self.notify, self.speak = store, notify, speak
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            items = self.store.get("notifications:items", [])
            settings = self.store.get(
                "notifications:settings", {"read_aloud": False, "muted": []}
            )
            counts = {}
            for item in items:
                if not item["read"]:
                    counts[item["source"]] = counts.get(item["source"], 0) + 1
            return {
                "items": items,
                "settings": settings,
                "counts": counts,
                "unread": sum(counts.values()),
            }

    def publish(self, source, title, text, links=None, *, external_id=None):
        if not isinstance(source, str) or not re.fullmatch(
            r"(Apps|Bot)/[a-zA-Z0-9_-]+", source
        ):
            raise ValueError("Origem de notificação inválida.")
        if links is not None and (
            not isinstance(links, list)
            or len(links) > 20
            or any(
                not isinstance(link, dict) or not isinstance(link.get("url"), str)
                for link in links
            )
        ):
            raise ValueError("Links de notificação inválidos.")
        clean = []
        for link in links or []:
            url = link.get("url", "")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                continue
            clean.append({"label": str(link.get("label", "Abrir"))[:100], "url": url})
        with self.lock:
            state = self.snapshot()
            muted = source in state["settings"]["muted"]
            if external_id:
                for existing in state["items"]:
                    if existing["id"] == external_id and existing["source"] == source:
                        return existing
            item = {
                "id": external_id or uuid.uuid4().hex,
                "source": source,
                "title": str(title)[:300],
                "text": str(text)[:10000],
                "links": clean,
                "read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.store.set("notifications:items", [item, *state["items"]][:1000])
        if not muted:
            try:
                self.notify(item["title"], item["text"], False)
            except Exception:
                logging.exception("Notificação persistida, mas o aviso nativo falhou.")
            if state["settings"]["read_aloud"]:
                spoken_text = item["title"] + ". " + item["text"]
                kwargs = {}
                try:
                    sig = inspect.signature(self.speak)
                    if "speaker_id" in sig.parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    ):
                        kwargs["speaker_id"] = source
                except (TypeError, ValueError):
                    pass
                threading.Thread(
                    target=self.speak,
                    args=(spoken_text,),
                    kwargs=kwargs,
                    daemon=True,
                ).start()
        return item

    def configure(self, data):
        if (
            not isinstance(data.get("read_aloud"), bool)
            or not isinstance(data.get("muted"), list)
            or any(
                not isinstance(s, str) or not s.startswith(("Apps/", "Bot/"))
                for s in data["muted"]
            )
        ):
            raise ValueError("Preferências de notificações inválidas.")
        with self.lock:
            self.store.set(
                "notifications:settings",
                {"read_aloud": data["read_aloud"], "muted": list(set(data["muted"]))},
            )

    def read(self, identity=None, source=None):
        with self.lock:
            items = self.snapshot()["items"]
            for item in items:
                if (identity is None or identity == item["id"]) and (
                    source is None or source == item["source"]
                ):
                    item["read"] = True
            self.store.set("notifications:items", items)

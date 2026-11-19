"""Incremental parser shared by the desktop log inspector and offline tests."""

import json


class STTProgress:
    def __init__(self):
        self.buffer = ""
        self.state = "idle"
        self.percent = 0.0
        self.label = "Transcrição local: aguardando"

    def feed(self, text):
        lines = (self.buffer + text).split("\n")
        self.buffer = lines.pop()
        for line in lines:
            if "[STT_PROGRESS] " not in line:
                continue
            try:
                event = json.loads(line.split("[STT_PROGRESS] ", 1)[1])
                state = event["state"]
                if state == "recovering":
                    self.percent = min(99.9, max(0.0, float(event["percent"])))
                    self.label = (
                        f"Local: recuperando repetição em {event['processed']:.1f}s…"
                    )
                elif state == "transcribing":
                    self.percent = min(99.9, max(0.0, float(event["percent"])))
                    self.label = f"Local: {self.percent:.1f}% — {event['processed']:.0f}s / {event['duration']:.0f}s"
                elif state == "completed":
                    self.percent, self.label = (
                        100,
                        "Local: transcrição concluída — 100%",
                    )
                elif state == "preparing":
                    self.percent, self.label = 0, "Local: preparando áudio / modelo…"
                elif state == "error":
                    self.label = "Local: falha na transcrição; consulte o log"
                else:
                    continue
                self.state = state
            except (ValueError, KeyError, TypeError):
                continue

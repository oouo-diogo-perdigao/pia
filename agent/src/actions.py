from __future__ import annotations

import logging
import os
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import pyautogui

from .config import Settings, DEFAULT_LOCATION
from .memory import MemoryStore
from .weather import get_weather


class ActionExecutor:
    def __init__(self, settings: Settings, memory: MemoryStore) -> None:
        self.settings = settings
        self.memory = memory
        pyautogui.PAUSE = 0.05

    @staticmethod
    def validate_url(value: str) -> bool:
        try:
            parsed = urlparse(value.strip())
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def execute(self, step) -> dict:
        kind = step.kind

        if kind == "delete_all":
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)
            pyautogui.press("backspace")
            return {"action": kind, "ok": True}

        if kind == "press_enter":
            pyautogui.press("enter")
            return {"action": kind, "ok": True}

        if kind == "open_url":
            if not step.target or not self.validate_url(step.target):
                raise ValueError("open_url recebeu uma URL inválida.")
            webbrowser.open(step.target)
            return {"action": kind, "ok": True, "target": step.target}

        if kind == "open_target":
            if not step.target:
                raise ValueError("open_target exige target.")
            return self._open_target(step.target)

        if kind == "weather":
            location = step.location or DEFAULT_LOCATION
            when = step.when or "hoje"
            result = get_weather(location, when)
            return {"action": kind, "ok": True, "result": result}

        if kind == "learned_action":
            if not step.action_id:
                raise ValueError("learned_action exige action_id.")
            item = self.memory.get_learned_action(step.action_id)
            if item is None:
                raise KeyError(f"Ação aprendida inexistente: {step.action_id}")
            return self.execute_learned(item)

        if kind == "remember_fact":
            if not step.fact_key or step.fact_value is None:
                raise ValueError("remember_fact exige fact_key e fact_value.")
            self.memory.remember_fact(step.fact_key, step.fact_value)
            return {
                "action": kind,
                "ok": True,
                "key": step.fact_key,
                "value": step.fact_value,
            }

        raise ValueError(f"Ação não permitida: {kind}")

    def execute_learned(self, item: dict) -> dict:
        action = item.get("action", {})
        action_type = action.get("type")
        value = str(action.get("value", ""))

        if action_type == "open_url":
            if not self.validate_url(value):
                raise ValueError("A memória contém uma URL inválida.")
            webbrowser.open(value)
            return {
                "action": "learned_action",
                "ok": True,
                "id": item.get("id"),
                "target": value,
            }

        if action_type == "open_path":
            path = Path(value).expanduser()
            if not path.exists():
                raise FileNotFoundError(value)
            os.startfile(str(path))
            return {
                "action": "learned_action",
                "ok": True,
                "id": item.get("id"),
                "target": str(path),
            }

        raise ValueError(f"Tipo de ação aprendida ainda não suportado: {action_type}")

    def _open_target(self, target: str) -> dict:
        target = target.strip()

        if self.validate_url(target):
            webbrowser.open(target)
            return {"action": "open_target", "ok": True, "target": target}

        path = Path(os.path.expandvars(os.path.expanduser(target)))
        if path.exists():
            os.startfile(str(path))
            return {
                "action": "open_target",
                "ok": True,
                "target": str(path),
            }

        # Para nomes de aplicativos, usamos a pesquisa do menu Iniciar.
        # Isso evita montar ou executar comandos shell gerados pela LLM.
        pyautogui.press("win")
        time.sleep(0.15)
        pyautogui.write(target, interval=0.02)
        time.sleep(0.25)
        pyautogui.press("enter")

        logging.info("Solicitada abertura via menu Iniciar: %s", target)
        return {"action": "open_target", "ok": True, "target": target}

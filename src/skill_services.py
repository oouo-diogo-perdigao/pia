"""Adaptadores desktop da API injetada nas skills (importados somente ao usar)."""
from concurrent.futures import Future
from pathlib import Path
import os
import webbrowser
from urllib.parse import urlsplit


class PiaServices:
    def close(self):
        from . import state
        with state.LOCK:
            state.SESSION_ACTIVE = False
        from .PiaOverlay import get_overlay
        overlay = get_overlay()
        if overlay:
            overlay.skill_action_requested.emit('close', True)

    def speak(self, text, cancelled, *, voice=None, speed=None):
        from .HTTPServer import TTS_MANAGER
        from .config import TTS_DEFAULT_SPEED
        if not isinstance(text, str) or not text.strip():
            raise ValueError('piaTTS exige texto não vazio')
        future = Future()
        TTS_MANAGER.add_tts_job(
            text=text.strip(), voice=TTS_MANAGER.resolve_voice(voice, None),
            speed=TTS_DEFAULT_SPEED if speed is None else float(speed),
            job_name='Skill PIA', completion=future, cancelled=cancelled,
        )
        return future

    def interface(self, action, enabled=True):
        allowed = {'blink', 'look', 'look_left', 'look_right', 'center', 'thinking', 'processing', 'pulse'}
        if action not in allowed:
            raise ValueError('Ação desconhecida de piaInterface: ' + str(action))
        from .PiaOverlay import get_overlay
        overlay = get_overlay()
        if overlay:
            overlay.skill_action_requested.emit(action, bool(enabled))

    def view(self, image):
        target = str(image)
        if urlsplit(target).scheme in ('https', 'http'):
            return webbrowser.open(target)
        path = Path(image).expanduser().resolve()
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        os.startfile(str(path))
        return str(path)

    def insert(self, text):
        from .HTTPServer import LOCAL_ACTIONS
        LOCAL_ACTIONS.insert_text_at_cursor(str(text))

    def key(self, *keys):
        import pyautogui
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)

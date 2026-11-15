"""Screenshot tool owned by the screenshots plugin."""

from __future__ import annotations

import uuid
from typing import Any

from src.user_paths import user_path


def take_screenshot(*, user_path_fn: Any = None) -> dict[str, Any]:
    root = (user_path_fn or user_path)("chat")
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ".png"
    dest = root / name

    captured = False
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(all_screens=True)
        img.save(dest, format="PNG")
        captured = True
    except Exception:
        pass

    if not captured:
        try:
            from PyQt6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                pixmap = screen.grabWindow(0)
                if not pixmap.isNull() and pixmap.save(str(dest), "PNG"):
                    captured = True
        except Exception:
            pass

    if not captured or not dest.is_file():
        raise RuntimeError("Não foi possível capturar a tela neste ambiente.")

    url = f"/api/pia/chat/assets/{name}"
    return {
        "image_url": url,
        "path": str(dest),
        "markdown": f"![Captura de tela]({url})",
    }


def register_tools(ctx: Any) -> None:
    ctx.tools.register("pia_screenshot", take_screenshot)

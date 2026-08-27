"""PyQt overlay to show a small animated SVG while session is active (src)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QWidget
import sys
from pathlib import Path
import logging

from .state import LOCK


class FloatingSvgOverlay(QWidget):
    def __init__(self, svg_content: str):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(100, 100)

        screen = QApplication.primaryScreen().geometry()
        x = 30
        y = (screen.height() - 100) // 2
        self.move(x, y)

        self.view = QWebEngineView(self)
        self.view.resize(100, 100)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.view.setHtml(svg_content)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_speaking(self, speaking: bool):
        if speaking:
            self.view.page().runJavaScript("document.body.classList.add('speaking');")
        else:
            self.view.page().runJavaScript(
                "document.body.classList.remove('speaking');"
            )


def run_overlay_app():
    svg_file_path = Path(__file__).resolve().parent.parent.parent / "pia.svg"
    if svg_file_path.exists():
        svg_raw = svg_file_path.read_text(encoding="utf-8")
        svg_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    html, body {{
        background: transparent !important; 
        background-color: transparent !important;
        margin: 0; 
        padding: 0;
        overflow: hidden; 
        width: 100px;
        height: 100px;
        display: flex; 
        align-items: center; 
        justify-content: center; 
    }}
    svg {{
        width: 100px !important;
        height: 100px !important;
        transform-origin: center center;
    }}
    @keyframes rotateClockwise {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
    @keyframes rotateAntiClockwise {{ from {{ transform: rotate(360deg); }} to {{ transform: rotate(0deg); }} }}
    .rotating-group-clockwise {{ transform-origin: 253px 256px; animation: rotateClockwise 300s linear infinite; }}
    .rotating-group-anti-clockwise {{ transform-origin: 253px 256px; animation: rotateAntiClockwise 60s linear infinite; }}
    @keyframes blink {{
      0%, 90%, 100% {{ transform: scaleY(1); }}
      95% {{ transform: scaleY(0.1); }}
    }}
    .blinking-eyes {{ transform-origin: 241px 245.5px; animation: blink 600s infinite; }}
    @keyframes lookAround {{
      0%, 98%, 100% {{ transform: translateX(0px); }}
      98.5% {{ transform: translateX(-20px); }}
      99% {{ transform: translateX(20px); }}
      99.5% {{ transform: translateX(0px); }}
    }}
    .looking-eyes {{ transform-origin: 241px 245.5px; animation: lookAround 300s infinite ease-in-out; }}
    @keyframes soundPulse {{
      0%, 100% {{
        transform: scale(1);
      }}
      50% {{
        transform: scale(1.12);
      }}
    }}
    body.speaking svg {{
      animation: soundPulse 0.4s ease-in-out infinite;
      transform-origin: center center;
    }}
</style>
</head>
<body>
{svg_raw}
</body>
</html>
"""
    else:
        svg_content = (
            "<html><body><h3>Arquivo pia.svg não encontrado</h3></body></html>"
        )

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    overlay = FloatingSvgOverlay(svg_content)

    def check_session():
        from . import state as _state

        with _state.LOCK:
            active = _state.SESSION_ACTIVE
        if active:
            if not overlay.isVisible():
                overlay.show()
        else:
            if overlay.isVisible():
                overlay.hide()

    from PyQt6.QtCore import QTimer

    timer = QTimer()
    timer.timeout.connect(check_session)
    timer.start(100)

    app.exec()

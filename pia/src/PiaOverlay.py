"""PyQt overlay to show a small animated SVG while session is active (src)."""

from PyQt6.QtCore import Qt, QTimer, QMetaObject, Q_ARG
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QWidget
import sys
from pathlib import Path

WINDOW_SIZE = 100  # Tamanho do overlay em pixels


class PiaOverlay(QWidget):
    def __init__(self, svg_content: str):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WINDOW_SIZE, WINDOW_SIZE)

        screen = QApplication.primaryScreen().geometry()
        self.move(0, 0)

        self.view = QWebEngineView(self)
        self.view.resize(WINDOW_SIZE, WINDOW_SIZE)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.view.setHtml(svg_content)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._is_speaking = False
        self._is_thinking = False
        self._has_pending_tasks = False

    def set_speaking(self, speaking: bool):
        self._is_speaking = speaking
        # Executa a alteração no JavaScript de forma segura na thread da UI do PyQt
        QMetaObject.invokeMethod(
            self,
            "_update_speaking_js",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, speaking),
        )

    def _update_speaking_js(self, speaking: bool):
        val = "true" if speaking else "false"
        self.view.page().runJavaScript(
            f"document.body.classList.toggle('speaking', {val});"
        )

    def set_thinking(self, thinking: bool):
        self._is_thinking = thinking
        QMetaObject.invokeMethod(
            self,
            "_update_thinking_js",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, thinking),
        )

    def _update_thinking_js(self, thinking: bool):
        val = "true" if thinking else "false"
        self.view.page().runJavaScript(
            f"document.body.classList.toggle('fast-orbit', {val});"
        )

    def set_pending_tasks(self, pending: bool):
        self._has_pending_tasks = pending

    def should_stay_visible(self) -> bool:
        from . import state as _state

        with _state.LOCK:
            session_active = _state.SESSION_ACTIVE
        return (
            session_active
            or self._is_speaking
            or self._is_thinking
            or self._has_pending_tasks
        )


# Máquina de estados baseada em contadores para gerenciar múltiplos processos da Pia
class PiaStateMachine:
    def __init__(self):
        self.counters = {
            "thinking": 0,  # Pensando (somente LLM) -> órbita interna mais rápida
            "processing": 0,  # Processando geral -> órbita externa mais rápida
            "speaking": 0,  # Falando -> boca se mexe
            "listening": 0,  # Escutando -> olhos se mexe
            "pulse": 0,  # Agente em execução (reservado)
        }
        self.lock = threading.Lock()

    def adjust_counter(self, state_name: str, delta: int):
        with self.lock:
            if state_name in self.counters:
                self.counters[state_name] = max(0, self.counters[state_name] + delta)
            self._apply_states()

    def trigger_blink(self):
        # Piscar os olhos (detectado silêncio / fim do áudio para enviar ao STT)
        overlay = get_overlay()
        if overlay:
            overlay.blink()

    def _apply_states(self):
        overlay = get_overlay()
        if not overlay:
            return
        overlay.set_inner_orbit_fast(self.counters["thinking"] > 0)
        overlay.set_outer_orbit_fast(self.counters["processing"] > 0)
        overlay.set_mouth_moving(self.counters["speaking"] > 0)
        overlay.set_eyes_moving(self.counters["listening"] > 0)


# Instâncias globais da classe e da máquina de estados para controle externo
_GLOBAL_OVERLAY: PiaOverlay | None = None
_GLOBAL_STATE_MACHINE: PiaStateMachine | None = None


def get_overlay() -> PiaOverlay | None:
    return _GLOBAL_OVERLAY


def get_state_machine() -> PiaStateMachine:
    global _GLOBAL_STATE_MACHINE
    if _GLOBAL_STATE_MACHINE is None:
        _GLOBAL_STATE_MACHINE = PiaStateMachine()
    return _GLOBAL_STATE_MACHINE


def run_overlay_app():
    global _GLOBAL_OVERLAY
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
        width: {WINDOW_SIZE}px;
        height: {WINDOW_SIZE}px;
        display: flex; 
        align-items: center; 
        justify-content: center; 
    }}
    svg {{
        width: {WINDOW_SIZE}px !important;
        height: {WINDOW_SIZE}px !important;
        transform-origin: center center;
    }}
</style>
</head>
<body>{svg_raw}</body>
</html>
"""
    else:
        svg_content = (
            "<html><body><h3>Arquivo pia.svg não encontrado</h3></body></html>"
        )

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    overlay = PiaOverlay(svg_content)
    _GLOBAL_OVERLAY = overlay

    def check_visibility():
        if overlay.should_stay_visible():
            if not overlay.isVisible():
                overlay.show()
        else:
            if overlay.isVisible():
                overlay.hide()

    timer = QTimer()
    timer.timeout.connect(check_visibility)
    timer.start(100)

    app.exec()

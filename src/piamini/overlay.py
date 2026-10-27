import os
import sys
import threading
from pathlib import Path
from src.config import PUBLIC_BASE_URL

"""PyQt overlay to show a small animated SVG while session is active (src)."""
from PyQt6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QThread,
    QMetaObject,
    Q_ARG,
    qInstallMessageHandler,
    QtMsgType,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWidgets import QApplication, QWidget


def quiet_qt_messages(mode, context, message):
    # Ignora a mensagem de erro de DPI do Windows
    if "SetProcessDpiAwarenessContext" in message:
        return
    # Mantém o comportamento padrão para os demais logs
    if mode == QtMsgType.QtDebugMsg:
        print(f"Debug: {message}")
    elif mode == QtMsgType.QtInfoMsg:
        print(f"Info: {message}")
    elif mode == QtMsgType.QtWarningMsg:
        print(f"Warning: {message}")
    elif mode == QtMsgType.QtCriticalMsg:
        print(f"Critical: {message}")
    elif mode == QtMsgType.QtFatalMsg:
        print(f"Fatal: {message}")


# WINDOW_SIZE = 100  # Tamanho do overlay em pixels
WINDOW_SIZE = 150  # Tamanho do overlay em pixels


class PiaOverlay(QWidget):
    skill_action_requested = pyqtSignal(str, bool)

    @pyqtSlot(str, bool)
    def apply_skill_action(self, action, enabled):
        if action == 'close':
            self._is_thinking = False
            self._is_speaking = False
        elif action == 'blink':
            self.blink()
        elif action == 'thinking':
            self.set_inner_orbit_fast(enabled)
        elif action == 'processing':
            self.set_outer_orbit_fast(enabled)
        elif action == 'look':
            self.set_eyes_moving(enabled)
        elif action in ('look_left', 'look_right', 'center'):
            offset = (-8 if action == 'look_left' else 8) if enabled and action != 'center' else 0
            self.view.page().runJavaScript(
                "document.querySelectorAll('.animation-looking-eyes').forEach(e => {e.style.animationPlayState='paused'; e.style.transform='translateX(" + str(offset) + "px)';});")
        elif action == 'pulse':
            val = 'running' if enabled else 'paused'
            self.view.page().runJavaScript("document.querySelectorAll('.animation-pulse').forEach(e => e.style.animationPlayState='" + val + "');")

    def __init__(self, svg_content: str):
        super().__init__()
        self.skill_action_requested.connect(self.apply_skill_action)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        # No Windows o cursor global funciona com a janela transparente a cliques.
        # No Wayland esse cursor não acompanha o mouse, então a janela precisa
        # receber enter/leave para o menu de auxílio aparecer.
        if sys.platform == 'win32':
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WINDOW_SIZE, WINDOW_SIZE)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.right() - WINDOW_SIZE - 26, screen.bottom() - WINDOW_SIZE - 70)
        self.user_hidden = False

        self.view = QWebEngineView(self)
        self.view.resize(WINDOW_SIZE, WINDOW_SIZE)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.view.setHtml(svg_content, QUrl.fromLocalFile(str(Path(__file__).parent) + '/'))
        self.view.loadFinished.connect(lambda _: self.view.page().runJavaScript("window.startStreaming&&startStreaming();"))
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # Faz o QWebEngineView ignorar os cliques do mouse para que o overlay principal receba
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.view.installEventFilter(self)

        self._is_speaking = False
        self._is_thinking = False
        self._has_pending_tasks = False
        self._streaming_started = False

    def showEvent(self, event):
        super().showEvent(event)
        # Dispara o stream JS assim que a janela é exibida pela primeira vez
        if not self._streaming_started:
            self._streaming_started = True
            self.view.page().runJavaScript("window.startStreaming&&startStreaming();")

    def set_speaking(self, speaking: bool):
        self._is_speaking = speaking
        # Executa a alteração no JavaScript de forma segura na thread da UI do PyQt
        QMetaObject.invokeMethod(
            self,
            "_update_speaking_js",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, speaking),
        )

    @pyqtSlot(bool)
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

    @pyqtSlot(bool)
    def _update_thinking_js(self, thinking: bool):
        val = "true" if thinking else "false"
        self.view.page().runJavaScript(
            f"document.body.classList.toggle('fast-orbit', {val});"
        )

    def set_pending_tasks(self, pending: bool):
        self._has_pending_tasks = pending

    def should_stay_visible(self) -> bool:
        return not self.user_hidden and not getattr(self, 'capture_hidden', False)

    def set_inner_orbit_fast(self, fast: bool):
        if QThread.currentThread() != self.thread():
            self.skill_action_requested.emit('thinking', fast)
            return
        # print log to indicate the inner orbit movement state change
        print(f"[PIA] Inner orbit fast: {fast}")
        val = "running" if fast else "paused"
        self.view.page().runJavaScript(
            f"document.querySelector('.animation-orbit-clockwise').style.animationPlayState = '{val}';"
        )

    def set_outer_orbit_fast(self, fast: bool):
        if QThread.currentThread() != self.thread():
            self.skill_action_requested.emit('processing', fast)
            return
        # print log to indicate the outer orbit movement state change
        print(f"[PIA] Outer orbit fast: {fast}")
        val = "running" if fast else "paused"
        self.view.page().runJavaScript(
            f"document.querySelector('.animation-orbit-anti-clockwise').style.animationPlayState = '{val}';"
        )

    def set_eyes_moving(self, moving: bool):
        if QThread.currentThread() != self.thread():
            self.skill_action_requested.emit('look', moving)
            return
        # print log to indicate the eyes movement state change
        print(f"[PIA] Eyes moving: {moving}")
        val = "running" if moving else "paused"
        self.view.page().runJavaScript(
            f"document.querySelector('.animation-looking-eyes').style.animationPlayState = '{val}';"
        )

    def blink(self):
        if QThread.currentThread() != self.thread():
            self.skill_action_requested.emit('blink', True)
            return
        # print log to indicate the blink action
        print("[PIA] Triggering blink animation")
        self.view.page().runJavaScript("""
            var eyes = document.querySelector('.animation-blinking-eyes');
            if (eyes) {
                eyes.style.animation = 'none';
                void eyes.offsetHeight;
                eyes.style.animation = 'blink 0.25s linear 1';
            }
            """)


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
        # Piscar os olhos (detectado silêncio / fim do áudio para enviar ao SAT)
        overlay = get_overlay()
        if overlay:
            overlay.blink()

    def _apply_states(self):
        overlay = get_overlay()
        if not overlay:
            return
        overlay.set_inner_orbit_fast(self.counters["thinking"] > 0)
        overlay.set_outer_orbit_fast(self.counters["processing"] > 0)
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
    qInstallMessageHandler(quiet_qt_messages)
    from src.config_paths import IMAGES_DIR
    template = Path(__file__).with_name('index.html').read_text(encoding='utf-8')
    svg = (IMAGES_DIR / 'pia.svg').read_text(encoding='utf-8')
    html = template.replace('__SVG__', svg).replace('__BASE__', PUBLIC_BASE_URL)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    overlay = PiaOverlay(html)
    _GLOBAL_OVERLAY = overlay
    from src.desktop_ui import DesktopUI
    overlay.desktop = DesktopUI(overlay)
    overlay.show()
    timer = QTimer(overlay)
    def update():
        from src import state
        with state.LOCK:
            listening = state.SESSION_ACTIVE
        from src.HTTPServer import STT_MANAGER
        listening = listening or STT_MANAGER.status.name == 'RECORDING'
        if getattr(overlay, '_last_listening', None) != listening:
            overlay._last_listening = listening
            overlay.skill_action_requested.emit('pulse', listening)
        if overlay.should_stay_visible() and not overlay.isVisible():
            overlay.show()
    timer.timeout.connect(update)
    timer.start(150)
    import signal
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sys.exit(app.exec())

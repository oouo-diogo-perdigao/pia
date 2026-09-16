import os
import sys
import threading
from pathlib import Path
from .config import TTS_SERVER_URL

"""PyQt overlay to show a small animated SVG while session is active (src)."""
from PyQt6.QtCore import Qt, QTimer, QMetaObject, Q_ARG, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QWidget

# WINDOW_SIZE = 100  # Tamanho do overlay em pixels
WINDOW_SIZE = 500  # Tamanho do overlay em pixels


class PiaOverlay(QWidget):
    def __init__(self, svg_content: str):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
            # | Qt.WindowType.WindowTransparentForInput
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
            self.view.page().runJavaScript("startStreaming();")

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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            print("[PIA] Botão esquerdo clicado: encerrando sessão e fechando overlay.")
            from . import state as _state

            with _state.LOCK:
                _state.SESSION_ACTIVE = False
            self.close()
        else:
            # O clique esquerdo é ignorado pelo widget, fazendo com que atravesse para o que está abaixo
            event.ignore()

    def eventFilter(self, obj, event):
        if obj == self.view and event.type() == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                print(
                    "[PIA] Botão esquerdo clicado: encerrando sessão e fechando overlay."
                )
                from . import state as _state

                with _state.LOCK:
                    _state.SESSION_ACTIVE = False
                self.close()
                return True
            else:
                event.ignore()
        return super().eventFilter(obj, event)

    def set_inner_orbit_fast(self, fast: bool):
        # print log to indicate the inner orbit movement state change
        print(f"[PIA] Inner orbit fast: {fast}")
        val = "running" if fast else "paused"
        self.view.page().runJavaScript(
            f"document.querySelector('.animation-orbit-clockwise').style.animationPlayState = '{val}';"
        )

    def set_outer_orbit_fast(self, fast: bool):
        # print log to indicate the outer orbit movement state change
        print(f"[PIA] Outer orbit fast: {fast}")
        val = "running" if fast else "paused"
        self.view.page().runJavaScript(
            f"document.querySelector('.animation-orbit-anti-clockwise').style.animationPlayState = '{val}';"
        )

    def set_eyes_moving(self, moving: bool):
        # print log to indicate the eyes movement state change
        print(f"[PIA] Eyes moving: {moving}")
        val = "running" if moving else "paused"
        self.view.page().runJavaScript(
            f"document.querySelector('.animation-looking-eyes').style.animationPlayState = '{val}';"
        )

    def blink(self):
        # print log to indicate the blink action
        print("[PIA] Triggering blink animation")
        self.view.page().runJavaScript("""
            var eyes = document.querySelector('.animation-blinking-eyes');
            if (eyes) {
                eyes.style.animation = 'none';
                void eyes.offsetHeight;
                eyes.style.animation = 'blink 1.5s linear infinite';
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
<script>
    let eventSource = null;
    let stopRequested = false;

    function startStreaming() {{
        if (eventSource) return; // Evita múltiplas instâncias
        
        eventSource = new EventSource("{TTS_SERVER_URL}/status/stream");

        eventSource.onmessage = function(event) {{
            const data = JSON.parse(event.data);
            const mouth = document.querySelector('.enable-mouth');
            const talking = document.querySelector('.animation-talking');
            
            if (!talking.dataset.listenerAdded) {{
                talking.dataset.listenerAdded = "true";
                talking.addEventListener('animationiteration', () => {{
                    if (stopRequested) {{
                        mouth.style.opacity = "0";
                        talking.style.animationPlayState = "paused";
                        stopRequested = false;
                    }}
                }});
            }}

            if (data.status === "playing") {{
                stopRequested = false;
                mouth.style.opacity = "1";
                talking.style.animationPlayState = "running";
            }} else {{
                stopRequested = true;
            }}
        }};

        eventSource.onerror = function(err) {{
            console.error("Erro na conexão SSE:", err);
        }};
    }}
</script>
</head>
<body>{svg_raw}</body>
</html>
"""
    else:
        svg_content = (
            "<html><body><h3>Arquivo pia.svg não encontrado</h3></body></html>"
        )

    # Habilita a inspeção remota na porta 9222
    # os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9222"

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    overlay = PiaOverlay(svg_content)
    _GLOBAL_OVERLAY = overlay

    def check_visibility():
        try:
            if overlay.should_stay_visible():
                if not overlay.isVisible():
                    overlay.show()
            else:
                if overlay.isVisible():
                    overlay.hide()
        except KeyboardInterrupt:
            pass

    timer = QTimer()
    timer.timeout.connect(check_visibility)
    timer.start(100)

    app.exec()

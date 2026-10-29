"""Qt owns native windows/tray only. Every workspace/app page is HTML."""
from concurrent.futures import Future
import importlib.util
import sys
import threading
import time
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, QEvent, pyqtSignal
from PyQt6.QtGui import QIcon, QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QMenu, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage

from .config import PORT
from .config_paths import IMAGES_DIR
from .pia.service import get_service
from .piamini.controls import MiniControls


class LocalPage(QWebEnginePage):
    def __init__(self, parent, origin):
        super().__init__(parent)
        self.origin = origin
        self.newWindowRequested.connect(lambda request: QDesktopServices.openUrl(request.requestedUrl())
            if request.requestedUrl().scheme() in ('http', 'https') else None)

    def acceptNavigationRequest(self, url, kind, main):
        if url.toString().startswith(self.origin + '/') or url.toString() == 'about:blank':
            return True
        if main and url.scheme() in ('http', 'https'):
            QDesktopServices.openUrl(url)
        return False


class WebShell(QMainWindow):
    hidden = pyqtSignal()

    def __init__(self, url, origin, *, tool=False, composer=False):
        flags = Qt.WindowType.Window
        if tool:
            flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.composer = composer
        self.opened_at = 0
        self.setWindowTitle('Mensagem à PIA' if composer else 'PIA')
        self.setWindowIcon(QIcon(str(IMAGES_DIR / 'pia.png')))
        self.view = QWebEngineView(self)
        self.view.setPage(LocalPage(self.view, origin))
        self.setCentralWidget(self.view)
        self.inspector = None
        if not composer:
            shortcut = QShortcut(QKeySequence('F12'), self)
            shortcut.activated.connect(self.inspect)
            self.inspect_shortcut = shortcut
        self.resize(440, 205) if composer else self.resize(1280, 820)
        self.target = url
        self.retries = 0
        self.view.loadFinished.connect(self.loaded)
        self.view.setUrl(QUrl(url))

    def inspect(self):
        if self.inspector is None:
            self.inspector = QWebEngineView()
            self.inspector.setWindowTitle('PIA · Inspetor HTML / CSS / JavaScript')
            self.inspector.resize(1100, 740)
            self.view.page().setDevToolsPage(self.inspector.page())
        self.inspector.show()
        self.inspector.raise_()

    def loaded(self, success):
        if not success and self.retries < 15:
            self.retries += 1
            QTimer.singleShot(500, lambda: self.view.setUrl(QUrl(self.target)))

    def present(self):
        self.opened_at = time.monotonic()
        self.show()
        self.raise_()
        self.activateWindow()
        self.view.setFocus()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.hidden.emit()

    def event(self, event):
        if getattr(self, 'composer', False) and event.type() == QEvent.Type.WindowDeactivate:
            QTimer.singleShot(120, self.check_outside)
        return super().event(event)

    def check_outside(self):
        if self.isVisible() and not self.isActiveWindow() and time.monotonic() - self.opened_at > .45:
            self.hide()
            self.hidden.emit()


class GuiBridge(QObject):
    requested = pyqtSignal(str, object, object)

    def __init__(self, ui):
        super().__init__(ui)
        self.ui = ui
        self.requested.connect(self.execute)

    def call(self, command, payload):
        future = Future()
        self.requested.emit(command, payload, future)
        return future

    def execute(self, command, payload, future):
        try:
            value = self.ui.command(command, payload)
            if isinstance(value, Future):
                def done(result):
                    try:
                        future.set_result(result.result())
                    except Exception as exc:
                        future.set_exception(exc)
                value.add_done_callback(done)
            else:
                future.set_result(value)
        except Exception as exc:
            future.set_exception(exc)


class DesktopUI(QObject):
    def __init__(self, overlay, service=None, url=None):
        super().__init__(overlay)
        self.overlay = overlay
        self.service = service or get_service()
        self.backend = self.service.backend
        self.url = url or f'http://localhost:{PORT}'
        self.bridge = GuiBridge(self)
        self.service.native_handler = self.bridge.call
        self.native_apps = {}
        self.capture_windows = []
        self.window = WebShell(self.url + '/', self.url)
        self.composer = WebShell(self.url + '/mini/composer.html', self.url, tool=True, composer=True)
        self.controls = MiniControls(self)
        self.setup_tray()
        self.window.hidden.connect(lambda: self.main_action.setChecked(False))
        self.backend.secretary.start()
        if hasattr(self.backend, 'start_connectors'):
            self.backend.start_connectors()
        if __import__('os').environ.pop('PIA_OPEN_MAIN', '')=='1':
            QTimer.singleShot(800,lambda:self.set_main_visible(True))
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(QIcon(str(IMAGES_DIR / 'pia.png')), self)
        self.tray.setToolTip('PIA')
        self.tray_menu = QMenu()
        self.main_action = self.tray_menu.addAction('Exibir PIA')
        self.main_action.setCheckable(True)
        self.main_action.toggled.connect(self.set_main_visible)
        self.mini_action = self.tray_menu.addAction('Exibir PIA Mini')
        self.mini_action.setCheckable(True)
        self.mini_action.setChecked(True)
        self.mini_action.toggled.connect(self.set_mini_visible)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction('Encerrar PIA').triggered.connect(QApplication.instance().quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda reason: self.set_main_visible(True)
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def set_main_visible(self, visible):
        self.main_action.blockSignals(True)
        self.main_action.setChecked(visible)
        self.main_action.blockSignals(False)
        self.window.present() if visible else self.window.hide()

    def set_mini_visible(self, visible):
        self.mini_action.blockSignals(True)
        self.mini_action.setChecked(visible)
        self.mini_action.blockSignals(False)
        self.overlay.user_hidden = not visible
        if visible:
            self.overlay.show()
            self.controls.keep_on_top()
        else:
            self.overlay.hide()
            self.controls.menu.hide()
            self.composer.hide()

    def open_composer(self):
        self.composer.move(self.controls.nearby(self.composer.size()))
        self.composer.present()

    def microphone(self):
        def work():
            try:
                self.backend.toggle_voice(lambda text: self.send_mini(text))
            except Exception as exc:
                self.bridge.call('notify', {'title': 'Microfone', 'text': str(exc)})
        threading.Thread(target=work, daemon=True).start()

    def send_mini(self, text):
        previous=getattr(self,'_mini_voice_job',None)
        if previous is not None:
            previous.cancelled.set()
            # Microphone capture keeps running while its dispatcher waits for
            # the cancelled completion to release the chat lock.
            with previous.changed:
                while previous.status=='running':
                    if self.backend.voice_stop.is_set():return
                    previous.changed.wait(.2)
        chat = self.service.store.get('mini:chat')
        if not chat or not any(c['id'] == chat for c in self.service.store.chat_records()):
            chat = self.service.store.new_chat('Mini PIA')
            self.service.store.set('mini:chat', chat)
        job = self.service.send(chat, text)
        self._mini_voice_job=self.service.jobs[job]
        self.backend.cancel_voice_reply=lambda: self.service.jobs[job].cancelled.set()
        self.speak_job(job)

    def speak_job(self, identity):
        job = self.service.jobs[identity]
        from .voice_interrupt import epoch
        generation=epoch()
        def wait():
            with job.changed:
                while job.status == 'running':
                    job.changed.wait(1)
            if job.status == 'done' and job.text and not job.cancelled.is_set() and epoch()==generation:
                self.backend.speak(job.text,conversation_epoch=generation)
        threading.Thread(target=wait, daemon=True).start()

    def app_native(self, identity, action, payload):
        if identity not in self.native_apps:
            record = self.service.apps.find(identity)
            path = (record['folder'] / record['web']['native']).resolve()
            if not path.is_relative_to(record['folder'].resolve()):
                raise ValueError('Adaptador nativo inválido.')
            package = '_pia_web_app_' + identity
            # Load the API first so the app has a package for relative imports.
            if identity not in self.service.apps.modules:
                self.service.apps.load(identity)
            spec = importlib.util.spec_from_file_location(package + '.native', path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            self.native_apps[identity] = module.NativeApp(self, self.service)
        return self.native_apps[identity].handle(action, payload)

    def command(self, action, payload):
        if action == 'restart':
            import subprocess
            import os
            from .config_paths import BASE_DIR,CONFIG_DIR
            from dotenv import dotenv_values
            from .env_types import split_key
            env=os.environ.copy()
            for file in (CONFIG_DIR/'.env',CONFIG_DIR/'.env.example'):
                for key in dotenv_values(file):
                    env.pop(key,None)
                    env.pop(split_key(key)[0],None)
            env['PIA_OPEN_MAIN']='1'
            flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
            subprocess.Popen([sys.executable,'-m','src.launcher','--restart-pid',str(os.getpid())],cwd=BASE_DIR,env=env,creationflags=flags,start_new_session=sys.platform!='win32')
            QTimer.singleShot(700,QApplication.instance().quit)
            return {'ok':True}
        if action == 'inspect':
            self.window.inspect()
            return {'ok': True}
        if action == 'choose-path':
            mode = payload.get('mode', 'directory')
            selected = QFileDialog.getOpenFileName(self.window, 'Selecionar arquivo')[0] if mode == 'file' else QFileDialog.getExistingDirectory(self.window, 'Selecionar pasta')
            return {'path': selected}
        if action == 'reveal-file':
            from pathlib import Path
            file = Path(payload['path']).expanduser().resolve()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file.parent)))
            return {'ok': True}
        if action == 'clipboard-text':
            QApplication.clipboard().setText(str(payload['text']))
            return {'ok':True}
        if action == 'dictate':
            from .pia.service import Job
            job = Job()
            self.service.jobs[job.id] = job
            def record():
                try:
                    active = self.backend.toggle_voice(lambda text: job.emit('delta',text=text+' '),
                        dictation=True,on_end=lambda: job.emit('done'))
                    if not active: job.emit('done')
                except Exception as exc: job.emit('error',error=str(exc))
            threading.Thread(target=record,daemon=True).start()
            return {'job':job.id}
        if action == 'voice':
            self.microphone()
        elif action == 'show':
            self.set_main_visible(bool(payload.get('visible', True)))
        elif action == 'mini':
            self.set_mini_visible(bool(payload.get('visible', True)))
        elif action == 'mini-compose-close':
            self.composer.hide()
        elif action == 'mini-job':
            self.speak_job(payload['job'])
        elif action == 'app':
            return self.app_native(payload['id'], payload['action'], payload.get('payload', {}))
        elif action == 'notify':
            self.tray.showMessage(payload.get('title', 'PIA'), payload.get('text', ''), QSystemTrayIcon.MessageIcon.Information, 10000)
            if payload.get('speak'):
                threading.Thread(target=self.backend.speak, args=(payload['text'],), daemon=True).start()
        elif action == 'autostart':
            from . import autostart
            if 'enabled' in payload:
                autostart.set_enabled(bool(payload['enabled']))
            return {'enabled': autostart.is_enabled()}
        else:
            raise ValueError('Ação nativa desconhecida.')
        return {'ok': True}

    def shutdown(self):
        for plugin in self.native_apps.values():
            if hasattr(plugin, 'shutdown'):
                plugin.shutdown()
        self.backend.shutdown()

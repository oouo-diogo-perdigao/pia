"""OS capture/clipboard/file dialogs. Image selection and editing live in web/."""
from concurrent.futures import Future
import base64
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys
import uuid
from urllib.request import urlopen

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QRect, QTimer, QStandardPaths, QMimeData, QUrl, QPoint, Qt
from PyQt6.QtGui import QImage, QPainter, QGuiApplication, QDesktopServices, QDrag, QPixmap
from PyQt6.QtWidgets import QApplication, QFileDialog

from .web_api import config


def png_data(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(bytes(buffer.data())).decode()


def decode_image(value):
    if not isinstance(value, str) or len(value) > 40 * 1024 * 1024 or not value.startswith('data:image/png;base64,'):
        raise ValueError('Imagem PNG inválida ou maior que 40 MiB.')
    raw = base64.b64decode(value.split(',', 1)[1], validate=True)
    image = QImage.fromData(raw, 'PNG')
    if image.isNull():
        raise ValueError('Não foi possível ler a imagem.')
    return image


def filename(title):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:100] or 'Captura'
    return clean + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')


def foreground(include_url=False):
    title, url, rect = '', '', None
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        user.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user.GetForegroundWindow()
        text = ctypes.create_unicode_buffer(1024)
        user.GetWindowTextW(hwnd, text, len(text))
        title = text.value
        box = wintypes.RECT()
        if user.GetWindowRect(hwnd, ctypes.byref(box)):
            rect = QRect(box.left, box.top, box.right - box.left, box.bottom - box.top)
        if include_url:
            try:
                import uiautomation as auto
                with auto.UIAutomationInitializerInThread():
                    control = auto.ControlFromHandle(hwnd)
                    for index, (child, _) in enumerate(auto.WalkControl(control, maxDepth=8)):
                        if index > 250:
                            break
                        if child.ControlTypeName == 'EditControl' and any(
                            key in child.Name.lower() for key in ('address', 'endereço', 'url', 'adresse')):
                            value = child.GetValuePattern().Value
                            if value.startswith(('http://', 'https://')):
                                url = value
                                break
            except Exception:
                pass
    elif sys.platform.startswith('linux'):
        try:
            identity = subprocess.check_output(['xdotool', 'getactivewindow'], timeout=2, text=True).strip()
            title = subprocess.check_output(['xdotool', 'getwindowname', identity], timeout=2, text=True).strip()
            geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', identity], timeout=2, text=True)
            values = dict(line.split('=', 1) for line in geometry.splitlines() if '=' in line)
            rect = QRect(*[int(values[k]) for k in ('X', 'Y', 'WIDTH', 'HEIGHT')])
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            pass
    return title, url, rect


class CaptureShell:
    """Lazy shell construction avoids a dependency cycle with the host wrapper."""
    @staticmethod
    def create(ui, url, geometry):
        from src.desktop_ui import WebShell
        shell = WebShell(url, ui.url, tool=True)
        shell.setGeometry(geometry)
        return shell


class NativeApp:
    def __init__(self, ui, context):
        self.ui, self.context = ui, context
        from src.config_paths import BASE_DIR
        self.folder = BASE_DIR / 'logs/screenshots'
        legacy=BASE_DIR/'data/screenshots/raw'
        if legacy.is_dir() and not legacy.is_symlink():
            import shutil
            target=self.folder/('legacy-'+uuid.uuid4().hex)
            if legacy.resolve().is_relative_to(BASE_DIR.resolve()) and target.resolve().is_relative_to(BASE_DIR.resolve()):
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(legacy),str(target))
        self.records = {}
        self.shell = None
        self.stage = None
        self.current = None

    def restore(self):
        if self.ui.main_action.isChecked():
            self.ui.window.show()

    def discard_raw(self):
        if self.current:
            record=self.records.pop(self.current,None)
            if record:record['path'].unlink(missing_ok=True)
            self.current=None

    def store_capture(self, image, title='', url='', mode='selection'):
        self.folder.mkdir(parents=True, exist_ok=True)
        identity = uuid.uuid4().hex
        path = self.folder / (identity + '.png')
        if not image.save(str(path), 'PNG'):
            raise RuntimeError('Não foi possível armazenar a captura.')
        self.records[identity] = {'id': identity, 'path': path, 'title': title, 'comment': url,
                                  'width': image.width(), 'height': image.height(), 'mode': mode}
        self.current = identity
        return identity

    def capture(self, mode):
        if mode not in ('selection', 'window'):
            raise ValueError('Modo de captura inválido.')
        self.discard_raw()
        if self.shell:
            self.shell.hide()
            self.shell.deleteLater()
            self.shell = None
        result = Future()
        def take():
            try:
                prefs = config()
                title, url, active = foreground(prefs['prefill_url'])
                screens = QGuiApplication.screens()
                geometry = QRect()
                for screen in screens:
                    geometry = geometry.united(screen.geometry())
                # Use the same local HTTP capture endpoint as skills and other clients.
                with urlopen(self.ui.url + '/action/screen-all', timeout=30) as response:
                    image = QImage.fromData(response.read(), 'PNG')
                if image.isNull():
                    raise RuntimeError('A rota /action/screen-all não retornou uma imagem PNG válida.')
                if mode == 'window':
                    if active is None:
                        raise RuntimeError('Não foi possível identificar a janela ativa neste desktop.')
                    crop = active.translated(-geometry.x(), -geometry.y()).intersected(image.rect())
                    if crop.isEmpty():
                        raise RuntimeError('A janela ativa está fora da área capturada.')
                    image = image.copy(crop)
                identity = self.store_capture(image, title if prefs['prefill_title'] else '', url, mode)
                self.geometry = geometry
                self.stage = 'capture'
                self.shell = CaptureShell.create(self.ui, self.ui.url + '/apps/screenshots/capture.html?id=' + identity, geometry)
                self.shell.hidden.connect(self.restore)
                self.shell.present()
                result.set_result({'id': identity})
            except Exception as exc:
                self.restore()
                result.set_exception(exc)
        QTimer.singleShot(0, take)
        return result

    def output_directory(self):
        return Path(config()['output_folder'] or str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)) / 'PIA Captures'))

    def saved_files(self):
        directory = self.output_directory()
        files = []
        if directory.is_dir():
            for path in sorted(directory.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
                if path.is_file() and path.suffix.lower() in ('.png','.jpg','.jpeg','.bmp'):
                    files.append({'name':path.name,'size':path.stat().st_size})
        return files

    def saved_path(self,name):
        if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or Path(name).suffix.lower() not in ('.png','.jpg','.jpeg','.bmp'):
            raise ValueError('Captura não encontrada.')
        directory=self.output_directory().resolve()
        candidate=directory/name
        path=candidate.resolve()
        if not path.is_relative_to(directory) or not path.is_file():raise ValueError('Captura não encontrada.')
        return candidate

    def handle(self, action, data):
        if action == 'copy-saved':
            image = QImage(str(self.saved_path(data['name'])))
            if image.isNull():
                raise ValueError('Imagem inválida.')
            QApplication.clipboard().setImage(image)
            return {'ok': True}
        if action == 'choose-folder':
            directory = QFileDialog.getExistingDirectory(self.ui.window,'Pasta das capturas',str(self.output_directory()))
            return {'folder':directory}
        if action in ('delete-saved','open-saved'):
            names=data.get('names',[]) if action=='delete-saved' else [data.get('name','')]
            if not isinstance(names,list) or not names:raise ValueError('Captura não encontrada.')
            paths=[self.saved_path(name) for name in names]
            for path in paths:
                if action=='delete-saved': path.unlink()
                elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))): raise RuntimeError('Não foi possível abrir a captura.')
            return {'ok':True}
        if action == 'list-saved':
            files=self.saved_files();offset=max(0,int(data.get('offset',0)));limit=max(1,min(48,int(data.get('limit',24))))
            return {'captures':files[offset:offset+limit],'total':len(files),'folder':str(self.output_directory())}
        if action == 'saved-image':
            name = data.get('name','')
            image = QImage(str(self.saved_path(name)))
            if data.get('thumbnail'): image = image.scaled(320,220,Qt.AspectRatioMode.KeepAspectRatio)
            return {'data':png_data(image)}
        if action == 'status':
            return {'available': True, 'folder':str(self.output_directory()),'captures': self.saved_files()}
        if action == 'capture':
            return self.capture(data.get('mode', 'selection'))
        if action == 'image':
            record = self.records[data['id']]
            return {**{k: v for k, v in record.items() if k != 'path'}, 'data': png_data(QImage(str(record['path']))), 'config': config()}
        if action == 'cancel':
            self.discard_raw()
            if self.shell:
                self.shell.hide()
            self.restore()
            return {'ok': True}
        if action == 'color':
            value = data.get('value', '')
            if not re.fullmatch('#[0-9a-fA-F]{6}', value):
                raise ValueError('Cor inválida.')
            QApplication.clipboard().setText(value)
            return {'ok': True}
        image = decode_image(data.get('data'))
        if action == 'copy':
            QApplication.clipboard().setImage(image)
            return {'ok': True}
        if action in ('finalize', 'save', 'desktop', 'drag', 'edit', 'print'):
            prefs = config()
            kind = data.get('format', prefs['format'])
            if kind not in ('png', 'jpg', 'bmp'):
                raise ValueError('Formato inválido.')
            name = filename(str(data.get('title', 'Captura'))) + '.' + kind
            if action == 'finalize':
                if prefs['auto_copy']: QApplication.clipboard().setImage(image)
                path = self.output_directory() / name
                if not prefs['auto_save']:
                    self.discard_raw()
                    if self.shell: self.shell.hide()
                    self.restore()
                    return {'ok':True}
            elif action == 'desktop':
                directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation))
                path = directory / name
            elif action == 'save':
                directory = prefs['output_folder'] or str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / 'PIA Captures')
                target, _ = QFileDialog.getSaveFileName(self.shell, 'Salvar captura', str(Path(directory) / name),
                    {'png': 'PNG (*.png)', 'jpg': 'JPEG (*.jpg)', 'bmp': 'Bitmap (*.bmp)'}[kind])
                if not target:
                    return {'cancelled': True}
                path = Path(target)
            else:
                path = self.folder / name
            if action == 'print':
                from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog = QPrintDialog(printer, self.shell)
                if dialog.exec():
                    painter = QPainter(printer)
                    area = painter.viewport()
                    size = image.size()
                    size.scale(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    painter.drawImage(QRect(area.topLeft(), size), image)
                    painter.end()
                return {'ok': True}
            path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(path), 'JPEG' if kind == 'jpg' else kind.upper(), int(prefs['quality'])):
                raise RuntimeError('Não foi possível salvar a captura.')
            if action == 'edit':
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            if action == 'drag':
                def drag_image():
                    drag = QDrag(self.shell.view if self.shell else self.ui.window.view)
                    mime = QMimeData()
                    mime.setImageData(image)
                    mime.setUrls([QUrl.fromLocalFile(str(path))])
                    drag.setMimeData(mime)
                    drag.setPixmap(QPixmap.fromImage(image).scaledToWidth(240))
                    drag.exec(Qt.DropAction.CopyAction)
                QTimer.singleShot(0, drag_image)
            if action == 'finalize':
                self.discard_raw()
                if self.shell: self.shell.hide()
                self.restore()
            elif action in ('save','desktop'):
                self.discard_raw()
            return {'ok': True, 'name': path.name}
        raise ValueError('Operação desconhecida.')

    def shutdown(self):
        self.discard_raw()
        if self.shell:
            self.shell.hide()

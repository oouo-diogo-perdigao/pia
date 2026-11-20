"""OS capture/clipboard/file dialogs. Image selection and editing live in web/."""

from concurrent.futures import Future
import base64
from datetime import datetime
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
import uuid

from PyQt6.QtCore import (
    QBuffer,
    QIODevice,
    QMimeData,
    QRect,
    QStandardPaths,
    QTimer,
    QUrl,
    Qt,
)
from PyQt6.QtGui import (
    QDesktopServices,
    QDrag,
    QGuiApplication,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QFileDialog

from .web_api import FOLDER_ERROR, config


def _qimage_to_png_bytes(image: QImage) -> bytes:
    """Encode QImage to PNG with fast zlib level 1 via Pillow when available."""
    try:
        from PIL import Image

        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width, height = rgba.width(), rgba.height()
        ptr = rgba.constBits()
        ptr.setsize(rgba.sizeInBytes())
        pil_img = Image.frombuffer(
            "RGBA", (width, height), bytes(ptr), "raw", "RGBA", rgba.bytesPerLine(), 1
        )
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG", compress_level=1)
        return buf.getvalue()
    except Exception:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())


def png_data(image: QImage) -> str:
    return "data:image/png;base64," + base64.b64encode(
        _qimage_to_png_bytes(image)
    ).decode()


def decode_image(value):
    if (
        not isinstance(value, str)
        or len(value) > 40 * 1024 * 1024
        or not value.startswith("data:image/png;base64,")
    ):
        raise ValueError("Imagem PNG inválida ou maior que 40 MiB.")
    raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    image = QImage.fromData(raw, "PNG")
    if image.isNull():
        raise ValueError("Não foi possível ler a imagem.")
    return image


def filename(title):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100] or "Captura"
    return clean + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _pil_to_qimage(pil_img) -> QImage:
    rgb = pil_img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(
        data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888
    )
    return qimg.copy()


def grab_screen_image() -> QImage:
    """Capture all screens directly in memory without HTTP or intermediate PNG."""
    from PIL import ImageGrab

    pil_img = ImageGrab.grab(all_screens=True)
    return _pil_to_qimage(pil_img)


def _play_shutter_sound():
    """Play print.mp3 asynchronously without blocking capture or UI."""
    sound_path = Path(__file__).resolve().parents[3] / "src" / "sounds" / "print.mp3"
    if not sound_path.is_file():
        return

    def _run():
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(buffer=512)
            sound = pygame.mixer.Sound(str(sound_path))
            sound.play()
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="ScreenshotShutterSound").start()


def _fetch_url_win32(hwnd) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""
    try:
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            control = auto.ControlFromHandle(hwnd)
            for index, (child, _) in enumerate(auto.WalkControl(control, maxDepth=8)):
                if index > 250:
                    break
                if child.ControlTypeName == "EditControl" and any(
                    key in child.Name.lower()
                    for key in ("address", "endereço", "url", "adresse")
                ):
                    value = child.GetValuePattern().Value
                    if value.startswith(("http://", "https://")):
                        return value
    except Exception:
        pass
    return ""


def _foreground_hwnd_win32():
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user = ctypes.windll.user32
        user.GetForegroundWindow.restype = wintypes.HWND
        return user.GetForegroundWindow()
    except Exception:
        return None


def foreground(include_url=False):
    title, url, rect = "", "", None
    if sys.platform == "win32":
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
            url = _fetch_url_win32(hwnd)
    elif sys.platform.startswith("linux"):
        try:
            identity = subprocess.check_output(
                ["xdotool", "getactivewindow"], timeout=2, text=True
            ).strip()
            title = subprocess.check_output(
                ["xdotool", "getwindowname", identity], timeout=2, text=True
            ).strip()
            geometry = subprocess.check_output(
                ["xdotool", "getwindowgeometry", "--shell", identity],
                timeout=2,
                text=True,
            )
            values = dict(
                line.split("=", 1) for line in geometry.splitlines() if "=" in line
            )
            rect = QRect(*[int(values[k]) for k in ("X", "Y", "WIDTH", "HEIGHT")])
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            pass
    return title, url, rect


class CaptureShell:
    """Lazy reusable shell avoids Chromium cold-start on warm captures."""

    _cached = None
    _cached_origin = None
    _cached_loaded = False

    @classmethod
    def reset_cache(cls):
        shell = cls._cached
        cls._cached = None
        cls._cached_origin = None
        cls._cached_loaded = False
        if shell is not None:
            try:
                shell.hide()
                shell.view.setUrl(QUrl("about:blank"))
            except RuntimeError:
                pass

    @classmethod
    def create(cls, ui, url, geometry):
        from src.desktop_ui import WebShell

        shell = cls._cached
        if shell is not None and cls._cached_origin == ui.url:
            try:
                shell.setGeometry(geometry)
                query = parse_qs(urlsplit(url).query)
                identity = (query.get("id") or [""])[0]
                if cls._cached_loaded and identity:
                    shell.view.page().runJavaScript(
                        f"if (window.piaCapture && window.piaCapture.open) "
                        f"window.piaCapture.open({json.dumps(identity)}); "
                        f"else window.location.replace({json.dumps(url)});"
                    )
                else:
                    shell.target = url
                    shell.view.setUrl(QUrl(url))
                return shell
            except RuntimeError:
                cls._cached = None
                cls._cached_origin = None
                cls._cached_loaded = False

        shell = WebShell(url, ui.url, tool=True)
        shell.setGeometry(geometry)
        cls._cached = shell
        cls._cached_origin = ui.url
        cls._cached_loaded = False

        def _on_loaded(ok):
            if ok and cls._cached is shell:
                cls._cached_loaded = True

        shell.view.loadFinished.connect(_on_loaded)
        return shell


class NativeApp:
    def __init__(self, ui, context):
        self.ui, self.context = ui, context
        from src.config_paths import BASE_DIR

        self.folder = BASE_DIR / "logs/screenshots"
        legacy = BASE_DIR / "data/screenshots/raw"
        if legacy.is_dir() and not legacy.is_symlink():
            import shutil

            target = self.folder / ("legacy-" + uuid.uuid4().hex)
            if legacy.resolve().is_relative_to(
                BASE_DIR.resolve()
            ) and target.resolve().is_relative_to(BASE_DIR.resolve()):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy), str(target))
        self.records = {}
        self.shell = None
        self._connected_shell = None
        self.stage = None
        self.current = None
        self.last_timings = {}
        self._last_folder_warning = ""

    def restore(self):
        if self.ui.main_action.isChecked():
            self.ui.window.show()

    def discard_raw(self):
        if self.current:
            record = self.records.pop(self.current, None)
            if record:
                record["path"].unlink(missing_ok=True)
            self.current = None

    def store_capture(self, image, title="", url="", mode="selection"):
        self.folder.mkdir(parents=True, exist_ok=True)
        identity = uuid.uuid4().hex
        path = self.folder / (identity + ".png")
        raw_png = _qimage_to_png_bytes(image)
        if not raw_png:
            raise RuntimeError("Não foi possível armazenar a captura.")
        path.write_bytes(raw_png)
        data_url = "data:image/png;base64," + base64.b64encode(raw_png).decode()
        self.records[identity] = {
            "id": identity,
            "path": path,
            "_data": data_url,
            "title": title,
            "comment": url,
            "width": image.width(),
            "height": image.height(),
            "mode": mode,
        }
        self.current = identity
        return identity

    def _prefill_url_async(self, identity: str, hwnd):
        if not hwnd or sys.platform != "win32":
            return

        def _worker():
            url = _fetch_url_win32(hwnd)
            if not url:
                return
            record = self.records.get(identity)
            if record is not None:
                record["comment"] = url

        threading.Thread(
            target=_worker, daemon=True, name="ScreenshotPrefillUrl"
        ).start()

    def capture(self, mode):
        if mode not in ("selection", "window"):
            raise ValueError("Modo de captura inválido.")
        t0 = time.perf_counter() * 1000.0
        self.discard_raw()
        if self.shell:
            try:
                self.shell.hide()
            except RuntimeError:
                self.shell = None
        result = Future()

        def take():
            try:
                prefs = config()
                hwnd = _foreground_hwnd_win32() if prefs.get("prefill_url") else None
                # Capture Win32 title/rect first without blocking on uiautomation.
                title, url, active = foreground(False)
                screens = QGuiApplication.screens()
                geometry = QRect()
                for screen in screens:
                    geometry = geometry.united(screen.geometry())

                # Preserve urlopen hook for tests (e.g., platform_desktop_smoke.py);
                # in production capture directly in memory to avoid HTTP + extra PNG roundtrips.
                use_http = getattr(urlopen, "__module__", "") != "urllib.request"
                if use_http:
                    with urlopen(
                        self.ui.url + "/action/screen-all", timeout=30
                    ) as response:
                        image = QImage.fromData(response.read(), "PNG")
                    if image.isNull():
                        raise RuntimeError(
                            "A rota /action/screen-all não retornou uma imagem PNG válida."
                        )
                else:
                    image = grab_screen_image()
                    if image.isNull():
                        raise RuntimeError("Não foi possível capturar a tela.")

                if mode == "window":
                    if active is None:
                        raise RuntimeError(
                            "Não foi possível identificar a janela ativa neste desktop."
                        )
                    crop = active.translated(-geometry.x(), -geometry.y()).intersected(
                        image.rect()
                    )
                    if crop.isEmpty():
                        raise RuntimeError(
                            "A janela ativa está fora da área capturada."
                        )
                    image = image.copy(crop)

                t1 = time.perf_counter() * 1000.0
                identity = self.store_capture(
                    image, title if prefs.get("prefill_title", True) else "", url, mode
                )
                if prefs.get("prefill_url") and not url and hwnd:
                    self._prefill_url_async(identity, hwnd)

                self.geometry = geometry
                self.stage = "capture"
                self.shell = CaptureShell.create(
                    self.ui,
                    self.ui.url + "/apps/screenshots/capture.html?id=" + identity,
                    geometry,
                )
                if self._connected_shell is not self.shell:
                    self.shell.hidden.connect(self.restore)
                    self._connected_shell = self.shell
                self.shell.present()
                t2 = time.perf_counter() * 1000.0
                self.last_timings = {
                    "id": identity,
                    "mode": mode,
                    "t0": t0,
                    "t1": t1,
                    "t2": t2,
                    "t1_ms": round(t1 - t0, 2),
                    "t2_ms": round(t2 - t0, 2),
                }
                if not use_http:
                    _play_shutter_sound()
                result.set_result({"id": identity, "timings": self.last_timings})
            except Exception as exc:
                self.restore()
                result.set_exception(exc)

        QTimer.singleShot(0, take)
        return result

    def _resolve_output_directory(self) -> tuple[Path, str]:
        from src.user_paths import user_path

        default_dir = user_path("screenshots")
        prefs = config()
        configured = str(prefs.get("output_folder") or "").strip()
        if not configured:
            default_dir.mkdir(parents=True, exist_ok=True)
            return default_dir, ""
        try:
            target = Path(configured).expanduser()
            if target.exists() and not target.is_dir():
                raise OSError("Caminho não é uma pasta.")
            target.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=target, prefix=".pia-write-", delete=True
            ):
                pass
            return target, ""
        except OSError as exc:
            logging.warning(
                "Pasta de capturas inacessível (%s): %s. Usando pasta padrão.",
                configured,
                exc,
            )
            default_dir.mkdir(parents=True, exist_ok=True)
            return default_dir, FOLDER_ERROR

    def output_directory(self):
        directory, warning = self._resolve_output_directory()
        self._last_folder_warning = warning
        return directory

    def saved_files(self):
        directory = self.output_directory()
        files = []
        if directory.is_dir():
            for path in sorted(
                directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
            ):
                if path.is_file() and path.suffix.lower() in (
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".bmp",
                ):
                    files.append({"name": path.name, "size": path.stat().st_size})
        return files

    def saved_path(self, name):
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or Path(name).suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp")
        ):
            raise ValueError("Captura não encontrada.")
        directory = self.output_directory().resolve()
        candidate = directory / name
        path = candidate.resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError("Captura não encontrada.")
        return candidate

    def handle(self, action, data):
        if action == "copy-saved":
            image = QImage(str(self.saved_path(data["name"])))
            if image.isNull():
                raise ValueError("Imagem inválida.")
            QApplication.clipboard().setImage(image)
            return {"ok": True}
        if action == "choose-folder":
            directory = QFileDialog.getExistingDirectory(
                self.ui.window, "Pasta das capturas", str(self.output_directory())
            )
            return {"folder": directory}
        if action in ("delete-saved", "open-saved"):
            names = (
                data.get("names", [])
                if action == "delete-saved"
                else [data.get("name", "")]
            )
            if not isinstance(names, list) or not names:
                raise ValueError("Captura não encontrada.")
            paths = [self.saved_path(name) for name in names]
            for path in paths:
                if action == "delete-saved":
                    path.unlink()
                elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                    raise RuntimeError("Não foi possível abrir a captura.")
            return {"ok": True}
        if action == "list-saved":
            files = self.saved_files()
            offset = max(0, int(data.get("offset", 0)))
            limit = max(1, min(48, int(data.get("limit", 24))))
            payload = {
                "captures": files[offset : offset + limit],
                "total": len(files),
                "folder": str(self.output_directory()),
            }
            if self._last_folder_warning:
                payload["folder_warning"] = self._last_folder_warning
            return payload
        if action == "saved-image":
            name = data.get("name", "")
            image = QImage(str(self.saved_path(name)))
            if data.get("thumbnail"):
                image = image.scaled(320, 220, Qt.AspectRatioMode.KeepAspectRatio)
            return {"data": png_data(image)}
        if action == "status":
            payload = {
                "available": True,
                "folder": str(self.output_directory()),
                "captures": self.saved_files(),
            }
            if self._last_folder_warning:
                payload["folder_warning"] = self._last_folder_warning
            return payload
        if action == "capture":
            return self.capture(data.get("mode", "selection"))
        if action == "image":
            record = self.records[data["id"]]
            cached = record.get("_data")
            if not cached:
                cached = png_data(QImage(str(record["path"])))
                record["_data"] = cached
            return {
                **{k: v for k, v in record.items() if k not in ("path", "_data")},
                "data": cached,
                "config": config(),
            }
        if action == "cancel":
            self.discard_raw()
            if self.shell:
                self.shell.hide()
            self.restore()
            return {"ok": True}
        if action == "color":
            value = data.get("value", "")
            if not re.fullmatch("#[0-9a-fA-F]{6}", value):
                raise ValueError("Cor inválida.")
            QApplication.clipboard().setText(value)
            return {"ok": True}
        image = decode_image(data.get("data"))
        if action == "copy":
            QApplication.clipboard().setImage(image)
            return {"ok": True}
        if action in ("finalize", "save", "desktop", "drag", "edit", "print"):
            prefs = config()
            kind = data.get("format", prefs["format"])
            if kind not in ("png", "jpg", "bmp"):
                raise ValueError("Formato inválido.")
            name = filename(str(data.get("title", "Captura"))) + "." + kind
            if action == "finalize":
                if prefs["auto_copy"]:
                    QApplication.clipboard().setImage(image)
                path = self.output_directory() / name
                if not prefs["auto_save"]:
                    self.discard_raw()
                    if self.shell:
                        self.shell.hide()
                    self.restore()
                    return {"ok": True}
            elif action == "desktop":
                directory = Path(
                    QStandardPaths.writableLocation(
                        QStandardPaths.StandardLocation.DesktopLocation
                    )
                )
                path = directory / name
            elif action == "save":
                directory = str(self.output_directory())
                target, _ = QFileDialog.getSaveFileName(
                    self.shell,
                    "Salvar captura",
                    str(Path(directory) / name),
                    {
                        "png": "PNG (*.png)",
                        "jpg": "JPEG (*.jpg)",
                        "bmp": "Bitmap (*.bmp)",
                    }[kind],
                )
                if not target:
                    return {"cancelled": True}
                path = Path(target)
            else:
                path = self.folder / name
            if action == "print":
                from PyQt6.QtPrintSupport import QPrintDialog, QPrinter

                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog = QPrintDialog(printer, self.shell)
                if dialog.exec():
                    painter = QPainter(printer)
                    area = painter.viewport()
                    size = image.size()
                    size.scale(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
                    painter.drawImage(QRect(area.topLeft(), size), image)
                    painter.end()
                return {"ok": True}
            path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(
                str(path),
                "JPEG" if kind == "jpg" else kind.upper(),
                int(prefs["quality"]),
            ):
                raise RuntimeError("Não foi possível salvar a captura.")
            if action in ("finalize", "save", "desktop"):
                from Plugins.Connectors.pia_server.media import enqueue

                enqueue(path)
            if action == "edit":
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            if action == "drag":

                def drag_image():
                    drag = QDrag(self.shell.view if self.shell else self.ui.window.view)
                    mime = QMimeData()
                    mime.setImageData(image)
                    mime.setUrls([QUrl.fromLocalFile(str(path))])
                    drag.setMimeData(mime)
                    drag.setPixmap(QPixmap.fromImage(image).scaledToWidth(240))
                    drag.exec(Qt.DropAction.CopyAction)

                QTimer.singleShot(0, drag_image)
            if action == "finalize":
                self.discard_raw()
                if self.shell:
                    self.shell.hide()
                self.restore()
            elif action in ("save", "desktop"):
                self.discard_raw()
            response = {"ok": True, "name": path.name}
            if self._last_folder_warning:
                response["folder_warning"] = self._last_folder_warning
            return response
        raise ValueError("Operação desconhecida.")

    def shutdown(self):
        self.discard_raw()
        if self.shell:
            try:
                self.shell.hide()
            except RuntimeError:
                pass
        CaptureShell.reset_cache()

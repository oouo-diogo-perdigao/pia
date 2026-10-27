"""Native Mini controls: dragging, hover cooldown and a focus-safe HTML composer."""
import ctypes
import math
import sys
import time
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QTimer, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QRegion
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget


class _XRectangle(ctypes.Structure):
    _fields_ = (
        ('x', ctypes.c_short),
        ('y', ctypes.c_short),
        ('width', ctypes.c_ushort),
        ('height', ctypes.c_ushort),
    )


class _ClickThrough:
    """Empty X input shape: Wayland delivers the click to the window below.

    The shape is filled only for a few milliseconds so the overlay can receive
    Enter. Mutter does not deliver pointer events while the shape is empty, and
    the X cursor then stays frozen inside the window.
    """

    def __init__(self):
        self.x11 = ctypes.CDLL('libX11.so.6')
        self.ext = ctypes.CDLL('libXext.so.6')
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XQueryPointer.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.x11.XQueryPointer.restype = ctypes.c_int
        self.ext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(_XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        self.display = self.x11.XOpenDisplay(None)
        self.root = self.x11.XDefaultRootWindow(self.display) if self.display else 0

    def _combine(self, window, full, width, height):
        if not self.display or not window:
            return
        if full:
            rect = _XRectangle(0, 0, max(1, width), max(1, height))
            self.ext.XShapeCombineRectangles(self.display, window, 2, 0, 0, ctypes.byref(rect), 1, 0, 0)
        else:
            self.ext.XShapeCombineRectangles(self.display, window, 2, 0, 0, None, 0, 0, 0)

    def receive_hover(self, widget):
        if not self.display:
            return
        ratio = widget.devicePixelRatio()
        self._combine(int(widget.winId()), True, int(widget.width() * ratio), int(widget.height() * ratio))
        self.x11.XSync(self.display, 0)

    def pass_clicks(self, widget):
        if not self.display:
            return
        self._combine(int(widget.winId()), False, 0, 0)
        self.x11.XFlush(self.display)

    def pointer(self):
        if not self.display:
            pos = QCursor.pos()
            return pos.x(), pos.y(), 0
        root = ctypes.c_ulong()
        child = ctypes.c_ulong()
        rx, ry = ctypes.c_int(), ctypes.c_int()
        wx, wy = ctypes.c_int(), ctypes.c_int()
        mask = ctypes.c_uint()
        self.x11.XQueryPointer(
            self.display, self.root, ctypes.byref(root), ctypes.byref(child),
            ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask),
        )
        return rx.value, ry.value, mask.value

    def button_down(self):
        return bool(self.pointer()[2] & 0x1F00)

    def input_boxes(self, widget, boxes):
        if not self.display:
            return
        window = int(widget.winId()) if widget.winId() else 0
        if not window:
            return
        ratio = widget.devicePixelRatio()
        if not boxes:
            self.ext.XShapeCombineRectangles(self.display, window, 2, 0, 0, None, 0, 0, 0)
        else:
            rects = (_XRectangle * len(boxes))()
            for index, box in enumerate(boxes):
                rects[index] = _XRectangle(
                    int(box.x() * ratio), int(box.y() * ratio),
                    max(1, int(box.width() * ratio)), max(1, int(box.height() * ratio)),
                )
            self.ext.XShapeCombineRectangles(self.display, window, 2, 0, 0, rects, len(boxes), 0, 0)
        self.x11.XFlush(self.display)


class HoverBlink:
    def __init__(self):
        self.inside = False
        self.last = -5.0

    def update(self, inside, now):
        should = inside and not self.inside and now - self.last >= 5
        self.inside = inside
        if should:
            self.last = now
        return should


def _pop(t):
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    c1 = 1.12
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _mix(a, b, t):
    return QPoint(int(a.x() + (b.x() - a.x()) * t), int(a.y() + (b.y() - a.y()) * t))


def _paint_disc(widget):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = widget._scale * (1.07 if widget._hover else 1.0)
    cx, cy = widget.width() / 2, widget.height() / 2
    painter.translate(cx, cy)
    painter.scale(scale, scale)
    painter.translate(-cx, -cy)
    rect = QRectF(1.3, 1.3, widget.width() - 2.6, widget.height() - 2.6)
    painter.setPen(QPen(QColor(255, 255, 255, 220), 1.35))
    painter.setBrush(QColor('#6d4ea8') if widget._hover else QColor(28, 22, 40, 242))
    painter.drawEllipse(rect)
    pen = QPen(QColor('#f6f1ff'), 1.65)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _stroke_icon(painter, widget.kind, rect.center())
    painter.end()


def _stroke_icon(painter, kind, c):
    if kind == 'message':
        painter.drawRoundedRect(QRectF(c.x() - 7.5, c.y() - 6.5, 15, 10.5), 3, 3)
        tail = QPainterPath()
        tail.moveTo(c.x() - 2.2, c.y() + 3.6)
        tail.lineTo(c.x() - 5.4, c.y() + 7.4)
        tail.lineTo(c.x() + 1.4, c.y() + 3.6)
        painter.drawPath(tail)
    elif kind == 'mic':
        painter.drawRoundedRect(QRectF(c.x() - 3.1, c.y() - 8, 6.2, 9.4), 3.1, 3.1)
        painter.drawArc(QRectF(c.x() - 6.2, c.y() - 4.2, 12.4, 9.2), 206 * 16, 128 * 16)
        painter.drawLine(QPointF(c.x(), c.y() + 5), QPointF(c.x(), c.y() + 8))
        painter.drawLine(QPointF(c.x() - 3.6, c.y() + 8), QPointF(c.x() + 3.6, c.y() + 8))
    elif kind == 'expand':
        s, arm = 6.4, 3.6
        for x, y, dx, dy in ((-s, -s, 1, 1), (s, -s, -1, 1), (-s, s, 1, -1), (s, s, -1, -1)):
            painter.drawLine(QPointF(c.x() + x, c.y() + y), QPointF(c.x() + x + dx * arm, c.y() + y))
            painter.drawLine(QPointF(c.x() + x, c.y() + y), QPointF(c.x() + x, c.y() + y + dy * arm))
    elif kind == 'hide':
        eye = QPainterPath()
        eye.moveTo(c.x() - 8, c.y())
        eye.quadTo(c.x(), c.y() - 5.6, c.x() + 8, c.y())
        eye.quadTo(c.x(), c.y() + 5.6, c.x() - 8, c.y())
        painter.drawPath(eye)
        painter.drawEllipse(QRectF(c.x() - 1.8, c.y() - 1.8, 3.6, 3.6))
        painter.drawLine(QPointF(c.x() - 7, c.y() + 5.5), QPointF(c.x() + 7, c.y() - 5.5))
    else:
        painter.setBrush(QColor('#f6f1ff'))
        painter.setPen(Qt.PenStyle.NoPen)
        for col in (-2.3, 2.3):
            for row in (-5, 0, 5):
                painter.drawEllipse(QRectF(c.x() + col - 1.45, c.y() + row - 1.45, 2.9, 2.9))


class _RoundButton(QPushButton):
    def __init__(self, kind, tooltip, callback, parent):
        super().__init__(parent)
        self.kind = kind
        self._scale = 1.0
        self._hover = False
        self.setFixedSize(RadialMenu.BUTTON, RadialMenu.BUTTON)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFlat(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.clicked.connect(callback)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        _paint_disc(self)


class DragHandle(QWidget):
    def __init__(self, controls, parent):
        super().__init__(parent)
        self.controls = controls
        self.kind = 'move'
        self._scale = 1.0
        self._hover = False
        self.start = None
        self.setFixedSize(RadialMenu.DRAG, RadialMenu.DRAG)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip('Mover')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        _paint_disc(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.globalPosition().toPoint()
            self.original = self.controls.overlay.pos()
            self.controls.dragging = True
            self.grabMouse()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.controls.move_to(self.original + event.globalPosition().toPoint() - self.start)

    def mouseReleaseEvent(self, event):
        if self.start is not None:
            self.start = None
            self.controls.dragging = False
            self.releaseMouse()
            point = self.controls.overlay.pos()
            self.controls.ui.service.store.set('mini:position', [point.x(), point.y()])


class RadialMenu(QWidget):
    """Four action discs plus a smaller move grip, on a semicircle around the mini."""

    BUTTON = 44
    DRAG = 34
    RADIUS = 112
    SPREAD = 168
    SPAN = 320

    def __init__(self, controls):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(controls.overlay, flags)
        self.controls = controls
        self.setWindowTitle('PIA Mini')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFixedSize(self.SPAN, self.SPAN)
        self._progress = 0.0
        self._closing = False
        self._targets = []
        self._anchor = QPoint(self.SPAN // 2, self.SPAN // 2)
        ui = controls.ui
        self.buttons = [
            _RoundButton('message', 'Mensagem', self._bind(ui.open_composer), self),
            _RoundButton('mic', 'Microfone', self._bind(ui.microphone), self),
            _RoundButton('expand', 'Expandir', self._bind(lambda: ui.set_main_visible(True)), self),
            _RoundButton('hide', 'Ocultar', self._bind(lambda: ui.set_mini_visible(False)), self),
        ]
        self.handle = DragHandle(controls, self)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._apply)
        self._anim.finished.connect(self._finished)

    def _bind(self, fn):
        def run():
            self.controls._suppress_until = time.monotonic() + 0.8
            self.collapse()
            fn()
        return run

    def _widgets(self):
        return [self.buttons[0], self.buttons[1], self.handle, self.buttons[2], self.buttons[3]]

    def hits(self, point):
        return any(widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(point))
                   for widget in self._widgets())

    def hovered(self):
        return any(widget.underMouse() for widget in self._widgets())

    def place(self):
        screen_widget = self.controls.overlay.screen()
        if screen_widget is None:
            return
        overlay = self.controls.overlay.frameGeometry()
        screen = screen_widget.availableGeometry()
        center = overlay.center()
        half = self.SPAN // 2
        self.move(center.x() - half, center.y() - half)
        self._anchor = QPoint(half, half)
        self._targets = self._layout(self._mid_angle(center, screen))
        self._apply(self._progress)

    def _stop_anim(self):
        self._anim.blockSignals(True)
        self._anim.stop()
        self._anim.blockSignals(False)

    def expand(self):
        self._closing = False
        self._stop_anim()
        self.place()
        self.show()
        self.raise_()
        self._anim.setDuration(360)
        self._anim.setStartValue(self._progress if self._progress > 0 else 0.01)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def collapse(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self._stop_anim()
        self._anim.setDuration(160)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def hideEvent(self, event):
        self._stop_anim()
        self._progress = 0.0
        self._closing = False
        super().hideEvent(event)

    def _finished(self):
        if self._closing:
            self.hide()

    def _layout(self, mid):
        widgets = self._widgets()
        step = self.SPREAD / (len(widgets) - 1)
        targets = []
        for index, widget in enumerate(widgets):
            angle = math.radians(mid + self.SPREAD / 2 - step * index)
            size = widget.width()
            radius = self.RADIUS - (self.BUTTON - size) / 2
            targets.append(QPoint(
                int(self._anchor.x() + math.cos(angle) * radius - size / 2),
                int(self._anchor.y() - math.sin(angle) * radius - size / 2),
            ))
        return targets

    def _mid_angle(self, center, screen):
        half = self.SPAN // 2
        origin = QPoint(center.x() - half, center.y() - half)
        room = sorted((
            (center.y() - screen.top(), 90),
            (center.x() - screen.left(), 180),
            (screen.right() - center.x(), 0),
            (screen.bottom() - center.y(), 270),
        ), reverse=True)
        order = [90] + [angle for _, angle in room if angle != 90]
        for base in order:
            if base == 90 and center.y() - screen.top() < 130:
                continue
            for shift in range(0, 150, 6):
                for delta in ((0,) if shift == 0 else (shift, -shift)):
                    mid = (base + delta) % 360
                    if self._fits(mid, origin, screen):
                        return mid
        return room[0][1]

    def _fits(self, mid, origin, screen):
        safe = screen.adjusted(4, 4, -4, -4)
        widgets = self._widgets()
        step = self.SPREAD / (len(widgets) - 1)
        for index, widget in enumerate(widgets):
            angle = math.radians(mid + self.SPREAD / 2 - step * index)
            size = widget.width()
            radius = self.RADIUS - (self.BUTTON - size) / 2
            rect = QRect(
                int(origin.x() + self.SPAN / 2 + math.cos(angle) * radius - size / 2),
                int(origin.y() + self.SPAN / 2 - math.sin(angle) * radius - size / 2),
                size, size,
            )
            if not safe.contains(rect):
                return False
        return True

    def _apply(self, value):
        if not self._targets:
            return
        progress = max(0.0, min(1.0, float(value)))
        self._progress = progress
        widgets = self._widgets()
        center_index = widgets.index(self.handle)
        for index, (widget, target) in enumerate(zip(widgets, self._targets)):
            if self._closing:
                eased = progress
            else:
                delay = abs(index - center_index) * 0.07
                eased = _pop(max(0.0, min(1.0, (progress - delay) / (1 - 0.14))))
            size = widget.width()
            start = QPoint(self._anchor.x() - size // 2, self._anchor.y() - size // 2)
            widget.move(_mix(start, target, eased))
            widget._scale = 0.12 + 0.88 * max(0.0, eased)
            widget.setVisible(eased > 0.03)
            widget.update()
        self._update_mask()

    def _update_mask(self):
        region = QRegion()
        for widget in self._widgets():
            if widget.isVisible():
                region = region.united(QRegion(widget.geometry(), QRegion.RegionType.Ellipse))
        boxes = [widget.geometry() for widget in self._widgets() if widget.isVisible()]
        if region.isEmpty():
            region = QRegion(self._anchor.x(), self._anchor.y(), 1, 1)
        self.setMask(region)
        clicks = getattr(self.controls, '_clicks', None)
        if clicks is not None and self.isVisible():
            clicks.input_boxes(self, boxes)


class MiniControls(QObject):
    def __init__(self, ui):
        super().__init__(ui.overlay)
        self.ui, self.overlay = ui, ui.overlay
        self.dragging = False
        self.blink = HoverBlink()
        self._pointer_inside = False
        self._probe_pending = False
        self._probe_hit = False
        self._suppress_until = 0.0
        self._clicks = _ClickThrough() if sys.platform != 'win32' else None
        self.menu = RadialMenu(self)
        self.handle = self.menu.handle
        saved = ui.service.store.get('mini:position')
        if saved:
            self.move_to(QPoint(*saved))
        self.timer = QTimer(self.menu)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.top_timer = QTimer(self.menu)
        self.top_timer.timeout.connect(self.keep_on_top)
        self.top_timer.start(900)
        if sys.platform != 'win32':
            self._hide_timer = QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.setInterval(280)
            self._hide_timer.timeout.connect(self._hide_if_left)
            self.overlay.setMouseTracking(True)
            self.overlay.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self._watch(self.overlay)
            self._watch(self.overlay.view)
            self._watch(self.menu)
            for child in self.menu.findChildren(QWidget):
                self._watch(child)

    def nearby(self, size):
        rect = self.overlay.frameGeometry()
        screen = self.overlay.screen().availableGeometry()
        x = max(screen.left(), min(rect.right() - size.width(), screen.right() - size.width()))
        y = rect.top() - size.height() - 6
        if y < screen.top():
            y = min(rect.bottom() + 6, screen.bottom() - size.height())
        return QPoint(x, y)

    def move_to(self, point):
        screen = QApplication.screenAt(point) or self.overlay.screen()
        rect = screen.availableGeometry()
        self.overlay.move(max(rect.left(), min(point.x(), rect.right() - self.overlay.width())),
                          max(rect.top(), min(point.y(), rect.bottom() - self.overlay.height())))
        self.menu.place()
        if hasattr(self.ui, 'composer') and self.ui.composer.isVisible():
            self.ui.composer.move(self.nearby(self.ui.composer.size()))

    def _watch(self, widget):
        widget.setMouseTracking(True)
        widget.installEventFilter(self)

    def _on_menu(self, watched):
        widget = watched
        while widget is not None:
            if widget is self.menu:
                return True
            widget = widget.parentWidget() if hasattr(widget, 'parentWidget') else None
        return False

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            if not self._on_menu(watched) and self._probe_pending:
                self._probe_hit = True
            if kind in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                if self._on_menu(watched) and not self.dragging and time.monotonic() >= self._suppress_until:
                    self._pointer_inside = True
                    self._hide_timer.stop()
                return False
            if time.monotonic() < self._suppress_until or self.dragging:
                return False
            self._pointer_inside = True
            self._hide_timer.stop()
            if not self.ui.composer.isVisible() and self.overlay.isVisible():
                self._present_menu()
        elif kind in (QEvent.Type.Leave, QEvent.Type.HoverLeave) and self._on_menu(watched):
            if not self.dragging and not self._hide_timer.isActive():
                self._hide_timer.start()
        elif kind == QEvent.Type.MouseButtonPress and self._on_menu(watched):
            self._hide_timer.stop()
        elif kind == QEvent.Type.MouseButtonPress and not self._on_menu(watched):
            self._clicks.pass_clicks(self.overlay)
            return True
        elif kind == QEvent.Type.Show and watched is self.overlay:
            QTimer.singleShot(0, lambda: self._clicks.pass_clicks(self.overlay))
        return False

    def _hide_if_left(self):
        self._pointer_inside = False
        if not self.dragging and not self.menu.hovered():
            self.menu.collapse()

    def _present_menu(self):
        if time.monotonic() < self._suppress_until or self.ui.composer.isVisible() or not self.overlay.isVisible():
            return
        if self.menu.isVisible() and not self.menu._closing:
            self.menu.place()
            self.menu.raise_()
            return
        self.menu.expand()

    def tick(self):
        if not self.overlay.isVisible():
            self._pointer_inside = False
            self.menu.hide()
            self.blink.update(False, time.monotonic())
            return
        if sys.platform != 'win32':
            self._probe_hover()
            return
        cursor = QCursor.pos()
        inside = self.overlay.frameGeometry().contains(cursor)
        if self.blink.update(inside, time.monotonic()):
            self.overlay.blink()
        if self.dragging or self.ui.composer.isVisible():
            if self.ui.composer.isVisible() and self.menu.isVisible():
                self.menu.collapse()
            return
        if inside or self.menu.hits(cursor):
            self._present_menu()
        elif self.menu.isVisible():
            self.menu.collapse()

    def _probe_hover(self):
        if self._probe_pending or self.dragging:
            return
        if self.ui.composer.isVisible():
            if self.menu.isVisible():
                self.menu.collapse()
            self._clicks.pass_clicks(self.overlay)
            return
        if self._clicks.button_down():
            self._clicks.pass_clicks(self.overlay)
            return
        self._probe_hit = False
        self._clicks.receive_hover(self.overlay)
        self._probe_pending = True
        QTimer.singleShot(28, self._finish_probe)

    def _finish_probe(self):
        self._probe_pending = False
        if not self.overlay.isVisible():
            self._clicks.pass_clicks(self.overlay)
            return
        over_overlay = self._probe_hit
        over_menu = self.menu.hovered()
        self._clicks.pass_clicks(self.overlay)
        if self.blink.update(over_overlay, time.monotonic()):
            self.overlay.blink()
        if self.dragging:
            return
        if self.ui.composer.isVisible():
            if self.menu.isVisible():
                self.menu.collapse()
            return
        if over_overlay or over_menu:
            self._pointer_inside = True
            self._hide_timer.stop()
            if time.monotonic() >= self._suppress_until:
                self._present_menu()
        elif self._pointer_inside:
            self._suppress_until = 0.0
            if not self._hide_timer.isActive():
                self._hide_timer.start()

    def keep_on_top(self):
        if not self.overlay.isVisible():
            return
        self.overlay.raise_()
        if self.menu.isVisible():
            self.menu.raise_()
        if self._clicks is not None and not self._probe_pending:
            self._clicks.pass_clicks(self.overlay)
        if sys.platform == 'win32':
            ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(int(self.overlay.winId())), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0013)

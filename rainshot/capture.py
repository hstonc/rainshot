"""X11 capture and asynchronous, race-safe XDG Screenshot portal requests."""
import os
import uuid
from urllib.parse import urlparse, unquote
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer, Qt, QPoint, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QCursor
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher, QDBusPendingReply, QDBusVariant
from .imaging import ScreenTile, compose_tiles, load_image

SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST = "org.freedesktop.portal.Request"


def is_wayland():
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY")) or QApplication.platformName().startswith("wayland")


def portal_file(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("截图服务返回了非本地文件地址。")
    if parsed.query or parsed.fragment:
        raise ValueError("截图服务返回的文件地址无效。")
    path = unquote(parsed.path)
    if not os.path.isabs(path):
        raise ValueError("截图服务返回的路径无效。")
    return path


class PortalCapture(QObject):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    canceled = pyqtSignal()

    def __init__(self, parent=None, bus=None, timeout_ms=120000):
        super().__init__(parent)
        self.bus = bus or QDBusConnection.sessionBus()
        self.path = None
        self.watcher = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self._timeout)

    def start(self):
        if self.path:
            return
        if not self.bus.isConnected():
            self.failed.emit("无法连接桌面 D-Bus 会话，请从桌面用户会话启动rainshot。")
            return
        token = "rainshot_" + uuid.uuid4().hex
        sender = self.bus.baseService().lstrip(":").replace(".", "_")
        self.path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        # Subscribe BEFORE calling Screenshot: a fast response may precede the reply.
        if not self.bus.connect(SERVICE, self.path, REQUEST, "Response", self._response):
            self.path = None
            self.failed.emit("无法监听桌面截图服务。")
            return
        message = QDBusMessage.createMethodCall(SERVICE, PORTAL_PATH, "org.freedesktop.portal.Screenshot", "Screenshot")
        message.setArguments(["", {"handle_token": QDBusVariant(token), "interactive": QDBusVariant(True)}])
        self.watcher = QDBusPendingCallWatcher(self.bus.asyncCall(message), self)
        self.watcher.finished.connect(self._reply)
        self.timer.start()

    @pyqtSlot(QDBusPendingCallWatcher)
    def _reply(self, watcher):
        reply = QDBusPendingReply(watcher).reply()
        watcher.deleteLater()
        self.watcher = None
        if not self.path:
            return
        if reply.type() == QDBusMessage.ErrorMessage:
            self._cleanup()
            self.failed.emit("桌面截图服务不可用：" + reply.errorMessage() + "\nUbuntu Wayland 请检查 xdg-desktop-portal 与 xdg-desktop-portal-gnome 是否已安装。")
        elif reply.arguments():
            value = reply.arguments()[0]
            actual = value.path() if hasattr(value, "path") else str(value)
            if actual != self.path:
                self.bus.disconnect(SERVICE, self.path, REQUEST, "Response", self._response)
                self.path = actual
                self.bus.connect(SERVICE, actual, REQUEST, "Response", self._response)

    @pyqtSlot("uint", "QVariantMap")
    def _response(self, code, results):
        if not self.path:
            return
        self._cleanup()
        if code == 1:
            self.canceled.emit()
        elif code != 0:
            self.failed.emit("桌面环境未完成截图，请重新尝试。")
        else:
            try:
                uri = results.get("uri", "")
                if isinstance(uri, QDBusVariant):
                    uri = uri.variant()
                image = load_image(portal_file(str(uri)))
                # The returned path belongs to the portal; never delete it here.
                self.ready.emit(image)
            except (ValueError, OSError) as exc:
                self.failed.emit(str(exc))

    def _cleanup(self):
        self.timer.stop()
        if self.path:
            self.bus.disconnect(SERVICE, self.path, REQUEST, "Response", self._response)
        self.path = None

    def cancel(self):
        if self.path:
            message = QDBusMessage.createMethodCall(SERVICE, self.path, REQUEST, "Close")
            self.bus.asyncCall(message)
            self._cleanup()
            self.canceled.emit()

    def _timeout(self):
        if self.path:
            message = QDBusMessage.createMethodCall(SERVICE, self.path, REQUEST, "Close")
            self.bus.asyncCall(message)
        self._cleanup()
        self.failed.emit("等待截图确认超时。请检查桌面授权对话框后重试。")


def grab_tiles():
    if is_wayland():
        raise RuntimeError("Wayland 截图必须经过桌面授权服务。")
    if QApplication.platformName() != "xcb":
        raise RuntimeError("当前没有可用的 X11 桌面，无法进行真实屏幕截图。")
    tiles = []
    for screen in QApplication.screens():
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            raise RuntimeError("无法读取屏幕：" + screen.name())
        tiles.append(ScreenTile(screen.geometry(), pixmap.toImage()))
    if not tiles:
        raise RuntimeError("没有检测到屏幕。")
    return tiles


def desktop_rect(tiles):
    rect = QRect()
    for tile in tiles:
        rect = rect.united(tile.geometry)
    return rect


from .hints import corner_position
from .snap import SnapProbe


class SelectionOverlay(QWidget):
    selected = pyqtSignal(object, object)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, tiles, settings=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.settings = settings
        self.hint_dismissed = False
        self.tiles = tiles
        self.bounds = desktop_rect(tiles)
        self.start_point = None
        self.end_point = None
        self.selection = QRect()
        self.snap = SnapProbe(self)
        self.snap.ready_at.connect(self.snap_ready_at)
        self.snap.finished_at.connect(self.probe_finished)
        self.snap_rects = []
        self.snap_index = 0
        self.hover_point = None
        self.hover_window = None
        self.element_cache = {}
        self.last_probe = None
        self.retry_query = None
        self.retry_count = 0
        self.snap_choice = False
        self.snap_anchor = QRect()
        self.shift_held = False
        self.press_selection = QRect()
        self.snap_timer = QTimer(self)
        self.snap_timer.setSingleShot(True)
        self.snap_timer.setInterval(140)
        self.snap_timer.timeout.connect(self.request_hover)
        self.setGeometry(self.bounds)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.done = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update_hover(QCursor.pos())

    def snap_enabled(self):
        return (not self.shift_held and not QApplication.keyboardModifiers() & Qt.ShiftModifier
                and (self.settings is None or self.settings.value('smart_selection', True, type=bool)))

    def elements_enabled(self):
        return self.settings is None or self.settings.value('element_selection', True, type=bool)

    @staticmethod
    def window_key(window):
        if window is None:
            return None
        rect = window['rect']
        return (window['id'], window['pid'], rect.x(), rect.y(), rect.width(), rect.height())

    def update_candidates(self, preferred=None):
        position = self.hover_point
        window = self.snap.window_at(position)
        screen = next((tile.geometry for tile in self.tiles if tile.geometry.contains(position)), self.bounds)
        rects = self.element_cache.get(self.hover_window, []) if self.elements_enabled() else []
        candidates = sorted((r for r in rects if r.contains(position)), key=lambda r: r.width() * r.height())
        fallback = ([window['rect'].intersected(self.bounds)] if window else []) + [screen]
        for rect in fallback:
            if not rect.isEmpty() and rect.contains(position) and rect not in candidates:
                candidates.append(rect)
        self.snap_rects = candidates
        self.snap_index = candidates.index(preferred) if preferred in candidates else 0
        self.selection = (candidates[self.snap_index].translated(-self.bounds.topLeft())
                          if candidates else QRect())
        self.update()

    def update_hover(self, position):
        if self.done or self.start_point is not None:
            return
        self.hover_point = QPoint(position)
        if not self.snap_enabled():
            self.snap_timer.stop()
            self.snap.cancel()
            self.last_probe = None
            self.snap_choice = False
            self.snap_rects = []
            self.selection = QRect()
            self.update()
            return
        window = self.snap.window_at(position)
        key = self.window_key(window)
        preferred = self.selection.translated(self.bounds.topLeft())
        if key != self.hover_window:
            self.snap.cancel()
            self.snap_choice = False
            self.last_probe = None
        elif self.snap_choice and not self.snap_anchor.contains(position):
            self.snap_choice = False
        self.hover_window = key
        self.update_candidates(preferred if self.snap_choice else None)
        if self.elements_enabled() and window and window['pid'] and not self.snap_choice:
            # Keep an in-flight hit test alive while the pointer moves in this window.
            self.snap_timer.start(140)
        else:
            self.snap_timer.stop()
            if not self.elements_enabled():
                self.snap.cancel()
                self.last_probe = None

    def request_hover(self):
        if self.done or self.start_point is not None or not self.snap_enabled() or not self.elements_enabled():
            return
        if self.snap_choice or self.snap.is_busy() or self.hover_point is None:
            return
        query = (self.hover_window, self.hover_point.x(), self.hover_point.y())
        if query == self.last_probe:
            if query != self.retry_query or self.retry_count >= 1:
                return
            self.retry_count += 1
        else:
            self.retry_query = None
            self.retry_count = 0
        self.last_probe = query
        self.snap.request(QPoint(self.hover_point))

    def snap_ready_at(self, point, rects):
        if self.done or self.start_point is not None or not self.snap_enabled() or not self.elements_enabled():
            return
        window = self.snap.window_at(point)
        if self.window_key(window) != self.hover_window or window is None:
            return
        visible = window['rect'].intersected(self.bounds)
        rects = [r.intersected(visible) for r in rects]
        rects = [r for r in rects if r.contains(point) and r.width() > 6 and r.height() > 6]
        query = (self.window_key(window), point.x(), point.y())
        if query == self.last_probe:
            self.retry_query = query if not any(r != visible for r in rects) else None
        cached = list(rects)
        for rect in self.element_cache.get(self.hover_window, []):
            if rect not in cached:
                cached.append(rect)
        if self.hover_window not in self.element_cache and len(self.element_cache) >= 8:
            del self.element_cache[next(iter(self.element_cache))]
        self.element_cache[self.hover_window] = cached[:128]
        preferred = self.selection.translated(self.bounds.topLeft()) if self.snap_choice else None
        self.update_candidates(preferred)

    def probe_finished(self, point):
        if (not self.done and self.start_point is None and self.snap_enabled() and self.elements_enabled()
                and self.hover_point is not None and not self.snap_choice):
            if point != self.hover_point:
                self.snap_timer.start(140)
            elif self.retry_query == self.last_probe and self.retry_count < 1:
                # A browser/toolkit may publish its tree just after the first
                # probe. Retry once while stationary, with no endless polling.
                self.snap_timer.start(450)

    def paintEvent(self, event):
        painter = QPainter(self)
        for tile in self.tiles:
            painter.drawImage(tile.geometry.translated(-self.bounds.topLeft()), tile.image)
        painter.fillRect(self.rect(), QColor(8, 18, 26, 130))
        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            for tile in self.tiles:
                painter.drawImage(tile.geometry.translated(-self.bounds.topLeft()), tile.image)
            painter.restore()
            painter.setPen(QPen(QColor('#94a3ff'), 2))
            painter.drawRect(self.selection)
            label = f'{self.selection.width()} × {self.selection.height()}'
            if self.start_point is None and len(self.snap_rects) > 1:
                label += f' · 選區 {self.snap_index + 1}/{len(self.snap_rects)}'
            box = painter.fontMetrics().boundingRect(label).adjusted(-10, -6, 10, 6)
            box.moveTopLeft(QPoint(self.selection.x(), max(0, self.selection.y() - box.height() - 5)))
            painter.fillRect(box, QColor('#1b2338'))
            painter.setPen(Qt.white)
            painter.drawText(box, Qt.AlignCenter, label)
        if not self.hint_dismissed and (self.settings is None or self.settings.value('hints_enabled', True, type=bool)):
            label = '指向控件或元素間隙，點擊確認 · 拖曳自訂\nTab 切換範圍 · Shift 暫停吸附 · Esc 取消'
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            corner = self.settings.value('hint_corner', 'bottom-right') if self.settings is not None else 'bottom-right'
            box = painter.fontMetrics().boundingRect(QRect(0, 0, 360, 150), Qt.TextWordWrap, label).adjusted(-14, -10, 14, 10)
            box.moveTopLeft(corner_position(screen.availableGeometry(), box.size(), corner) - self.bounds.topLeft())
            painter.fillRect(box, QColor('#1b2338'))
            painter.setPen(Qt.white)
            painter.drawText(box.adjusted(14, 10, -14, -10), Qt.TextWordWrap | Qt.AlignVCenter, label)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.cancel()
        elif event.button() == Qt.LeftButton:
            self.snap_timer.stop()
            self.snap.cancel()
            self.press_selection = QRect(self.selection) if not event.modifiers() & Qt.ShiftModifier else QRect()
            self.hint_dismissed = True
            self.update()
            self.start_point = event.pos()
            self.selection = QRect()

    def mouseMoveEvent(self, event):
        if self.start_point is not None and event.buttons() & Qt.LeftButton:
            self.selection = QRect(self.start_point, event.pos()).normalized().intersected(self.rect())
            self.update()
        elif self.start_point is None:
            self.update_hover(event.globalPos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_point is not None:
            if (event.pos() - self.start_point).manhattanLength() <= 4 and not self.press_selection.isEmpty():
                self.selection = self.press_selection
            else:
                self.selection = QRect(self.start_point, event.pos()).normalized().intersected(self.rect())
            if self.selection.width() > 3 and self.selection.height() > 3:
                self.finish()
            else:
                self.start_point = None

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        global_point = event.globalPos()
        for tile in self.tiles:
            if tile.geometry.contains(global_point):
                self.selection = tile.geometry.translated(-self.bounds.topLeft())
                self.finish()
                return

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish()
        elif event.key() == Qt.Key_Tab and self.snap_rects and self.start_point is None:
            self.snap_timer.stop()
            self.snap.cancel()
            if not self.snap_choice:
                self.snap_anchor = self.selection.translated(self.bounds.topLeft())
            self.snap_choice = True
            self.snap_index = (self.snap_index + 1) % len(self.snap_rects)
            self.selection = self.snap_rects[self.snap_index].translated(-self.bounds.topLeft())
            self.update()
        elif event.key() == Qt.Key_Shift and self.start_point is None:
            self.shift_held = True
            self.snap_timer.stop()
            self.snap.cancel()
            self.last_probe = None
            self.snap_rects = []
            self.selection = QRect()
            self.update()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Shift:
            self.shift_held = False
            self.update_hover(QCursor.pos())
        else:
            super().keyReleaseEvent(event)

    def finish(self):
        if self.done or self.selection.width() < 2 or self.selection.height() < 2:
            return
        rect = self.selection.translated(self.bounds.topLeft())
        self.snap_timer.stop()
        self.snap.cancel()
        try:
            image = compose_tiles(self.tiles, rect)
        except ValueError as exc:
            self.done = True
            self.hide()
            self.failed.emit(str(exc))
            self.deleteLater()
            return
        self.done = True
        self.hide()
        self.selected.emit(image, rect)
        self.deleteLater()

    def cancel(self):
        if not self.done:
            self.snap_timer.stop()
            self.snap.cancel()
            self.done = True
            self.hide()
            self.canceled.emit()
            self.deleteLater()

"""Fast window fallback and cancellable, out-of-process accessibility probes."""
import json
import math
import sys
from PyQt5.QtCore import QObject, QProcess, QTimer, QPoint, QRect, pyqtSignal
from .x11 import X11


def native_point(position, logical_bounds, native_bounds):
    """Map Qt global coordinates using the selected window's physical extent."""
    return QPoint(native_bounds.x() + round((position.x() - logical_bounds.x()) *
                                            native_bounds.width() / logical_bounds.width()),
                  native_bounds.y() + round((position.y() - logical_bounds.y()) *
                                            native_bounds.height() / logical_bounds.height()))


def logical_rectangle(rect, logical_bounds, native_bounds):
    """Clip in physical space before converting back to the Qt window extent."""
    rect = rect.intersected(native_bounds)
    if rect.isEmpty():
        return QRect()
    sx = logical_bounds.width() / native_bounds.width()
    sy = logical_bounds.height() / native_bounds.height()
    left = math.floor((rect.x() - native_bounds.x()) * sx)
    top = math.floor((rect.y() - native_bounds.y()) * sy)
    right = math.ceil((rect.x() + rect.width() - native_bounds.x()) * sx)
    bottom = math.ceil((rect.y() + rect.height() - native_bounds.y()) * sy)
    return QRect(logical_bounds.x() + left, logical_bounds.y() + top,
                 right - left, bottom - top).intersected(logical_bounds)


class SnapProbe(QObject):
    ready = pyqtSignal(object)
    ready_at = pyqtSignal(object, object)
    finished_at = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        x11 = X11()
        try:
            self.windows = x11.windows()
        finally:
            x11.close()
        self.process = QProcess(self)
        self.process.finished.connect(self.complete)
        self.process.errorOccurred.connect(self.process_error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        # Importing AT-SPI and activating its desktop registry may be cold.
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.expire)
        self.bounds = QRect()
        self.point = None
        self._generation = 0
        self._active = None
        self._pending = None

    @property
    def active_point(self):
        context = self._pending or self._active
        if context and context['generation'] == self._generation:
            return QPoint(context['point'])
        return None

    def is_busy(self):
        return self.active_point is not None

    def window_at(self, position):
        return next((w for w in self.windows if w['rect'].contains(position)), None)

    def request(self, position):
        position = QPoint(position)
        window = self.window_at(position)
        if not window or not window['pid']:
            self.cancel()
            return
        if self.active_point == position:
            return
        self._generation += 1
        self.point, self.bounds = position, QRect(window['rect'])
        self._pending = {'generation': self._generation, 'point': position,
                         'bounds': QRect(window['rect']),
                         'native_bounds': QRect(window.get('native_rect', window['rect'])),
                         'pid': window['pid']}
        self.timer.stop()
        if self.process.state() != QProcess.NotRunning:
            # Retain only the newest pending request. Never block the GUI on
            # process teardown; an old finished signal cannot complete it.
            self.process.kill()
        else:
            self.start_pending()

    def start_pending(self):
        if not self._pending or self.process.state() != QProcess.NotRunning:
            return
        context, self._pending = self._pending, None
        self._active = context
        logical, native = context['bounds'], context['native_bounds']
        if logical.isEmpty() or native.isEmpty():
            self._active = None
            self.publish(context, [])
            return
        point = native_point(context['point'], logical, native)
        arguments = [context['pid'], point.x(), point.y(), native.x(), native.y(),
                     native.width(), native.height()]
        if self.process.isOpen():
            self.process.readAllStandardOutput()
            self.process.readAllStandardError()
        self.timer.start()
        self.process.start(sys.executable, ['-m', 'rainshot.accessible'] +
                           [str(value) for value in arguments])

    def complete(self, code, status):
        self.timer.stop()
        context, self._active = self._active, None
        output = bytes(self.process.readAllStandardOutput()) if self.process.isOpen() else b''
        if context and context['generation'] == self._generation:
            rects = self.parse(output, context) if code == 0 and status == QProcess.NormalExit else []
            self.publish(context, rects)
        self.start_pending()

    @staticmethod
    def parse(output, context):
        try:
            if len(output) > 65536:
                return []
            data = json.loads(output)
            if not isinstance(data, list) or len(data) > 128:
                return []
            rects = []
            for values in data:
                if (not isinstance(values, list) or len(values) != 4 or
                        any(type(value) is not int or abs(value) > 10000000 for value in values) or
                        values[2] <= 0 or values[3] <= 0):
                    continue
                rect = logical_rectangle(QRect(*values), context['bounds'], context['native_bounds'])
                if (rect.contains(context['point']) and rect.width() > 6 and
                        rect.height() > 6 and rect not in rects):
                    rects.append(rect)
            return sorted(rects, key=lambda rect: rect.width() * rect.height())
        except (ValueError, TypeError, ZeroDivisionError):
            return []

    def publish(self, context, rects):
        point = QPoint(context['point'])
        self.ready_at.emit(point, rects)
        self.ready.emit(rects)
        self.finished_at.emit(point)

    def process_error(self, error):
        # FailedToStart need not emit finished. Other failures finish normally.
        if error == QProcess.FailedToStart:
            self.complete(-1, QProcess.CrashExit)

    def expire(self):
        context = self._active
        if not context or context['generation'] != self._generation:
            return
        self._generation += 1
        self.timer.stop()
        self.process.kill()
        self.publish(context, [])

    def cancel(self):
        self._generation += 1
        self._pending = None
        self.timer.stop()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
        else:
            self._active = None
            if self.process.isOpen():
                self.process.readAllStandardOutput()

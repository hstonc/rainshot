"""Read desktop accessibility status; enable it only on an explicit request."""
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt5.QtDBus import (QDBusConnection, QDBusMessage, QDBusPendingCallWatcher,
                         QDBusPendingReply, QDBusVariant)

SERVICE = 'org.a11y.Bus'
PATH = '/org/a11y/bus'
STATUS = 'org.a11y.Status'
PROPERTIES = 'org.freedesktop.DBus.Properties'


class DesktopAccessibility(QObject):
    changed = pyqtSignal()
    enable_finished = pyqtSignal(bool)

    def __init__(self, parent=None, bus=None, timeout_ms=2500):
        super().__init__(parent)
        self.bus = bus if bus is not None else QDBusConnection.sessionBus()
        self.timeout_ms = timeout_ms
        self.enabled = None
        self.screen_reader_enabled = None
        self.error = ''
        self.pending = False
        self.enabling = False
        self._operation = None
        self._watcher = None

    def refresh(self):
        if self.pending:
            return False
        self._begin(False)
        self._read()
        return True

    def enable(self):
        if self.pending:
            return False
        self._begin(True)
        # IsEnabled allows applications to expose accessibility geometry.
        # ScreenReaderEnabled belongs to the user's screen reader: never set it.
        self._call('Set', [STATUS, 'IsEnabled', QDBusVariant(True)], 'enable')
        return True

    def _begin(self, enabling):
        self.error = ''
        self.pending = True
        self.enabling = enabling
        self.changed.emit()

    def _read(self):
        self._call('GetAll', [STATUS], 'verify' if self.enabling else 'refresh')

    def _call(self, method, arguments, operation):
        self._operation = operation
        if not self.bus.isConnected():
            self._finish('無法連接桌面的 D-Bus 服務，請從桌面使用者工作階段啟動 rainshot。')
            return
        message = QDBusMessage.createMethodCall(SERVICE, PATH, PROPERTIES, method)
        message.setArguments(arguments)
        try:
            self._watcher = QDBusPendingCallWatcher(
                self.bus.asyncCall(message, self.timeout_ms), self)
            self._watcher.finished.connect(self._reply)
        except (RuntimeError, TypeError) as exc:
            self._finish('無法存取桌面輔助功能：' + str(exc))

    @pyqtSlot(QDBusPendingCallWatcher)
    def _reply(self, watcher):
        if watcher is not self._watcher:
            watcher.deleteLater()
            return
        operation = self._operation
        reply = QDBusPendingReply(watcher).reply()
        self._watcher = None
        watcher.deleteLater()
        if reply.type() == QDBusMessage.ErrorMessage:
            action = {'refresh': '讀取狀態', 'enable': '啟用', 'verify': '確認啟用結果'}[operation]
            self._finish('無法' + action + '：' + reply.errorMessage())
            return
        if operation == 'enable':
            # A successful Set reply is not evidence the property took effect.
            self._read()
            return
        arguments = reply.arguments()
        values = arguments[0] if len(arguments) == 1 else None
        if not isinstance(values, dict):
            self._finish('桌面服務未提供有效的輔助功能狀態。')
            return
        enabled = values.get('IsEnabled')
        reader = values.get('ScreenReaderEnabled')
        enabled = enabled.variant() if isinstance(enabled, QDBusVariant) else enabled
        reader = reader.variant() if isinstance(reader, QDBusVariant) else reader
        if type(enabled) is not bool or ('ScreenReaderEnabled' in values and type(reader) is not bool):
            self._finish('桌面服務未提供有效的輔助功能狀態。')
            return
        self.enabled, self.screen_reader_enabled = enabled, reader
        self._finish('桌面尚未確認輔助功能已啟用，請重新嘗試。'
                     if operation == 'verify' and not enabled else '')

    def _finish(self, error=''):
        enabling = self.enabling
        self._operation = None
        self._watcher = None
        self.pending = self.enabling = False
        self.error = error
        self.changed.emit()
        if enabling:
            self.enable_finished.emit(not error and self.enabled is True)

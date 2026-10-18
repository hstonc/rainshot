"""Nonactivating corner messages outside the screenshot toolbar."""
from pathlib import Path
from PyQt5.QtCore import Qt, QTimer, QPoint, QSize, QObject, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QApplication

CORNERS = [('右下', 'bottom-right'), ('右上', 'top-right'), ('左下', 'bottom-left'), ('左上', 'top-left')]


def corner_position(available, size, corner, margin=22):
    x = available.left() + margin if corner.endswith('left') else available.right() - size.width() - margin + 1
    y = available.top() + margin if corner.startswith('top') else available.bottom() - size.height() - margin + 1
    return QPoint(x, y)


class CornerMessage(QFrame):
    dismissed = pyqtSignal()

    def __init__(self, owner, settings, anchor=None, corner=None):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.owner = owner
        self.settings = settings
        self.anchor = QPoint(anchor) if anchor is not None else None
        self.corner = corner
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet('QFrame {background:#1b2338;border:1px solid #6e7cab;border-radius:9px;}'
                           'QLabel {color:#edf0ff;border:none;font:12px "Noto Sans CJK TC";}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.label = QLabel()
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.tutorial = False
        self.action = None

    def present(self, text, tutorial=False, duration=6500, action=None):
        self.timer.stop()
        self.tutorial = tutorial
        self.action = action
        self.setAttribute(Qt.WA_TransparentForMouseEvents, action is None)
        # Qt copies this attribute into native flags only when creating a window.
        # Synchronize both so a previously click-through hint can accept a click.
        self.setWindowFlag(Qt.WindowTransparentForInput, action is None)
        self.setCursor(Qt.PointingHandCursor if action else Qt.ArrowCursor)
        if tutorial and self.settings is not None and not self.settings.value('hints_enabled', True, type=bool):
            self.hide()
            return
        if self.owner is not None and (self.owner.closing or self.owner.suspended or not self.owner.isVisible()):
            return
        self.label.setText(text)
        self.reposition()
        self.show()
        if duration:
            self.timer.start(duration)

    def reposition(self):
        anchor = (self.owner.surface.mapToGlobal(self.owner.surface.rect().center())
                  if self.owner is not None else self.anchor)
        screen = QApplication.screenAt(anchor) if anchor is not None else None
        available = (screen or QApplication.primaryScreen()).availableGeometry()
        self.setFixedWidth(min(400, available.width() - 44))
        height = self.layout().totalHeightForWidth(self.width())
        self.setFixedHeight(max(54, height))
        corner = self.corner or (self.settings.value('hint_corner', 'bottom-right')
                                 if self.settings is not None else 'bottom-right')
        self.move(corner_position(available, self.size(), corner))

    def dismiss(self):
        self.timer.stop()
        self.hide()
        self.action = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowTransparentForInput, True)
        self.setCursor(Qt.ArrowCursor)
        self.dismissed.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.action:
            action = self.action
            self.dismiss()
            action()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SavedNoticeManager(QObject):
    """Keep the current save notification alive after its screenshot is deleted."""
    def __init__(self, app):
        super().__init__(app)
        self.notice = None
        app.aboutToQuit.connect(self.clear)

    def show(self, text, anchor, corner, action=None, duration=6500):
        self.clear()
        notice = CornerMessage(None, None, anchor=anchor, corner=corner)
        self.notice = notice
        notice.dismissed.connect(lambda: self.release(notice))
        notice.present(text, action=action, duration=duration)
        return notice

    def release(self, notice):
        if self.notice is notice:
            self.notice = None
        notice.deleteLater()

    def clear(self):
        if self.notice is not None:
            self.notice.dismiss()

    def open_folder(self, folder, anchor, corner):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.show('無法開啟儲存資料夾，請檢查系統的預設檔案管理器。',
                      anchor, corner)


def saved_notice_manager():
    app = QApplication.instance()
    manager = getattr(app, '_rainshot_saved_notice_manager', None)
    if manager is None:
        manager = SavedNoticeManager(app)
        app._rainshot_saved_notice_manager = manager
    return manager


def create_save_notice(path, settings, anchor=None, duration=6500):
    path = Path(path).absolute()
    anchor = QPoint(anchor) if anchor is not None else None
    corner = settings.value('hint_corner', 'bottom-right')
    manager = saved_notice_manager()
    return manager.show('已儲存：' + path.name + ' · 點擊開啟資料夾', anchor, corner,
                        action=lambda: manager.open_folder(path.parent, anchor, corner),
                        duration=duration)

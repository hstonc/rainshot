"""Continuous viewport stitching: feature offsets, verified overlap, bounded workers."""
import numpy as np
from PyQt5.QtCore import QObject, QThread, QTimer, Qt, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QPixmap, QCursor
from PyQt5.QtWidgets import QApplication, QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from .imaging import rgb_array, compose_tiles
from .capture import grab_tiles
from .style import STYLE
from .x11 import X11
from .hotkeys import Hotkeys


def from_rgb(array):
    data = np.ascontiguousarray(array, dtype=np.uint8)
    return QImage(data.data, data.shape[1], data.shape[0], data.strides[0], QImage.Format_RGB888).copy()


class ScrollEngine:
    def __init__(self, image):
        self.last = rgb_array(image).copy()
        self.parts = self.last.copy()
        self.steps = 0

    def append(self, image):
        import cv2
        cv2.setNumThreads(1)
        current = rgb_array(image).copy()
        if current.shape != self.last.shape:
            raise ValueError('選區尺寸已改變，請結束這次長截圖。')
        h, w = current.shape[:2]
        ratio = min(1., 760 / w)
        gray = lambda a: cv2.resize(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), (max(16, round(w * ratio)), max(16, round(h * ratio))))
        first, second = gray(self.last), gray(current)
        if np.mean(np.abs(first.astype(float) - second.astype(float))) < .65:
            return 'unchanged', 0
        # Ignore narrow scrollbars and compositor borders.
        first[:, :4] = first[:, -10:] = 255
        second[:, :4] = second[:, -10:] = 255
        orb = cv2.ORB_create(nfeatures=3200, edgeThreshold=12, fastThreshold=10)
        ka, da = orb.detectAndCompute(first, None)
        kb, db = orb.detectAndCompute(second, None)
        if da is None or db is None:
            raise ValueError('內容特徵不足。請慢慢捲動，讓相鄰畫面保留至少一半重疊。')
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
        offsets = []
        for pair in matches:
            if len(pair) != 2 or pair[0].distance >= .72 * pair[1].distance:
                continue
            a, b = ka[pair[0].queryIdx].pt, kb[pair[0].trainIdx].pt
            if abs(a[0] - b[0]) <= 2.5:
                offsets.append((a[1] - b[1], a[1], a[0]))
        moving = [m for m in offsets if m[0] > 3]
        reverse = np.array([m[0] for m in offsets if m[0] < -3])
        if len(reverse) >= 7:
            reverse_bins = np.rint(-reverse / 3).astype(int)
            reverse_peak = np.bincount(reverse_bins).argmax() * 3
            reverse_count = np.sum(np.abs(reverse + reverse_peak) <= 3.5)
            if reverse_count > max(8, len(moving) * .6):
                return 'up', 0
        if len(moving) < 7:
            if sum(m[0] < -3 for m in offsets) >= 7:
                return 'up', 0
            raise ValueError('尚未找到可靠重疊；請捲回上一個已接合的位置，再小幅向下捲動。')
        candidates = np.array(moving)
        bins = np.rint(candidates[:, 0] / 3).astype(int)
        peak = np.bincount(bins).argmax() * 3
        inliers = candidates[np.abs(candidates[:, 0] - peak) <= 3.5]
        if len(inliers) < 7 or np.ptp(inliers[:, 1]) < first.shape[0] * .13:
            raise ValueError('重疊特徵不一致，請縮小每次捲動的距離。')
        estimated = round(float(np.median(inliers[:, 0])) / ratio)
        if estimated >= h * .82:
            raise ValueError('捲動過快；請捲回一些，保留至少 20% 的重疊內容。')
        # Refine the offset at original resolution; floating ORB coordinates can
        # otherwise lose a pixel per frame and accumulate visible seams.
        a = self.last.astype(np.int16)
        b = current.astype(np.int16)
        left, right = max(3, w // 30), w - max(12, w // 30)
        best = None
        for dy in range(max(1, estimated - 4), min(h - 10, estimated + 5)):
            delta = np.mean(np.abs(a[dy:, left:right:3] - b[:-dy, left:right:3]), axis=(1, 2))
            score = float(np.quantile(delta, .65))
            if best is None or (score, abs(dy - estimated)) < (best[0], abs(best[1] - estimated)):
                best = score, dy, float(np.mean(delta < 16))
        score, dy, good = best
        if score > 17 or good < .60:
            raise ValueError('畫面仍在變動或已失去重疊；先停一下，再捲回上一個位置重試。')
        # Verify ink/edges, not white space: repeated paragraphs with different
        # numbers can have a low whole-row error even when pages do not overlap.
        overlap = h - dy
        margin = min(h // 5, overlap // 4)
        old = self.last[dy + margin:h - margin, left:right]
        new = current[margin:overlap - margin, left:right]
        old_gray = cv2.cvtColor(old, cv2.COLOR_RGB2GRAY)
        new_gray = cv2.cvtColor(new, cv2.COLOR_RGB2GRAY)
        edges = (cv2.Canny(old_gray, 50, 120) > 0) | (cv2.Canny(new_gray, 50, 120) > 0)
        errors = np.mean(np.abs(old.astype(np.int16) - new.astype(np.int16)), axis=2)[edges]
        if errors.size < 100 or np.mean(errors < 18) < .91:
            raise ValueError('文字細節無法對齊，已保留上一段結果；請捲回一些再慢慢向下捲動。')
        # A stationary bottom strip is removed before extending, then reattached
        # once. This prevents sticky footers from being duplicated at every join.
        edge = np.mean(np.abs(a[:, left:right:3] - b[:, left:right:3]), axis=(1, 2))
        changing = np.flatnonzero(edge > 4)
        footer = h - int(changing[-1]) - 1 if changing.size else 0
        footer = min(footer, h // 4)
        if self.parts.shape[0] + dy > 32760 or (self.parts.shape[0] + dy) * w > 80_000_000:
            raise ValueError('已達長截圖上限（32,760 px / 8,000 萬像素），請完成並另開一張。')
        cut = self.parts.shape[0] - footer
        self.parts = np.concatenate([self.parts[:cut], current[h - footer - dy:]], axis=0)
        self.last = current
        self.steps += 1
        return 'added', dy

    def image(self):
        return from_rgb(self.parts)


class AppendWorker(QThread):
    result = pyqtSignal(str, int, object)
    failed = pyqtSignal(str)

    def __init__(self, engine, image, parent):
        super().__init__(parent)
        self.engine, self.frame = engine, image

    def run(self):
        try:
            state, offset = self.engine.append(self.frame)
            preview = self.engine.image().scaled(128, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation) if state == 'added' else None
            self.result.emit(state, offset, preview)
        except (ValueError, ImportError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('這一幀未能接合；請減慢捲動速度。')


class RegionFrame(QWidget):
    def __init__(self, region):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(region.adjusted(-3, -3, 3, 3))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(QColor('#a6b0ff'), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))


class SessionControls(QFrame):
    finishRequested = pyqtSignal()
    cancelRequested = pyqtSignal()

    def __init__(self, region, title, preview=False):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setStyleSheet(STYLE)
        self.setObjectName('card')
        self.setFixedWidth(380)
        self.box = QVBoxLayout(self)
        self.info = QLabel(title)
        self.info.setWordWrap(True)
        self.info.setMaximumWidth(340)
        self.box.addWidget(self.info)
        self.actions = QHBoxLayout()
        self.stop_button = QPushButton('完成')
        self.stop_button.setObjectName('primary')
        self.stop_button.clicked.connect(self.finishRequested)
        self.actions.addWidget(self.stop_button)
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.cancelRequested)
        self.actions.addWidget(cancel)
        self.box.addLayout(self.actions)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setVisible(preview)
        self.box.addWidget(self.preview)
        self.region = QRect(region)
        self.adjustSize()
        self.reposition()

    def reposition(self):
        self.adjustSize()
        screen = QApplication.screenAt(self.region.center()) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        # Prefer an adjacent monitor/space; no pixel of these controls enters
        # the recording or scroll image. Full-screen regions must be narrowed.
        candidates = [QPoint(self.region.right() + 32, self.region.top()),
                      QPoint(self.region.left() - self.width() - 32, self.region.top()),
                      QPoint(self.region.left(), self.region.bottom() + 32),
                      QPoint(self.region.left(), self.region.top() - self.height() - 32)]
        areas = [geo] + [s.availableGeometry() for s in QApplication.screens() if s != screen]
        for area in areas:
            for point in candidates + [area.topLeft() + QPoint(12, 12)]:
                rect = QRect(point, self.size())
                if area.contains(rect) and not rect.intersects(self.region.adjusted(-3, -3, 3, 3)):
                    self.move(point)
                    return True
        return False

    def closeEvent(self, event):
        event.ignore()
        self.cancelRequested.emit()


class SessionKeys(Hotkeys):
    def start(self, finish, cancel):
        self.activated.connect(lambda action: finish() if action == 'finish' else cancel())
        return self.apply({'finish': 'Ctrl+Return', 'cancel': 'Ctrl+Escape'})


class ScrollSession(QObject):
    completed = pyqtSignal(object)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, region, initial, parent=None):
        super().__init__(parent)
        self.region = QRect(region)
        self.engine = ScrollEngine(initial)
        self.worker = None
        self.stopping = None
        self.done = False
        self.no_change = 0
        self.inline_controls = False
        self.keys = SessionKeys(self)
        self.frame = RegionFrame(region)
        self.controls = SessionControls(region, '直接在原頁面向下捲動\n保留一半重疊；完成後按「完成」', True)
        self.controls.finishRequested.connect(self.finish)
        self.controls.cancelRequested.connect(self.cancel)
        self.auto = QPushButton('自動捲動')
        self.auto.setCheckable(True)
        self.auto.toggled.connect(self.auto_changed)
        self.controls.actions.insertWidget(0, self.auto)
        self.controls.preview.setPixmap(QPixmap.fromImage(initial.scaled(128, 260, Qt.KeepAspectRatio)))
        self.x11 = X11()
        windows = self.x11.windows()
        self.source_window = next((w['id'] for w in windows if w['rect'].contains(region.center())), None)
        self.timer = QTimer(self)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self.capture)
        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(600)
        self.auto_timer.timeout.connect(self.scroll_once)

    def start(self):
        key_error = self.keys.start(self.finish, self.cancel)
        if not self.controls.reposition():
            self.controls.preview.hide()
            if not self.controls.reposition():
                self.inline_controls = True
                self.controls.move(self.region.topRight() - QPoint(self.controls.width() + 12, -12))
                self.controls.info.setText('移開滑鼠開始擷取；移回右上角顯示按鈕並暫停擷取。')
        if not key_error:
            self.controls.stop_button.setText('完成 · Ctrl+Enter')
            self.controls.info.setText(self.controls.info.text() + '\nCtrl+Esc 取消')
        self.frame.show()
        self.controls.show()
        self.timer.start()

    def auto_changed(self, enabled):
        self.no_change = 0
        if enabled:
            self.controls.info.setText('將滑鼠移進選區開始自動捲動；移出即暫停。')
            self.auto_timer.start()
        else:
            self.auto_timer.stop()

    def scroll_once(self):
        if self.worker or self.stopping or not self.region.contains(QCursor.pos()):
            return
        # Do not send wheel events to a new window opened over the original page.
        under = next((w['id'] for w in self.x11.windows() if w['rect'].contains(QCursor.pos())), None)
        if under != self.source_window:
            self.auto.setChecked(False)
            self.controls.info.setText('前方視窗已改變，已暫停自動捲動。')
            return
        self.x11.wheel()

    def capture(self):
        if self.done or self.stopping or self.worker:
            return
        if self.inline_controls:
            if self.controls.geometry().contains(QCursor.pos()):
                self.controls.show()
                return
            if self.controls.isVisible():
                self.controls.hide()
                # Wait for the compositor to remove the panel before sampling.
                return
        try:
            image = compose_tiles(grab_tiles(), self.region)
            self.worker = AppendWorker(self.engine, image, self)
            self.worker.result.connect(self.accept)
            self.worker.failed.connect(self.rejected)
            self.worker.finished.connect(self.worker_finished)
            self.worker.start()
        except (ValueError, RuntimeError) as exc:
            self.rejected(str(exc))

    def accept(self, state, offset, preview):
        if self.done or self.stopping == 'cancel':
            return
        if state == 'added':
            self.no_change = 0
            self.controls.info.setText(f'已接合 {self.engine.steps} 次 · {self.engine.parts.shape[1]} × {self.engine.parts.shape[0]} px\n繼續向下捲動，或按完成。')
            self.controls.preview.setPixmap(QPixmap.fromImage(preview))
            if not self.inline_controls and not self.controls.reposition():
                self.controls.preview.hide()
                self.controls.reposition()
        elif state == 'up':
            self.controls.info.setText('已略過向上捲動；回到已截取的最下方後可繼續。')
        else:
            self.no_change += 1
            if self.auto.isChecked() and self.no_change > 10 and self.region.contains(QCursor.pos()):
                self.auto.setChecked(False)
                self.controls.info.setText('內容沒有繼續移動，已暫停自動捲動。可以按完成。')

    def rejected(self, message):
        self.auto.setChecked(False)
        self.controls.info.setText(message)

    def worker_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        if self.stopping:
            self.end()

    def finish(self):
        self.stop('finish')

    def cancel(self):
        self.stop('cancel')

    def stop(self, action):
        if self.done or self.stopping == 'cancel':
            return
        self.stopping = action
        self.timer.stop(); self.auto_timer.stop()
        self.controls.hide(); self.frame.hide()
        if not self.worker:
            self.end()

    def end(self):
        if self.done:
            return
        self.done = True
        self.keys.close()
        self.x11.close()
        self.controls.deleteLater(); self.frame.deleteLater()
        if self.stopping == 'finish':
            self.completed.emit(self.engine.image())
        else:
            self.canceled.emit()

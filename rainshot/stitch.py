"""Manual scroll capture and ordered image stitching with verified overlap."""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QScrollArea, QMessageBox)
from .imaging import stitch_pair, load_image


class StitchJob(QThread):
    result = pyqtSignal(object, int)
    failed = pyqtSignal(str)

    def __init__(self, first, second, parent=None):
        super().__init__(parent)
        self.first, self.second = QImage(first), QImage(second)

    def run(self):
        try:
            image, overlap = stitch_pair(self.first, self.second)
            self.result.emit(image, overlap)
        except (ValueError, MemoryError) as exc:
            self.failed.emit(str(exc) or "图片过大，内存不足。")


class StitchDialog(QDialog):
    captureRequested = pyqtSignal()
    editRequested = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, image=None, region=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("rainshot · 长截图")
        self.resize(720, 680)
        self.region = region
        self.image = None
        self.previous = None
        self.count = 0
        self.job = None
        self.pending = False
        self.completed = False
        layout = QVBoxLayout(self)
        heading = QLabel("把完整内容，留在一张图里。")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        help_text = ("向下滚动原页面，保留约一半重叠，再点击「追加截图」。\n"
                     "rainshot会隐藏窗口，2 秒后采集同一区域。选区请避开固定页头。" if region is not None else
                     "按从上到下的顺序逐张添加图片，每张保留约一半重叠。\n"
                     "仅支持竖向拼接；宽度、窗口尺寸和缩放比例需保持一致。")
        tip = QLabel(help_text)
        tip.setWordWrap(True)
        layout.addWidget(tip)
        row = QHBoxLayout()
        self.add_button = QPushButton("添加一张图片…")
        self.add_button.clicked.connect(self.add_file)
        row.addWidget(self.add_button)
        self.capture_button = QPushButton("追加截图（2 秒后）")
        self.capture_button.clicked.connect(self.request_capture)
        self.capture_button.setVisible(region is not None)
        row.addWidget(self.capture_button)
        self.undo_button = QPushButton("撤销上次拼接")
        self.undo_button.clicked.connect(self.undo)
        row.addWidget(self.undo_button)
        row.addStretch()
        layout.addLayout(row)
        self.preview = QLabel("添加第一张截图开始")
        self.preview.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview)
        layout.addWidget(scroll, 1)
        self.status = QLabel("尚未添加图片")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.edit_button = QPushButton("完成，进入编辑器")
        self.edit_button.setObjectName("primary")
        self.edit_button.clicked.connect(self.finish)
        layout.addWidget(self.edit_button)
        if image is not None:
            self.append(image)
        self.update_buttons()

    def set_busy(self, busy):
        self.pending = busy
        self.update_buttons()

    def update_buttons(self):
        busy = self.pending or (self.job is not None and self.job.isRunning())
        self.add_button.setEnabled(not busy)
        self.capture_button.setEnabled(not busy)
        self.edit_button.setEnabled(not busy and self.image is not None)
        self.undo_button.setEnabled(not busy and self.previous is not None)

    def request_capture(self):
        self.set_busy(True)
        self.captureRequested.emit()

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "添加下一张截图", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            try:
                self.append(load_image(path))
            except (ValueError, OSError) as exc:
                self.status.setText(str(exc))

    def append(self, image):
        if self.job and self.job.isRunning():
            return
        self.pending = False
        if self.image is None:
            self.image = image
            self.count = 1
            self.update_preview()
            return
        self.status.setText("正在核对重叠区域…")
        self.job = StitchJob(self.image, image, self)
        self.job.result.connect(self.accept_result)
        self.job.failed.connect(self.status.setText)
        self.job.finished.connect(self.job_finished)
        self.job.start()
        self.update_buttons()

    def job_finished(self):
        if self.job:
            self.job.deleteLater()
            self.job = None
        self.update_buttons()

    def accept_result(self, image, overlap):
        self.previous = self.image
        self.image = image
        self.count += 1
        self.update_preview()
        self.status.setText(f"已拼接 {self.count} 张 · 重叠 {overlap} px · {image.width()} × {image.height()} px")

    def update_preview(self):
        scaled = self.image.scaledToWidth(min(600, self.image.width()), Qt.SmoothTransformation)
        self.preview.setPixmap(QPixmap.fromImage(scaled))
        self.status.setText(f"{self.count} 张图片 · {self.image.width()} × {self.image.height()} px")
        self.update_buttons()

    def undo(self):
        if self.previous is not None:
            self.image = self.previous
            self.previous = None
            self.count -= 1
            self.update_preview()

    def finish(self):
        if self.image is not None:
            self.completed = True
            self.editRequested.emit(self.image)
            self.close()

    def closeEvent(self, event):
        if self.pending or (self.job and self.job.isRunning()):
            event.ignore()
            self.status.setText("正在采集或拼接，请稍候完成后关闭。")
            return
        self.closed.emit()
        event.accept()

    def reject(self):
        self.close()

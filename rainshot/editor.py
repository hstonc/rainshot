import math
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, QStandardPaths
from PyQt5.QtGui import QPainter, QPixmap, QColor, QKeySequence, QPen
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsPixmapItem, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QButtonGroup, QColorDialog, QSpinBox, QInputDialog, QFileDialog,
    QMessageBox, QShortcut, QFrame, QMenu)
from .imaging import Document, Mark, draw_mark, save_image, anchor_geometry


TOOLS = [("pan", "移动", "V"), ("rect", "矩形", "R"), ("ellipse", "椭圆", "E"),
         ("arrow", "箭头", "A"), ("line", "直线", "L"), ("pen", "画笔", "B"),
         ("highlight", "荧光", "H"), ("text", "文字", "T"), ("number", "序号", "N"),
         ("mosaic", "马赛克", "M"), ("redact", "遮盖", "D"), ("crop", "裁剪", "C")]


class PreviewMark(QGraphicsItem):
    def __init__(self, mark, bounds):
        super().__init__()
        self.mark = mark
        self.bounds = bounds
        self.setZValue(10)

    def boundingRect(self):
        return self.bounds

    def paint(self, painter, option, widget=None):
        if self.mark.kind in ("crop", "mosaic"):
            painter.setPen(QPen(QColor("#1ba78f"), 2, Qt.DashLine))
            painter.setBrush(QColor(27, 167, 143, 30))
            painter.drawRect(QRectF(QPointF(*self.mark.points[0]), QPointF(*self.mark.points[-1])).normalized())
        else:
            draw_mark(painter, self.mark)


class Canvas(QGraphicsView):
    changed = pyqtSignal()
    zoomChanged = pyqtSignal(float)

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.document = document
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene_obj.addItem(self.item)
        self.tool = "arrow"
        self.color = "#ef5b5b"
        self.stroke = 4
        self.points = []
        self.preview = None
        self.setBackgroundBrush(QColor("#e8eeed"))
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.refresh()

    def refresh(self):
        self.clear_preview()
        self.item.setPixmap(QPixmap.fromImage(self.document.render()))
        rect = self.item.boundingRect()
        self.setSceneRect(rect.adjusted(-rect.width(), -rect.height(), rect.width(), rect.height()))
        self.changed.emit()

    def fit_image(self):
        self.fitInView(self.item.boundingRect().adjusted(-28, -28, 28, 28), Qt.KeepAspectRatio)
        self.zoomChanged.emit(self.transform().m11())

    def actual_size(self):
        self.resetTransform()
        self.centerOn(self.item.boundingRect().center())
        self.zoomChanged.emit(1.0)

    def set_tool(self, tool):
        self.points = []
        self.clear_preview()
        self.tool = tool
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == "pan" else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.OpenHandCursor if tool == "pan" else Qt.CrossCursor)

    def zoom_at(self, pos, factor):
        old = self.mapToScene(pos)
        current = self.transform().m11()
        new = min(16.0, max(.03, current * factor))
        self.scale(new / current, new / current)
        after = self.mapToScene(pos)
        # Translate the floating-point transform instead of quantizing centerOn
        # through integer scroll bars. This avoids accumulating anchor drift.
        delta = after - old
        self.translate(delta.x(), delta.y())
        self.zoomChanged.emit(new)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            self.zoom_at(event.pos(), math.pow(1.0015, max(-480, min(480, delta))))
        event.accept()

    def image_point(self, pos):
        p = self.mapToScene(pos)
        r = self.item.boundingRect()
        return QPointF(max(0, min(r.width() - 1, p.x())), max(0, min(r.height() - 1, p.y())))

    def clear_preview(self):
        if self.preview:
            self.scene_obj.removeItem(self.preview)
            self.preview = None

    def mousePressEvent(self, event):
        if self.tool == "pan" or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if not self.item.boundingRect().contains(self.mapToScene(event.pos())):
            return
        p = self.image_point(event.pos())
        if self.tool == "text":
            value, ok = QInputDialog.getMultiLineText(self, "添加文字", "输入标注内容")
            if ok and value.strip():
                self.document.add(Mark("text", ((p.x(), p.y()),), self.color, self.stroke, value))
                self.refresh()
            return
        if self.tool == "number":
            number = 1 + sum(m.kind == "number" for m in self.document.marks)
            self.document.add(Mark("number", ((p.x(), p.y()),), self.color, self.stroke, str(number)))
            self.refresh()
            return
        self.points = [(p.x(), p.y())]

    def mouseMoveEvent(self, event):
        if not self.points or not event.buttons() & Qt.LeftButton:
            super().mouseMoveEvent(event)
            return
        p = self.image_point(event.pos())
        if self.tool in ("pen", "highlight"):
            if len(self.points) < 15000:
                self.points.append((p.x(), p.y()))
        else:
            self.points = [self.points[0], (p.x(), p.y())]
        self.clear_preview()
        mark = Mark(self.tool, tuple(self.points), self.color, self.stroke)
        self.preview = PreviewMark(mark, self.item.boundingRect())
        self.scene_obj.addItem(self.preview)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.points:
            p = self.image_point(event.pos())
            self.points.append((p.x(), p.y()))
            mark = Mark(self.tool, tuple(self.points), self.color, self.stroke)
            self.points = []
            self.clear_preview()
            if self.tool == "crop":
                self.document.crop(QRectF(QPointF(*mark.points[0]), p).normalized())
                self.refresh()
                self.fit_image()
            else:
                self.document.add(mark)
                self.refresh()
        super().mouseReleaseEvent(event)


class PinWindow(QWidget):
    """Draw the original image directly; no animations, timers or re-encoding on zoom."""
    def __init__(self, image, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.image = image
        self.drag = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("rainshot · 贴图")
        self.setToolTip("拖动移动 · 滚轮围绕鼠标缩放 · 双击恢复原尺寸 · 右键菜单 · Esc 关闭")
        screen = QApplication.primaryScreen().availableGeometry()
        factor = min(1, screen.width() * .7 / image.width(), screen.height() * .7 / image.height())
        self.resize(max(1, round(image.width() * factor)), max(1, round(image.height() * factor)))
        self.move(screen.center() - self.rect().center())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self.image)
        painter.setPen(QPen(QColor("#1ba78f"), 2))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.setWindowOpacity(min(1, max(.2, self.windowOpacity() + (.05 if event.angleDelta().y() > 0 else -.05))))
            return
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            return
        current = self.width() / self.image.width()
        longest = max(self.image.width(), self.image.height())
        scale = min(8, 16384 / longest, max(24 / longest, current * math.pow(1.0015, max(-480, min(480, delta)))))
        # Use rounded dimensions in the anchor calculation to prevent cumulative drift.
        width = max(1, round(self.image.width() * scale))
        height = max(1, round(self.image.height() * scale))
        self.setGeometry(anchor_geometry(self.geometry(), event.globalPos(), width, height))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.globalPos() - self.pos()
            # Native compositor move works on Wayland where absolute move is restricted.
            if self.windowHandle() and QApplication.platformName().startswith("wayland"):
                self.windowHandle().startSystemMove()

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseDoubleClickEvent(self, event):
        self.setGeometry(anchor_geometry(self.geometry(), event.globalPos(), self.image.width(), self.image.height()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("复制图片", lambda: QApplication.clipboard().setImage(self.image))
        menu.addAction("恢复原尺寸", lambda: self.resize(self.image.size()))
        menu.addSeparator()
        menu.addAction("关闭贴图", self.close)
        menu.exec_(event.globalPos())


class Editor(QMainWindow):
    pinRequested = pyqtSignal(object)
    ocrRequested = pyqtSignal(object)
    saved = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("rainshot · 编辑截图")
        self.resize(1200, 820)
        self.document = Document(image)
        self.saved_state = (self.document.base.cacheKey(), self.document.marks)
        self.canvas = Canvas(self.document)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("editorHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(22, 16, 22, 16)
        title = QLabel("rainshot  /  编辑截图")
        title.setObjectName("sectionTitle")
        row.addWidget(title)
        row.addStretch()
        for label, fn, primary in [("文字识别", lambda: self.ocrRequested.emit(self.document.render()), False),
                                    ("贴到屏幕", lambda: self.pinRequested.emit(self.document.render()), False),
                                    ("保存…", self.save, False), ("复制图片", self.copy, True)]:
            button = QPushButton(label)
            button.setObjectName("primary" if primary else "secondary")
            button.clicked.connect(fn)
            row.addWidget(button)
        layout.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("toolRail")
        rail.setFixedWidth(124)
        tools = QVBoxLayout(rail)
        tools.setContentsMargins(12, 16, 12, 16)
        tools.setSpacing(5)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, label, shortcut in TOOLS:
            button = QPushButton(f"{label}  {shortcut}")
            button.setObjectName("tool")
            button.setCheckable(True)
            button.setChecked(key == "arrow")
            button.clicked.connect(lambda _, k=key: self.canvas.set_tool(k))
            self.group.addButton(button)
            tools.addWidget(button)
            QShortcut(QKeySequence(shortcut), self, activated=button.click)
        tools.addStretch()
        body.addWidget(rail)
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        properties = QHBoxLayout()
        properties.setContentsMargins(18, 12, 18, 12)
        properties.addWidget(QLabel("颜色"))
        for color in ["#ef5b5b", "#f1ac35", "#1ba78f", "#4e80df", "#1b2936", "#ffffff"]:
            swatch = QPushButton()
            swatch.setFixedSize(24, 24)
            swatch.setStyleSheet(f"background:{color};border:1px solid #b9c9c5;border-radius:12px;")
            swatch.setToolTip(color)
            swatch.clicked.connect(lambda _, c=color: setattr(self.canvas, "color", c))
            properties.addWidget(swatch)
        custom = QPushButton("自选")
        custom.clicked.connect(self.pick_color)
        properties.addWidget(custom)
        properties.addSpacing(14)
        properties.addWidget(QLabel("粗细"))
        width = QSpinBox()
        width.setRange(1, 24)
        width.setValue(4)
        width.valueChanged.connect(lambda n: setattr(self.canvas, "stroke", n))
        properties.addWidget(width)
        properties.addStretch()
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        properties.addWidget(self.undo_button)
        properties.addWidget(self.redo_button)
        center.addLayout(properties)
        center.addWidget(self.canvas)
        footer = QHBoxLayout()
        footer.setContentsMargins(18, 10, 18, 10)
        self.dimensions = QLabel()
        footer.addWidget(self.dimensions)
        footer.addStretch()
        self.zoom_label = QLabel("100%")
        footer.addWidget(self.zoom_label)
        for label, fn in [("适应窗口", self.canvas.fit_image), ("1:1", self.canvas.actual_size)]:
            button = QPushButton(label)
            button.clicked.connect(fn)
            footer.addWidget(button)
        center.addLayout(footer)
        body.addLayout(center, 1)
        layout.addLayout(body, 1)
        self.setCentralWidget(root)
        self.canvas.changed.connect(self.update_state)
        self.canvas.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z:.0%}"))
        for key, fn in [("Ctrl+Z", self.undo), ("Ctrl+Shift+Z", self.redo), ("Ctrl+Y", self.redo),
                        ("Ctrl+S", self.save), ("Ctrl+C", self.copy), ("Ctrl+0", self.canvas.fit_image),
                        ("Ctrl+1", self.canvas.actual_size)]:
            QShortcut(QKeySequence(key), self, activated=fn)
        self.update_state()

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, "_fitted"):
            self._fitted = True
            self.canvas.fit_image()

    def update_state(self):
        self.dimensions.setText(f"{self.document.base.width()} × {self.document.base.height()} px   ·   滚轮缩放，V 拖动画布")
        self.undo_button.setEnabled(bool(self.document.past))
        self.redo_button.setEnabled(bool(self.document.future))

    def undo(self):
        if self.document.undo():
            self.canvas.refresh()

    def redo(self):
        if self.document.redo():
            self.canvas.refresh()

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.canvas.color), self, "标注颜色")
        if color.isValid():
            self.canvas.color = color.name()

    def copy(self):
        QApplication.clipboard().setImage(self.document.render())
        self.statusBar().showMessage("已复制图片；rainshot保持运行时可继续粘贴。", 5000)

    def save(self):
        folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        name = str(Path(folder) / ("rainshot_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"))
        path, selected = QFileDialog.getSaveFileName(self, "保存截图", name, "PNG 图片 (*.png);;JPEG 图片 (*.jpg);;WebP 图片 (*.webp)")
        if not path:
            return False
        if not Path(path).suffix:
            path += ".jpg" if "JPEG" in selected else ".webp" if "WebP" in selected else ".png"
        try:
            save_image(self.document.render(), path)
            self.saved_state = (self.document.base.cacheKey(), self.document.marks)
            self.saved.emit(path)
            self.statusBar().showMessage("已保存：" + path, 6000)
            return True
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False

    def closeEvent(self, event):
        state = (self.document.base.cacheKey(), self.document.marks)
        if state != self.saved_state:
            answer = QMessageBox.question(self, "保留标注", "标注尚未保存，是否保存后关闭？", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save and not self.save()):
                event.ignore()
                return
        event.accept()
        self.closed.emit()

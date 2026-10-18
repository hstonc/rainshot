"""Image operations use physical pixels; window geometry uses logical pixels."""
from dataclasses import dataclass, field
import math
from pathlib import Path
import numpy as np
from PyQt5.QtCore import Qt, QPointF, QRectF, QRect, QSaveFile, QIODevice
from PyQt5.QtGui import QImage, QImageReader, QPainter, QPen, QColor, QFont, QPolygonF, QTextDocument, QTextOption

MAX_PIXELS = 80_000_000


def check_size(width, height):
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS or max(width, height) > 32760:
        raise ValueError("图像尺寸无效，或超过 8000 万像素 / 单边 32760 像素，请缩小截图区域。")


def load_image(path):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        check_size(size.width(), size.height())
    image = reader.read()
    if image.isNull():
        raise ValueError("无法读取图片：" + reader.errorString())
    check_size(image.width(), image.height())
    image.setDevicePixelRatio(1)
    return image.convertToFormat(QImage.Format_ARGB32)


def save_image(image, path):
    """Atomic writes preserve an existing file if encoding or disk I/O fails."""
    suffix = Path(path).suffix.lower()
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(suffix)
    if not fmt:
        raise ValueError("请选择 PNG、JPEG 或 WebP 格式。")
    out = QSaveFile(str(path))
    if not out.open(QIODevice.WriteOnly):
        raise OSError(out.errorString())
    if not image.save(out, fmt, -1 if fmt == "PNG" else 95):
        out.cancelWriting()
        raise OSError("编码失败；当前系统可能未安装此图片格式的 Qt 插件。")
    if not out.commit():
        raise OSError(out.errorString())


@dataclass(frozen=True)
class Mark:
    kind: str
    points: tuple
    color: str = "#ef5b5b"
    width: int = 4
    text: str = ""


def draw_mark(painter, mark):
    points = [QPointF(*p) for p in mark.points]
    if not points:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor(mark.color)
    painter.setPen(QPen(color, mark.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    a, b = points[0], points[-1]
    rect = QRectF(a, b).normalized()
    if mark.kind == "rect":
        painter.drawRect(rect)
    elif mark.kind == "ellipse":
        painter.drawEllipse(rect)
    elif mark.kind in ("pen", "highlight"):
        if mark.kind == "highlight":
            color.setAlpha(75)
            painter.setPen(QPen(color, mark.width * 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPolyline(QPolygonF(points)) if len(points) > 1 else painter.drawPoint(a)
    elif mark.kind in ("arrow", "line"):
        painter.drawLine(a, b)
        if mark.kind == "arrow" and a != b:
            angle = math.atan2(b.y() - a.y(), b.x() - a.x())
            length = max(12, mark.width * 4)
            c = QPointF(b.x() - length * math.cos(angle - .5), b.y() - length * math.sin(angle - .5))
            d = QPointF(b.x() - length * math.cos(angle + .5), b.y() - length * math.sin(angle + .5))
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([b, c, d]))
    elif mark.kind == "text":
        font = QFont("Noto Sans CJK TC")
        font.setPixelSize(max(16, mark.width * 6))
        painter.setFont(font)
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(font)
        option = QTextOption()
        option.setWrapMode(QTextOption.NoWrap)
        document.setDefaultTextOption(option)
        document.setPlainText(mark.text)
        painter.translate(a)
        # The editor and committed mark share Qt's text document layout.
        from PyQt5.QtGui import QAbstractTextDocumentLayout, QPalette
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.Text, color)
        document.documentLayout().draw(painter, context)
    elif mark.kind == "number":
        radius = max(14, mark.width * 4)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(a, radius, radius)
        painter.setPen(Qt.white)
        font = QFont("Sans Serif")
        font.setBold(True)
        font.setPixelSize(int(radius * 1.2))
        painter.setFont(font)
        painter.drawText(QRectF(a.x() - radius, a.y() - radius, radius * 2, radius * 2), Qt.AlignCenter, mark.text)
    elif mark.kind == "redact":
        painter.fillRect(rect.toAlignedRect(), QColor("#161d25"))
    painter.restore()


class Document:
    """History stores commands and implicitly shared source images, not full renders."""
    def __init__(self, image):
        check_size(image.width(), image.height())
        self.base = image.convertToFormat(QImage.Format_ARGB32)
        self.base.setDevicePixelRatio(1)
        self.marks = ()
        self.past = []
        self.future = []
        self._cache = None

    def _remember(self):
        self.past.append((QImage(self.base), self.marks))
        # Crop snapshots can be large; bound both count and conservative byte use.
        while len(self.past) > 60 or (len(self.past) > 1 and
                sum(i.sizeInBytes() for i, _ in self.past) > 256_000_000):
            self.past.pop(0)
        self.future.clear()
        self._cache = None

    def add(self, mark):
        self._remember()
        self.marks += (mark,)

    def undo(self):
        if not self.past:
            return False
        self.future.append((self.base, self.marks))
        self.base, self.marks = self.past.pop()
        self._cache = None
        return True

    def redo(self):
        if not self.future:
            return False
        self.past.append((self.base, self.marks))
        self.base, self.marks = self.future.pop()
        self._cache = None
        return True

    def crop(self, rect):
        rect = rect.toAlignedRect().intersected(self.base.rect())
        if rect.width() < 2 or rect.height() < 2:
            return False
        cropped = self.render().copy(rect)
        self._remember()
        self.base, self.marks = cropped, ()
        return True

    def replace(self, image):
        check_size(image.width(), image.height())
        self._remember()
        self.base = image.convertToFormat(QImage.Format_ARGB32)
        self.base.setDevicePixelRatio(1)
        self.marks = ()

    def render(self):
        if self._cache is not None:
            return self._cache
        result = self.base.copy()
        for mark in self.marks:
            if mark.kind == "mosaic":
                rect = QRectF(QPointF(*mark.points[0]), QPointF(*mark.points[-1])).normalized().toAlignedRect().intersected(result.rect())
                if rect.isEmpty():
                    continue
                block = max(6, mark.width * 3)
                tile = result.copy(rect).scaled(max(1, rect.width() // block), max(1, rect.height() // block), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                tile = tile.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
                painter = QPainter(result)
                painter.drawImage(rect.topLeft(), tile)
                painter.end()
            else:
                painter = QPainter(result)
                draw_mark(painter, mark)
                painter.end()
        self._cache = result
        return result


def anchor_geometry(old, cursor, new_width, new_height):
    """One atomic geometry change keeps the same image pixel under the cursor."""
    rx = (cursor.x() - old.x()) / old.width()
    ry = (cursor.y() - old.y()) / old.height()
    return QRect(round(cursor.x() - rx * new_width), round(cursor.y() - ry * new_height), new_width, new_height)


@dataclass
class ScreenTile:
    geometry: QRect
    image: QImage


def compose_tiles(tiles, region):
    """Map each monitor's logical coordinates to its own physical source pixels."""
    selected = [t for t in tiles if t.geometry.intersects(region)]
    if not selected or region.isEmpty():
        raise ValueError("选区不在可用屏幕范围内。")
    scale = max(t.image.width() / t.geometry.width() for t in selected)
    width, height = round(region.width() * scale), round(region.height() * scale)
    check_size(width, height)
    result = QImage(width, height, QImage.Format_ARGB32)
    result.fill(Qt.black)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    for tile in selected:
        cut = tile.geometry.intersected(region)
        sx = tile.image.width() / tile.geometry.width()
        sy = tile.image.height() / tile.geometry.height()
        source = QRectF((cut.x() - tile.geometry.x()) * sx, (cut.y() - tile.geometry.y()) * sy, cut.width() * sx, cut.height() * sy)
        target = QRectF((cut.x() - region.x()) * scale, (cut.y() - region.y()) * scale, cut.width() * scale, cut.height() * scale)
        raw = QImage(tile.image)
        raw.setDevicePixelRatio(1)
        painter.drawImage(target, raw, source)
    painter.end()
    return result


def rgb_array(image):
    rgb = image.convertToFormat(QImage.Format_RGB888)
    ptr = rgb.bits()
    ptr.setsize(rgb.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(rgb.height(), rgb.bytesPerLine())[:, :rgb.width() * 3].reshape(rgb.height(), rgb.width(), 3).copy()


def find_overlap(previous, following):
    """Conservative vertical overlap; reject blank, ambiguous, or changed content."""
    if previous.width() != following.width():
        raise ValueError("两张截图宽度不同，请保持窗口、缩放和选区不变。")
    if previous.height() < 64 or following.height() < 64:
        raise ValueError("截图高度至少需要 64 像素。")
    h = min(previous.height(), following.height())
    # Sample columns, retaining physical row resolution and RGB to detect color changes.
    a = rgb_array(previous.copy(0, previous.height() - h, previous.width(), h))
    b = rgb_array(following.copy(0, 0, following.width(), h))
    step = max(1, previous.width() // 80)
    a, b = a[:, ::step, :].astype(np.float32), b[:, ::step, :].astype(np.float32)
    if float(np.abs(a - b).mean()) < .5:
        raise ValueError("画面没有移动，请向下滚动后再采集。")
    # Compare a 24-row stripe for every possible overlap, then verify full overlap.
    stripe = min(24, h // 4)
    minimum = max(40, h // 6)
    candidates = []
    for overlap in range(minimum, h - 8):
        score = float(np.abs(a[h - overlap:h - overlap + stripe] - b[:stripe]).mean())
        if score < 8:
            candidates.append((score, overlap))
    matches = []
    for _, overlap in sorted(candidates)[:20]:
        source, target = a[-overlap:], b[:overlap]
        # Repeated text rows and blank pages must not silently produce a false seam.
        detail = float(np.abs(np.diff(target, axis=0)).mean())
        error = float(np.abs(source - target).mean())
        if detail > 1 and error < 4:
            matches.append((error, overlap))
    if not matches:
        raise ValueError("找不到可靠重叠。请减少滚动距离，保留约一半重叠，并避开固定页头或动画。")
    matches.sort()
    if len(matches) > 1 and matches[1][0] - matches[0][0] < .8 and abs(matches[1][1] - matches[0][1]) > 3:
        raise ValueError("页面内容重复，拼接位置不唯一。请调整选区或滚动距离。")
    return matches[0][1]


def stitch_pair(previous, following):
    overlap = find_overlap(previous, following)
    height = previous.height() + following.height() - overlap
    check_size(previous.width(), height)
    result = QImage(previous.width(), height, QImage.Format_ARGB32)
    result.fill(Qt.white)
    painter = QPainter(result)
    painter.drawImage(0, 0, previous)
    painter.drawImage(0, previous.height(), following.copy(0, overlap, following.width(), following.height() - overlap))
    painter.end()
    return result, overlap

"""Non-interactive pixel loupe; never included in exported screenshot pixels."""
from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtGui import QColor, QPainter, QPen, QFont
from PyQt5.QtWidgets import QApplication, QWidget


class PixelMagnifier(QWidget):
    CELLS = 11
    CELL = 12

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(184, 240)
        self.setWindowTitle('rainshot · 像素放大鏡')
        self.image = None
        self.pixel = QPoint()

    def present(self, image, pixel, cursor):
        self.image, self.pixel = image, QPoint(pixel)
        screen = QApplication.screenAt(cursor) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x, y = cursor.x() + 24, cursor.y() + 24
        if x + self.width() > bounds.right() + 1:
            x = cursor.x() - self.width() - 24
        if y + self.height() > bounds.bottom() + 1:
            y = cursor.y() - self.height() - 24
        self.move(max(bounds.left(), min(x, bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(y, bounds.bottom() - self.height() + 1)))
        self.update()
        self.show()
        self.raise_()

    def paintEvent(self, event):
        if self.image is None:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#151c2e'))
        painter.setPen(QColor('#8797ff'))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        left, top = 26, 10
        radius = self.CELLS // 2
        for row in range(self.CELLS):
            for col in range(self.CELLS):
                x, y = self.pixel.x() + col - radius, self.pixel.y() + row - radius
                rect = QRect(left + col * self.CELL, top + row * self.CELL, self.CELL, self.CELL)
                painter.fillRect(rect, QColor('#4c597d' if (row + col) % 2 else '#26314c'))
                if self.image.rect().contains(x, y):
                    painter.fillRect(rect, self.image.pixelColor(x, y))
                painter.setPen(QColor(0, 0, 0, 45))
                painter.drawRect(rect.adjusted(0, 0, -1, -1))
        center = QRect(left + radius * self.CELL, top + radius * self.CELL, self.CELL, self.CELL)
        painter.setPen(QPen(Qt.black, 3))
        painter.drawRect(center)
        painter.setPen(QPen(Qt.white, 1))
        painter.drawRect(center)
        color = self.image.pixelColor(self.pixel)
        painter.setFont(QFont('monospace', 10))
        painter.setPen(QColor('#edf0ff'))
        lines = [color.name().upper(), f'RGB {color.red()}, {color.green()}, {color.blue()}',
                 f'{self.pixel.x()}, {self.pixel.y()}', '方向鍵逐像素微調', '點擊 / Enter 複製']
        for index, text in enumerate(lines):
            painter.drawText(QRect(5, 149 + index * 17, self.width() - 10, 17), Qt.AlignCenter, text)

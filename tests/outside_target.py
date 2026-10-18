"""Own non-activating window for external-process click-through integration tests."""
import sys
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtWidgets import QApplication, QWidget

app = QApplication([])


class Target(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(int(sys.argv[1]), int(sys.argv[2]), 380, 220)
        self.count = 0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#224760"))
        painter.setPen(Qt.white)
        painter.drawText(30, 80, "rainshot external click test")
        painter.drawText(30, 120, "This window does not take keyboard focus.")

    def mousePressEvent(self, event):
        self.count += 1
        Path(sys.argv[3]).write_text(str(self.count))


window = Target()
window.show()
app.processEvents()
print("READY", flush=True)
app.exec_()

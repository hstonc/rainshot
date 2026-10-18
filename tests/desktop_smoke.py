"""Opt-in integration test that briefly opens sample windows on the real X11 desktop."""
import json
import os
import sys
import tempfile
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtTest import QTest, QSignalSpy
from rainshot.capture import grab_tiles, compose_tiles, SelectionOverlay, desktop_rect
from rainshot.editor import Editor, PinWindow
from rainshot.imaging import save_image, load_image
from rainshot.style import STYLE


class Target(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("rainshot integration test")
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen.x() + 150, screen.y() + 150, 520, 320)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#237761"))
        p.fillRect(QRect(40, 40, 150, 100), QColor("#f1ac35"))
        p.setPen(Qt.white)
        p.drawText(40, 230, "rainshot · 桌面截图集成测试")


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(STYLE)
    assert app.platformName() == "xcb", "This test requires a real X11 session"
    target = Target()
    target.show()
    target.raise_()
    QTest.qWait(500)
    tiles = grab_tiles()
    crop = compose_tiles(tiles, target.geometry())
    assert crop.pixelColor(80, 80).name() == "#f1ac35"
    assert crop.pixelColor(250, 80).name() == "#237761"
    overlay = SelectionOverlay(tiles)
    selected = QSignalSpy(overlay.selected)
    QTest.qWait(250)
    # Select only our own test window, even though the overlay spans the virtual desktop.
    start = target.geometry().topLeft() - desktop_rect(tiles).topLeft() + QPoint(5, 5)
    end = start + QPoint(499, 299)
    QTest.mousePress(overlay, Qt.LeftButton, pos=start)
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=end)
    assert len(selected) == 1
    image = selected[0][0]
    assert image.width() == 500 and image.height() == 300
    assert image.pixelColor(75, 75).name() == "#f1ac35"
    editor = Editor(image)
    editor.show()
    QTest.qWait(250)
    editor.copy()
    assert QApplication.clipboard().image().width() == 500
    path = out / "x11-test-capture.png"
    save_image(editor.document.render(), path)
    assert load_image(path).width() == 500
    pin = PinWindow(image)
    pin.show()
    QTest.qWait(150)
    assert pin.isVisible()
    pin.close()
    editor.close()
    target.close()
    app.processEvents()
    report = {"platform": app.platformName(), "screens": [t.geometry.getRect() for t in tiles],
        "capture_selection": "500x300 physical pixels, expected sample colors verified",
        "editor_clipboard_export_pin": "passed"}
    (out / "x11-smoke.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()

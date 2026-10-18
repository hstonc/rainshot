"""Real X11 test: generated content only; temporary external window receives clicks."""
import ctypes as C
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtGui import QPainter, QColor, QCursor
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtTest import QTest
from rainshot.app import Controller
from rainshot.capture import desktop_rect
from rainshot.floating import FloatingShot

output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=True)
app = QApplication([])
assert app.platformName() == "xcb"
screen = app.primaryScreen().availableGeometry()
previous_cursor = QCursor.pos()


class Source(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setGeometry(screen.x() + 100, screen.y() + 120, 520, 320)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#237761"))
        painter.fillRect(QRect(40, 40, 150, 100), QColor("#f1ac35"))
        painter.setPen(Qt.white)
        painter.drawText(30, 220, "rainshot 0.3 · 原位貼圖測試")


x = C.CDLL("libX11.so.6")
xt = C.CDLL("libXtst.so.6")
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XFlush.argtypes = [C.c_void_p]
x.XCloseDisplay.argtypes = [C.c_void_p]
xt.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
xt.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
display = x.XOpenDisplay(None)
assert display


def click(point, button=1):
    xt.XTestFakeMotionEvent(display, -1, point.x(), point.y(), 0)
    xt.XTestFakeButtonEvent(display, button, 1, 0)
    x.XFlush(display)
    QTest.qWait(35)
    xt.XTestFakeButtonEvent(display, button, 0, 0)
    x.XFlush(display)
    QTest.qWait(180)


source = Source()
controller = Controller(app)
external = None
try:
    source.show()
    QTest.qWait(300)
    controller.capture("region", 0)
    QTest.qWait(500)
    overlay = controller.overlay
    assert overlay is not None
    start = source.pos() - overlay.bounds.topLeft() + QPoint(5, 5)
    QTest.mousePress(overlay, Qt.LeftButton, pos=start)
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=start + QPoint(499, 299))
    QTest.qWait(220)
    shot = next(w for w in controller.windows if not w.closing)
    assert isinstance(shot, FloatingShot) and not shot.pinned
    image = shot.document.render()
    assert (image.width(), image.height()) == (500, 300)
    assert image.pixelColor(75, 75).name() == "#f1ac35"
    assert shot.image_origin() == source.pos() + QPoint(5, 5)
    assert shot.outside_clicks.display, "XInput observer unavailable"
    source.hide()
    marker = output / "click-count.txt"
    external_point = QPoint(screen.x() + 940, screen.y() + 180)
    external = subprocess.Popen([sys.executable, str(Path(__file__).with_name("outside_target.py")),
        str(screen.x() + 900), str(screen.y() + 120), str(marker)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert external.stdout.readline().strip() == "READY"
    QTest.qWait(200)
    assert not shot.closing, "Non-activating external window should not itself dismiss the shot"
    click(external_point)
    assert shot.closing, "Click on external non-focusable window must dismiss transient shot"
    assert marker.read_text() == "1", "Original click must reach the external application"
    pinned = controller.edit(image, QRect(screen.x() + 100, screen.y() + 120, 500, 300), pinned=True)
    QTest.qWait(180)
    click(external_point)
    assert pinned.isVisible() and not pinned.closing
    assert marker.read_text() == "2"
    cursor = pinned.image_origin() + QPoint(250, 150)
    before_origin = pinned.image_origin()
    before_width = pinned.surface.width()
    rx = (cursor.x() - before_origin.x()) / before_width
    click(cursor, button=4)
    assert pinned.surface.width() > before_width
    assert abs((cursor.x() - pinned.image_origin().x()) / pinned.surface.width() - rx) < .005
    pinned.grab().save(str(output / "native-floating.png"))
    click(pinned.buttons["pin"].mapToGlobal(pinned.buttons["pin"].rect().center()))
    assert not pinned.pinned
    click(external_point)
    assert pinned.closing and marker.read_text() == "3"
    report = {"capture_result": "500x300, exact image origin and sample pixel colors verified",
        "no_home_or_editor_window": not hasattr(controller, "home"),
        "outside_nonactivating_window": "transient dismissed; original click delivered",
        "pinned_outside_click": "remains visible",
        "native_wheel_zoom": "dimensions increased; image anchor preserved",
        "unpin_then_outside_click": "dismissed"}
    (output / "desktop-v0.3.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
finally:
    controller.close_shots()
    controller.tray.hide()
    controller.hotkeys.close()
    source.close()
    if external:
        external.terminate()
        external.wait(timeout=5)
    xt.XTestFakeMotionEvent(display, -1, previous_cursor.x(), previous_cursor.y(), 0)
    x.XFlush(display)
    x.XCloseDisplay(display)

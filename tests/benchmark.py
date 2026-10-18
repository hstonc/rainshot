"""Reproducible CPU timings; these are not compositor/input-to-photon measurements."""
import json
import statistics
import time
from PyQt5.QtCore import Qt, QPoint, QPointF
from PyQt5.QtGui import QImage, QColor, QWheelEvent
from PyQt5.QtWidgets import QApplication
from rainshot.editor import PinWindow, Canvas
from rainshot.imaging import Document, Mark

app = QApplication([])
image = QImage(3840, 2160, QImage.Format_ARGB32)
image.fill(QColor("white"))
pin = PinWindow(image)
pin.resize(800, 450)
timings = []
for i in range(200):
    point = QPoint(pin.width() // 2, pin.height() // 2)
    event = QWheelEvent(QPointF(point), QPointF(pin.pos() + point), QPoint(), QPoint(0, 120 if i % 2 == 0 else -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    start = time.perf_counter()
    pin.wheelEvent(event)
    timings.append((time.perf_counter() - start) * 1000)
doc = Document(image)
for i in range(20):
    doc.add(Mark("arrow", ((200, i * 80 + 20), (1000, i * 80 + 50))))
start = time.perf_counter()
doc.render()
render_ms = (time.perf_counter() - start) * 1000
canvas = Canvas(doc)
canvas.resize(900, 650)
canvas.show()
app.processEvents()
canvas.actual_size()
point = QPoint(650, 380)
before = canvas.mapToScene(point)
for _ in range(10):
    canvas.zoom_at(point, 1.05)
after = canvas.mapToScene(point)
print(json.dumps({"pin_4k_wheel_handler_median_ms": round(statistics.median(timings), 3),
    "pin_4k_wheel_handler_p95_ms": round(sorted(timings)[189], 3),
    "render_4k_20_arrows_ms": round(render_ms, 2),
    "canvas_anchor_drift_after_10_zooms_px": [round(after.x() - before.x(), 2), round(after.y() - before.y(), 2)],
    "note": "offscreen CPU timing; not a frame-rate or compositor-latency claim"}, indent=2))

"""Current surface CPU event/paint benchmark; does not measure compositor latency."""
import json
import statistics
import time
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication
from rainshot.floating import FloatingShot

app = QApplication([])
image = QImage(3840, 2160, QImage.Format_ARGB32)
image.fill(Qt.white)
shot = FloatingShot(image, pinned=True)
shot.show_active()
app.processEvents()
samples = []
for i in range(200):
    point = shot.image_origin() + QPoint(shot.surface.width() // 2, shot.surface.height() // 2)
    start = time.perf_counter()
    shot.zoom_at(point, 1.05 if i % 2 == 0 else 1 / 1.05)
    # Include painting our own widgets, but not the desktop compositor.
    app.processEvents()
    samples.append((time.perf_counter() - start) * 1000)
print(json.dumps({"source": "3840x2160", "iterations": 200,
    "zoom_and_qt_paint_median_ms": round(statistics.median(samples), 3),
    "zoom_and_qt_paint_p95_ms": round(sorted(samples)[189], 3),
    "note": "Offscreen CPU timing including Qt repaint; not input-to-display latency"}, indent=2))
shot.close()

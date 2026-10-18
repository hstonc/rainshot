"""Run the actual toolbar OCR action and select its real results in the image."""
import json
import os
import sys
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QImage, QPainter, QColor, QFont
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest, QSignalSpy
from rainshot.floating import FloatingShot

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
image = QImage(1000, 370, QImage.Format_ARGB32)
image.fill(QColor("#fbfcf7"))
painter = QPainter(image)
painter.fillRect(0, 0, 1000, 48, QColor("#e6eee4"))
font = QFont("Noto Sans CJK TC")
font.setPixelSize(16)
painter.setFont(font)
painter.setPen(QColor("#3d6552"))
painter.drawText(40, 32, "RAINSHOT  /  原位文字選取")
font.setPixelSize(40)
painter.setFont(font)
painter.setPen(QColor("#203b37"))
painter.drawText(42, 125, "直接在貼圖上，選取需要的文字。")
font.setPixelSize(28)
painter.setFont(font)
painter.drawText(42, 198, "點擊其他地方關閉，釘住後保留。")
painter.drawText(42, 260, "rainshot screenshot test 12345")
font.setPixelSize(16)
painter.setFont(font)
painter.setPen(QColor("#6d8778"))
painter.drawText(42, 332, "本機 OCR · 保留原圖 · 支援跨行選取與複製")
painter.end()
shot = FloatingShot(image, pinned=True)
shot.show_active()
app.processEvents()
shot.run_ocr()
assert shot.ocr_job is not None
ready = QSignalSpy(shot.ocr_job.layoutReady)
assert ready.wait(60000), shot.status.text()
assert shot.selection and len(shot.selection.words) > 3
text = shot.selection.all_text
assert "12345" in text and "rainshot" in text, text
assert "選取" in text.replace(" ", ""), text
target_word = next(w for w in shot.selection.words if "12345" in w.text)
def local(point):
    return QPoint(round(point.x() * shot.surface.width() / image.width()), round(point.y() * shot.surface.height() / image.height()))
start = target_word.rect.topLeft() + QPoint(2, 2)
end = target_word.rect.bottomRight() - QPoint(2, 2)
QTest.mousePress(shot.surface, Qt.LeftButton, pos=local(start))
QTest.mouseRelease(shot.surface, Qt.LeftButton, pos=local(end))
assert "12345" in shot.selection.selected_text
shot.copy_text()
assert "12345" in QApplication.clipboard().text()
# Highlight the main paragraph using the real OCR boxes for the preview.
matching = [i for i, g in enumerate(shot.selection.glyphs) if 65 < g.rect.center().y() < 205]
assert matching
shot.selection.anchor, shot.selection.end = matching[0], matching[-1]
shot.surface.update()
app.processEvents()
shot.grab().save(str(out / "floating-ocr.png"))
image.save(str(out / "ocr-sample.png"))
report = {"languages": ready[0][1], "recognized_text": text,
          "positioned_words": len(shot.selection.words), "mouse_selection_and_copy": "12345 verified",
          "private_temp_cleaned": shot.ocr_job.temp is None}
(out / "positioned-ocr.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
shot.close()

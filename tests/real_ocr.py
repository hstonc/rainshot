"""Opt-in real OCR test. Supply a local Tesseract binary as the first argument."""
import json
import sys
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter, QColor, QFont
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QSignalSpy
from rainshot.ocr import OcrJob

app = QApplication([])
image = QImage(1300, 360, QImage.Format_ARGB32)
image.fill(Qt.white)
painter = QPainter(image)
font = QFont("Noto Sans CJK SC")
font.setPixelSize(48)
painter.setFont(font)
painter.setPen(Qt.black)
painter.drawText(50, 110, "rainshot截图软件，支持离线文字识别。")
painter.drawText(50, 220, "rainshot screenshot test 12345")
painter.end()
job = OcrJob(image, executable=sys.argv[1])
done, failed = QSignalSpy(job.finished), QSignalSpy(job.failed)
job.start()
assert done.wait(60000), list(failed)
text = done[0][0]
assert "12345" in text and "rainshot" in text, text
assert "文字识别" in text.replace(" ", ""), text
result = {"languages": done[0][1], "recognized": text, "private_temp_removed": job.temp is None}
Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))

"""Render only application-owned sample content; never includes the user's desktop."""
import os
import sys
import tempfile
from pathlib import Path
from PyQt5.QtCore import Qt, QRectF, QSettings
from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QPen
from PyQt5.QtWidgets import QApplication
from rainshot.home import Home
from rainshot.editor import Editor
from rainshot.imaging import Mark
from rainshot.style import STYLE


def sample():
    image = QImage(1100, 700, QImage.Format_ARGB32)
    image.fill(QColor("#f8f6f0"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(0, 0, 1100, 64, QColor("#e7e9e1"))
    font = QFont("Noto Sans CJK SC")
    font.setPixelSize(16)
    painter.setFont(font)
    painter.setPen(QColor("#557365"))
    painter.drawText(42, 40, "FIELD NOTES     /     设计工作台")
    painter.drawText(820, 40, "工作空间    ·    本地草稿")
    font.setPixelSize(42)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#253e36"))
    painter.drawText(65, 145, "好想法，值得被看见。")
    font.setPixelSize(18)
    font.setBold(False)
    painter.setFont(font)
    painter.drawText(65, 190, "让记录更轻松，让沟通更清楚。")
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#dcead9"))
    painter.drawRoundedRect(QRectF(65, 240, 590, 320), 22, 22)
    painter.setBrush(QColor("#618b71"))
    painter.drawEllipse(QRectF(132, 286, 212, 212))
    painter.setBrush(QColor("#f0ca7a"))
    painter.drawRoundedRect(QRectF(288, 302, 276, 183), 24, 24)
    painter.setBrush(QColor("#e8ede4"))
    painter.drawRoundedRect(QRectF(702, 240, 329, 320), 22, 22)
    font.setPixelSize(22)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#253e36"))
    painter.drawText(730, 292, "本周待办")
    font.setPixelSize(18)
    font.setBold(False)
    painter.setFont(font)
    for y, text in [(344, "01   整理灵感与参考"), (400, "02   标注讨论重点"), (456, "03   保存一份清晰记录")]:
        painter.drawText(730, y, text)
    painter.setPen(QColor("#799084"))
    painter.drawText(65, 638, "rainshot 示例画布  ·  不含真实用户数据")
    painter.end()
    return image


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as temp:
        home = Home(QSettings(temp + "/settings.ini", QSettings.IniFormat))
        home.show()
        app.processEvents()
        home.grab().save(str(output / "home.png"))
        home.hide()
        image = sample()
        image.save(str(output / "sample.png"))
        editor = Editor(image)
        editor.document.add(Mark("rect", ((710, 360), (1010, 414)), "#ef5b5b", 3))
        editor.document.add(Mark("arrow", ((490, 188), (708, 376)), "#ef5b5b", 4))
        editor.document.add(Mark("number", ((705, 234),), "#237761", 4, "1"))
        editor.canvas.refresh()
        editor.show()
        app.processEvents()
        editor.canvas.fit_image()
        app.processEvents()
        editor.grab().save(str(output / "editor.png"))
        editor.hide()


if __name__ == "__main__":
    main()

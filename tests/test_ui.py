import os
from pathlib import Path
import pytest
from PyQt5.QtCore import Qt, QPoint, QPointF, QRect, QSettings
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest, QSignalSpy
from PyQt5.QtWidgets import QApplication, QMessageBox
from rainshot.editor import Editor, PinWindow
from rainshot.home import Home
from rainshot.capture import SelectionOverlay, portal_file
from rainshot.imaging import Mark, ScreenTile
from rainshot.ocr import OcrJob
from rainshot.stitch import StitchDialog


def test_editor_draw_copy_crop_and_zoom(app, image, monkeypatch):
    editor = Editor(image)
    editor.show()
    app.processEvents()
    canvas = editor.canvas
    canvas.fit_image()
    canvas.set_tool("rect")
    start = canvas.mapFromScene(QPointF(40, 40))
    end = canvas.mapFromScene(QPointF(200, 160))
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    assert len(editor.document.marks) == 1
    editor.copy()
    assert not QApplication.clipboard().image().isNull()
    editor.undo()
    assert not editor.document.marks
    editor.redo()
    assert editor.document.marks
    canvas.actual_size()
    pos = canvas.mapFromScene(QPointF(320, 200)) + QPoint(80, 50)
    before = canvas.mapToScene(pos)
    for _ in range(10):
        canvas.zoom_at(pos, 1.05)
    after = canvas.mapToScene(pos)
    assert abs(before.x() - after.x()) < .01
    assert abs(before.y() - after.y()) < .01
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    editor.close()


def test_pin_wheel_keeps_cursor_anchor(app, image):
    pin = PinWindow(image)
    pin.setGeometry(QRect(100, 100, 640, 400))
    pin.show()
    app.processEvents()
    old = pin.geometry()
    local = QPoint(350, 220)
    cursor = old.topLeft() + local
    event = QWheelEvent(QPointF(local), QPointF(cursor), QPoint(), QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    pin.wheelEvent(event)
    new = pin.geometry()
    assert abs((cursor.x() - new.x()) / new.width() - local.x() / old.width()) < .003
    assert abs((cursor.y() - new.y()) / new.height() - local.y() / old.height()) < .003
    assert pin.image.cacheKey() == image.cacheKey()
    pin.close()


def test_overlay_cancel_and_selection(app, image):
    tiles = [ScreenTile(QRect(0, 0, 640, 400), image)]
    overlay = SelectionOverlay(tiles)
    cancel = QSignalSpy(overlay.canceled)
    QTest.keyClick(overlay, Qt.Key_Escape)
    assert len(cancel) == 1
    overlay = SelectionOverlay(tiles)
    selected = QSignalSpy(overlay.selected)
    QTest.mousePress(overlay, Qt.LeftButton, pos=QPoint(30, 40))
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(230, 140))
    assert len(selected) == 1
    assert selected[0][0].width() == 201
    assert selected[0][1].x() == 30


def test_history_only_saved_paths(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    home = Home(settings)
    home.remember("/tmp/example.png")
    assert settings.value("history", [], type=list) == ["/tmp/example.png"]
    settings.setValue("history_enabled", False)
    home.remember("/tmp/disabled.png")
    assert settings.value("history", [], type=list) == ["/tmp/example.png"]
    home.clear_history()
    assert not settings.value("history", [], type=list)
    home.deleteLater()


@pytest.mark.parametrize("uri", ["https://example.com/a.png", "file://remote/a.png", "file:relative.png", "file:///a.png?x=1"])
def test_invalid_portal_uri(uri):
    with pytest.raises(ValueError):
        portal_file(uri)


def test_percent_encoded_uri():
    assert portal_file("file:///tmp/a%20b.png") == "/tmp/a b.png"


def test_ocr_success_and_temp_cleanup(app, image, tmp_path):
    executable = tmp_path / "tesseract-test"
    executable.write_text("#!/usr/bin/python3\nimport sys\nprint('eng\\nchi_sim' if '--list-langs' in sys.argv else '测试 rainshot')\n")
    executable.chmod(0o755)
    job = OcrJob(image, executable=str(executable))
    done = QSignalSpy(job.finished)
    failed = QSignalSpy(job.failed)
    job.start()
    assert done.wait(4000)
    assert len(failed) == 0
    assert done[0][0] == "测试 rainshot"
    assert done[0][1] == "chi_sim+eng"
    assert job.temp is None


def test_ocr_timeout_reaps_process(app, image, tmp_path):
    executable = tmp_path / "slow-test"
    executable.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(10)\n")
    executable.chmod(0o755)
    job = OcrJob(image, executable=str(executable))
    job.timer.setInterval(40)
    failed = QSignalSpy(job.failed)
    job.start()
    assert failed.wait(2000)
    assert "超时" in failed[0][0]
    assert job.process.state() == job.process.NotRunning


def test_stitch_dialog_starts_and_exports(app, image):
    dialog = StitchDialog(image)
    assert dialog.count == 1
    ready = QSignalSpy(dialog.editRequested)
    dialog.finish()
    assert len(ready) == 1
    assert dialog.completed


def test_editor_unsaved_cancel(app, image, monkeypatch):
    editor = Editor(image)
    editor.show()
    editor.document.add(Mark("arrow", ((20, 20), (80, 80))))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Cancel)
    assert not editor.close()
    assert editor.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Discard)
    assert editor.close()

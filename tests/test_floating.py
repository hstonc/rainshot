import sys
import pytest
from pathlib import Path
from PyQt5 import sip
from PyQt5.QtCore import Qt, QRect, QRectF, QPoint, QPointF, QEvent, QSettings, QObject
from PyQt5.QtGui import QMouseEvent, QDesktopServices
from PyQt5.QtWidgets import QApplication, QWidget, QFileDialog
from PyQt5.QtTest import QTest
from rainshot.floating import FloatingShot
from rainshot.ocr_layout import Word, parse_tsv, graphemes
from rainshot.hints import saved_notice_manager, create_save_notice


def words():
    return [Word("雨截", QRectF(30, 30, 60, 30), (1, 1, 1, 1), 95),
            Word("hello", QRectF(120, 30, 75, 30), (1, 1, 1, 1), 90),
            Word("文字選取", QRectF(30, 90, 120, 30), (1, 1, 1, 2), 98)]


def outside_event(shot):
    pos = shot.geometry().bottomRight() + QPoint(50, 50)
    return QMouseEvent(QEvent.MouseButtonPress, QPointF(0, 0), QPointF(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def test_transient_outside_close_and_pin_preserves(app, image):
    shot = FloatingShot(image)
    shot.show_active()
    shot.eventFilter(QWidget(), outside_event(shot))
    assert shot.closing and not shot.isVisible()
    pinned = FloatingShot(image)
    pinned.show_active()
    pinned.toggle_pin()
    pinned.eventFilter(QWidget(), outside_event(pinned))
    assert not pinned.closing and pinned.isVisible()
    pinned.toggle_pin()
    pinned.eventFilter(QWidget(), outside_event(pinned))
    assert pinned.closing


def test_toolbar_click_does_not_dismiss(app, image):
    shot = FloatingShot(image)
    shot.show_active()
    QTest.mouseClick(shot.buttons["annotate"], Qt.LeftButton)
    assert not shot.closing and shot.annotation_row.isVisible()
    QTest.mouseClick(shot.buttons["pin"], Qt.LeftButton)
    assert shot.pinned
    shot.close()


def test_pinned_shot_uses_managed_window_move(app, image, monkeypatch):
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    assert shot.windowType() == Qt.Window
    assert shot.windowFlags() & Qt.FramelessWindowHint
    assert shot.windowFlags() & Qt.WindowStaysOnTopHint
    calls = []
    monkeypatch.setattr(shot, 'begin_window_move', lambda: calls.append(True) or True)
    point = QPoint(40, 40)
    QTest.mousePress(shot.surface, Qt.LeftButton, pos=point)
    assert calls == [True]
    assert shot.surface.drag is None
    QTest.mouseRelease(shot.surface, Qt.LeftButton, pos=point)
    shot.close()


def test_window_move_falls_back_when_unsupported(app, image, monkeypatch):
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    monkeypatch.setattr(shot, 'begin_window_move', lambda: False)
    point = QPoint(40, 40)
    QTest.mousePress(shot.surface, Qt.LeftButton, pos=point)
    assert shot.surface.drag is not None
    QTest.mouseRelease(shot.surface, Qt.LeftButton, pos=point)
    assert shot.surface.drag is None
    shot.close()


def test_tsv_bounds_and_chinese_graphemes(app):
    data = "5\t1\t2\t3\t4\t1\t10\t20\t90\t30\t96\trainshot\n" \
           "5\t1\t2\t3\t4\t2\t-50\t20\t90\t30\t90\t裁切\n" \
           "5\t1\t2\t3\t4\t3\t1000\t20\t90\t30\t90\toutside\n" \
           "5\t1\t2\t3\t4\t3\t10\t20\t90\t30\t-1\tignore\n"
    result = parse_tsv(data, 640, 400)
    assert len(result) == 2 and result[1].rect.x() == 0
    assert result[0].line == (1, 2, 3, 4)
    assert graphemes("A😀e\u0301中") == ["A", "😀", "e\u0301", "中"]


def test_select_original_position_across_lines_and_zoom(app, image):
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    shot.ocr_complete(words(), "chi_tra+eng")
    assert shot.ocr_row.isVisible()
    def local(x, y):
        return QPoint(round(x * shot.surface.width() / 640), round(y * shot.surface.height() / 400))
    QTest.mousePress(shot.surface, Qt.LeftButton, pos=local(40, 45))
    QTest.mouseRelease(shot.surface, Qt.LeftButton, pos=local(140, 105))
    assert shot.selection.selected_text == "雨截 hello\n文字選取"
    assert len(shot.selection.highlight_rects) == 2
    shot.copy()
    assert QApplication.clipboard().text() == "雨截 hello\n文字選取"
    point = shot.surface.mapToGlobal(local(170, 110))
    old_origin = shot.image_origin()
    rx = (point.x() - old_origin.x()) / shot.surface.width()
    ry = (point.y() - old_origin.y()) / shot.surface.height()
    shot.zoom_at(point, 1.35)
    origin = shot.image_origin()
    assert abs((point.x() - origin.x()) / shot.surface.width() - rx) < .002
    assert abs((point.y() - origin.y()) / shot.surface.height() - ry) < .002
    QTest.mousePress(shot.surface, Qt.LeftButton, pos=local(65, 45))
    QTest.mouseRelease(shot.surface, Qt.LeftButton, pos=local(65, 45))
    assert shot.selection.selected_text == "截"
    shot.close()


def test_inline_text_no_dialog_and_undo_invalidate_ocr(app, image):
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    shot.set_mode("text")
    QTest.mouseClick(shot.surface, Qt.LeftButton, pos=QPoint(30, 40))
    assert shot.text_input.isVisible()
    shot.text_input.setPlainText("原位標註")
    QTest.keyClick(shot.text_input, Qt.Key_Return, Qt.ControlModifier)
    assert not shot.text_input.isVisible()
    assert shot.document.marks[-1].text == "原位標註"
    shot.ocr_complete(words(), "eng")
    shot.undo()
    assert shot.selection is None and not shot.document.marks
    shot.close()


def test_quick_save_no_dialog(app, image, tmp_path, monkeypatch):
    import rainshot.floating as module
    monkeypatch.setattr(module.QStandardPaths, "writableLocation", lambda _: str(tmp_path))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (_ for _ in ()).throw(AssertionError("Unexpected file dialog")))
    shot = FloatingShot(image, pinned=True)
    assert shot.save_to(tmp_path / "missing" / "fail.png") is False
    assert "儲存失敗" in shot.status.text() and not shot.closing
    shot.quick_save()
    from pathlib import Path
    assert Path(shot.last_save).is_file()
    assert Path(shot.last_save).parent == tmp_path / "rainshot"
    assert shot.closing and not shot.isVisible()
    saved_notice_manager().clear()


@pytest.mark.parametrize('pinned', [False, True])
def test_saved_corner_message_survives_deleted_shot(app, image, tmp_path, monkeypatch, pinned):
    import rainshot.floating as module
    monkeypatch.setattr(module.QStandardPaths, "writableLocation", lambda _: str(tmp_path))
    opened = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: opened.append(url) or True)
    shot = FloatingShot(image, pinned=pinned)
    shot.show_active()
    assert shot.corner_message.windowFlags() & Qt.WindowTransparentForInput
    shot.quick_save()
    expected = str(Path(shot.last_save).parent.absolute())
    assert shot.closing and not shot.isVisible()
    message = saved_notice_manager().notice
    assert message.owner is None and message.parent() is None
    assert message.action and '點擊開啟資料夾' in message.label.text()
    assert not message.windowFlags() & Qt.WindowTransparentForInput
    assert not message.windowHandle().flags() & Qt.WindowTransparentForInput
    assert message.windowFlags() & Qt.WindowDoesNotAcceptFocus
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    assert sip.isdeleted(shot) and message.isVisible()
    QTest.mouseClick(message, Qt.LeftButton, pos=message.rect().center())
    assert opened and opened[0].toLocalFile() == expected
    assert saved_notice_manager().notice is None
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(message)


def test_save_failure_keeps_shot_and_does_not_create_save_notice(app, image, tmp_path, monkeypatch):
    import rainshot.floating as module
    saved_notice_manager().clear()
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    def fail(*args):
        raise OSError('export failed')
    monkeypatch.setattr(module, 'save_image', fail)
    assert shot.save_to(tmp_path / 'failed.png') is False
    assert shot.isVisible() and not shot.closing
    assert 'export failed' in shot.status.text()
    assert saved_notice_manager().notice is None
    assert shot.corner_message.isVisible() and shot.corner_message.action is None
    shot.close()


def test_save_notice_replacement_snapshot_and_timeout_release(app, tmp_path):
    manager = saved_notice_manager()
    manager.clear()
    settings = QSettings(str(tmp_path / 'save.ini'), QSettings.IniFormat)
    settings.setValue('hint_corner', 'top-left')
    first = create_save_notice(tmp_path / 'first.png', settings, QPoint(10, 10), duration=0)
    settings.setValue('hint_corner', 'bottom-right')
    assert first.corner == 'top-left'
    second = create_save_notice(tmp_path / 'second.png', settings, QPoint(10, 10), duration=5)
    assert not first.isVisible() and second.isVisible()
    assert manager.notice is second and second.corner == 'bottom-right'
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(first)
    QTest.qWait(60)
    assert manager.notice is None
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(second)


def test_folder_open_failure_notice_survives_original_notice(app, image, tmp_path, monkeypatch):
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: False)
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    assert shot.save_to(tmp_path / 'saved.png')
    message = saved_notice_manager().notice
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(shot)
    QTest.mouseClick(message, Qt.LeftButton, pos=message.rect().center())
    failure = saved_notice_manager().notice
    assert failure is not None and failure is not message
    assert failure.isVisible() and failure.action is None
    assert '無法開啟' in failure.label.text()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(message)
    saved_notice_manager().clear()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(failure)


def test_recording_save_closes_target_without_restoring_or_activating_it(app, image, tmp_path, monkeypatch):
    from rainshot.app import Controller
    controller = Controller(app)
    other = controller.pin(image)
    shot = controller.pin(image)
    session = QObject(controller)
    controller.live_session, controller.live_target = session, shot
    controller.busy = shot.busy = True
    controller.hide_windows()
    restored, activated = [], []
    original_show = shot.show
    monkeypatch.setattr(shot, 'show', lambda: restored.append(True) or original_show())
    monkeypatch.setattr(shot, 'show_active', lambda: activated.append(True))
    path = tmp_path / 'recorded.gif'
    controller.end_session(session, path=str(path))
    assert not restored and not activated
    assert shot.closing and not shot.isVisible()
    assert other.isVisible() and not other.suspended
    assert not controller.busy and controller.live_session is None
    assert controller.settings.value('history', [], type=list)[0] == str(path)
    message = saved_notice_manager().notice
    assert message.isVisible() and message.action
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(shot) and sip.isdeleted(session)
    assert message.isVisible()
    saved_notice_manager().clear()
    other.close()
    controller.tray.hide()
    controller.hotkeys.close()
    controller.deleteLater()


def test_next_capture_clears_independent_save_notice_before_grabbing(app, image, tmp_path):
    from rainshot.app import Controller
    controller = Controller(app)
    shot = controller.pin(image)
    path = tmp_path / 'saved.png'
    assert shot.save_to(path)
    message = saved_notice_manager().notice
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(shot) and message.isVisible()
    controller.capture()
    controller.timer.stop()
    assert not message.isVisible() and saved_notice_manager().notice is None
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(message)
    controller.restore()
    controller.tray.hide()
    controller.hotkeys.close()
    controller.deleteLater()


def test_new_status_clears_owned_message_action(app, image, tmp_path, monkeypatch):
    import rainshot.floating as module
    monkeypatch.setattr(module.QStandardPaths, "writableLocation", lambda _: str(tmp_path))
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    shot.set_status('可點擊的一般提示', action=lambda: None)
    assert shot.corner_message.action
    shot.set_status('一般提示')
    assert shot.corner_message.action is None
    assert shot.corner_message.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert shot.corner_message.windowFlags() & Qt.WindowTransparentForInput
    assert shot.corner_message.windowHandle().flags() & Qt.WindowTransparentForInput
    shot.close()


def test_ocr_failure_inline(app, image, monkeypatch):
    import rainshot.ocr as module
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    shot.run_ocr()
    assert "OCR" in shot.status.text() and shot.ocr_job.done
    assert shot.mode == "pan"
    shot.close()


def test_stitch_close_while_worker_running(app, image, monkeypatch):
    import rainshot.stitch as module
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    def delayed(*args):
        QTest.qSleep(100)
        return image, 200
    monkeypatch.setattr(module, "stitch_pair", delayed)
    shot = FloatingShot(image, pinned=True)
    shot.show_active()
    shot.append_image(image)
    assert shot.close() and not shot.isVisible()
    QTest.qWait(250)
    assert not errors


def test_region_stays_at_capture_position(app, image):
    shot = FloatingShot(image, QRect(70, 90, 640, 400))
    assert shot.image_origin() == QPoint(70, 90)
    shot.show_active()
    before = shot.image_origin()
    shot.buttons["annotate"].click()
    assert shot.image_origin() == before
    shot.close()


def test_edge_selection_keeps_toolbar_on_screen(app):
    from PyQt5.QtGui import QImage
    image = QImage(70, 90, QImage.Format_ARGB32)
    image.fill(Qt.white)
    for x in [0, 720]:
        shot = FloatingShot(image, QRect(x, 80, 70, 90))
        assert shot.image_origin() == QPoint(x, 80)
        toolbar = QRect(shot.tools.mapToGlobal(QPoint()), shot.tools.size())
        assert app.primaryScreen().availableGeometry().contains(toolbar)
        shot.close()

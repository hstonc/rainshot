import io
import json
import numpy as np
import pytest
from PyQt5.QtCore import Qt, QPoint, QRect, QSettings
from PyQt5.QtGui import QImage, QColor, QPainter, QFont
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication
from rainshot.floating import FloatingShot
from rainshot.imaging import rgb_array
from rainshot.qr import decode, QrJob
from rainshot.scroll_capture import ScrollEngine, from_rgb
from rainshot.capture import SelectionOverlay
from rainshot.imaging import ScreenTile
from rainshot.translation import get_config, build_request, parse_result


def page(width=640, height=3000):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor('#f6f8fc'))
    p = QPainter(image)
    p.setFont(QFont('DejaVu Sans', 14))
    rng = np.random.default_rng(934)
    for row in range(0, height, 48):
        color = QColor(*map(int, rng.integers(10, 160, 3)))
        p.fillRect(20, row + 8, 35, 26, color)
        p.setPen(QColor('#202838'))
        p.drawText(75, row + 30, f'Row {row:04d}: rainshot test {rng.integers(100000, 999999)}')
        p.fillRect(width - 120, row + 5, 60, 3 + row % 32, color)
    p.end()
    return image


def viewport(image, offset, h=480, fixed=True):
    result = image.copy(0, offset, image.width(), h)
    if fixed:
        p = QPainter(result)
        p.fillRect(0, 0, image.width(), 45, QColor('#283e62'))
        p.fillRect(0, h - 32, image.width(), 32, QColor('#918ade'))
        p.setPen(Qt.white); p.drawText(20, 28, 'STICKY HEADER'); p.end()
    return result


def test_scroll_exact_pixels_fixed_footer_and_reverse(app):
    image = page()
    first = viewport(image, 0)
    engine = ScrollEngine(first)
    assert engine.append(first) == ('unchanged', 0)
    for offset in [80, 167, 311, 510, 680]:
        state, dy = engine.append(viewport(image, offset))
        assert state == 'added'
        assert engine.parts.shape == (480 + offset, 640, 3)
    expected = rgb_array(image.copy(0, 0, 640, 1160)).copy()
    expected[:45] = rgb_array(first)[:45]
    expected[-32:] = rgb_array(first)[-32:]
    assert np.array_equal(engine.parts, expected)
    assert engine.append(viewport(image, 510))[0] == 'up'
    assert engine.parts.shape[0] == 1160
    assert engine.append(viewport(image, 790)) == ('added', 110)


def test_scroll_dynamic_small_region_does_not_break_join(app):
    image = page()
    engine = ScrollEngine(viewport(image, 0))
    current = viewport(image, 130)
    p = QPainter(current); p.fillRect(420, 240, 50, 25, QColor('red')); p.end()
    assert engine.append(current) == ('added', 130)


def test_scroll_rejects_unrelated_and_can_resume(app):
    image = page()
    engine = ScrollEngine(viewport(image, 0))
    with pytest.raises(ValueError): engine.append(viewport(image, 1800))
    assert engine.steps == 0
    assert engine.append(viewport(image, 120)) == ('added', 120)


def qr_image(text):
    import qrcode
    stream = io.BytesIO()
    qrcode.make(text).save(stream, format='PNG')
    return QImage.fromData(stream.getvalue())


@pytest.mark.parametrize('angle', [0, 90, 180])
def test_qr_unicode_rotated_multiple_local(app, angle):
    from PyQt5.QtGui import QTransform
    first = qr_image('https://example.org/rainshot?測試=1')
    second = qr_image('WIFI:T:WPA;S:rainshot-test;P:synthetic-only;;')
    canvas = QImage(900, 500, QImage.Format_RGB32); canvas.fill(Qt.white)
    p = QPainter(canvas); p.drawImage(10, 10, first.transformed(QTransform().rotate(angle))); p.drawImage(470, 10, second); p.end()
    result = decode(canvas)
    assert {r['text'] for r in result} == {'https://example.org/rainshot?測試=1', 'WIFI:T:WPA;S:rainshot-test;P:synthetic-only;;'}
    assert all(len(r['points']) >= 4 for r in result)


def test_qr_job_and_cancel_cleanup(app, image):
    job = QrJob(qr_image('rainshot local QR'))
    done = QSignalSpy(job.finished); errors = QSignalSpy(job.failed)
    job.start()
    assert done.wait(5000) and done[0][0][0]['text'] == 'rainshot local QR' and not errors
    assert job.temp is None
    job.deleteLater()
    job = QrJob(image)
    job.start(); job.cleanup()
    assert job.done and job.temp is None
    job.deleteLater()


def test_pixel_color_after_zoom_and_shortcuts(app, tmp_path):
    image = QImage(640, 400, QImage.Format_RGB32); image.fill(QColor('#123456'))
    image.setPixelColor(123, 77, QColor('#ABCDEF'))
    settings = QSettings(str(tmp_path/'test.ini'), QSettings.IniFormat)
    shot = FloatingShot(image, QRect(0, 0, 640, 400), pinned=True, settings=settings)
    shot.show_active()
    shot.zoom_at(shot.image_origin(), 2)
    shot.toggle_color()
    shot.sample_color(QPoint(246, 154))
    assert shot.pixel_hex == '#ABCDEF'
    shot.copy_color(); assert QApplication.clipboard().text() == '#ABCDEF'
    assert np.array_equal(rgb_array(shot.document.render()), rgb_array(image))
    shot.activateWindow(); shot.surface.setFocus(); app.processEvents()
    QTest.keyClick(shot.surface, Qt.Key_I)
    assert shot.color_mode and not shot.corner_message.tutorial
    QTest.keyClick(shot.surface, Qt.Key_G)
    assert shot.record_row.isVisible()
    for key in ['qr', 'color', 'record', 'scroll', 'pin']:
        assert not shot.buttons[key].icon().isNull()
    shot.close()


def test_snap_click_drag_and_tab(app, tmp_path):
    image = QImage(800, 600, QImage.Format_RGB32); image.fill(Qt.white)
    settings = QSettings(str(tmp_path/'test.ini'), QSettings.IniFormat)
    overlay = SelectionOverlay([ScreenTile(QRect(0,0,800,600), image)], settings)
    overlay.snap_timer.stop()
    overlay.snap.windows = [{'id':12, 'pid':0, 'rect':QRect(100,100,300,200)}]
    overlay.update_hover(QPoint(150,150)); overlay.snap_timer.stop()
    assert overlay.selection == QRect(100,100,300,200)
    QTest.keyClick(overlay, Qt.Key_Tab)
    assert overlay.selection == QRect(0,0,800,600)
    # A Tab choice survives pointer jitter; entering another window resets it.
    overlay.update_hover(QPoint(500,500)); overlay.snap_timer.stop()
    overlay.update_hover(QPoint(150,150)); overlay.snap_timer.stop()
    selected = QSignalSpy(overlay.selected)
    QTest.mouseClick(overlay, Qt.LeftButton, pos=QPoint(150,150))
    assert selected[0][1] == QRect(100,100,300,200)
    overlay = SelectionOverlay([ScreenTile(QRect(0,0,800,600), image)], settings)
    selected = QSignalSpy(overlay.selected)
    QTest.mousePress(overlay, Qt.LeftButton, Qt.ShiftModifier, QPoint(40,50))
    QTest.mouseRelease(overlay, Qt.LeftButton, Qt.ShiftModifier, QPoint(240,200))
    assert selected[0][1] == QRect(40,50,201,151)


def test_default_free_translation_no_secrets(app, tmp_path):
    settings = QSettings(str(tmp_path/'test.ini'), QSettings.IniFormat)
    config = get_config(settings)
    assert config['provider'] == 'google' and not config['key']
    url, headers, raw = build_request(config, 'Hello + 測試 & x=y')
    from urllib.parse import urlparse, parse_qs
    assert parse_qs(urlparse(url.toString()).query)['q'] == ['Hello + 測試 & x=y']
    assert 'Authorization' not in headers and not raw
    assert parse_result('google', [[['你好','Hello'],['世界','world']],None,'en']) == '你好世界'
    assert parse_result('microsoft', [{'translations':[{'text':'你好'}]}]) == '你好'


def test_https_process_cancel_has_no_late_result(app, tmp_path, monkeypatch):
    import rainshot.translation as translation
    helper = tmp_path / 'translation_http.py'
    helper.write_text('import sys,time,json,base64\np=json.load(sys.stdin)\ntime.sleep(1)\nprint(json.dumps({"status":200,"body":base64.b64encode(b"[]").decode()}))\n')
    monkeypatch.setattr(translation, '__file__', str(tmp_path/'translation.py'))
    settings = QSettings(str(tmp_path/'api.ini'), QSettings.IniFormat)
    job = translation.TranslationJob(get_config(settings), 'synthetic cancellation test')
    done,failed = QSignalSpy(job.finished),QSignalSpy(job.failed)
    job.start(); QTest.qWait(60)
    assert job.process is not None
    job.cancel(); QTest.qWait(80)
    assert job.done and job.process is None and not done and not failed and job.text == ''
    job.deleteLater()


def test_settings_only_use_current_namespace(app, tmp_path, monkeypatch):
    import rainshot.config as config
    current = QSettings(str(tmp_path/'new.ini'),QSettings.IniFormat)
    current.setValue('hint_corner','bottom-left')
    current.setValue('migration/old_version',True)
    current.setValue('pixel_color',True)
    calls=[]
    monkeypatch.setattr(config,'QSettings',lambda *args:calls.append(args) or current)
    assert config.load_settings().value('hint_corner') == 'bottom-left'
    assert calls == [('rainshot','rainshot')]
    assert not current.contains('pixel_color') and not current.contains('migration/old_version')


def test_record_failure_without_capture_support_cleans_resources(app, monkeypatch, tmp_path):
    from rainshot.recording import RecordingSession
    recording = RecordingSession(QRect(0,0,300,200),{'format':'gif'},output_dir=tmp_path)
    failed = QSignalSpy(recording.failed)
    recording.start()
    assert failed and recording.done and recording.temp is None
    assert not recording.keys.display and not list(tmp_path.iterdir())
    recording.deleteLater()


def test_controller_cancel_before_session_start_restores_pin(app, image, monkeypatch):
    from rainshot.app import Controller
    from rainshot.scroll_capture import ScrollSession
    c = Controller(app)
    shot = c.edit(image, QRect(0,0,640,400), pinned=True)
    session = ScrollSession(shot.region, image, c)
    c.begin_session(session, shot)
    assert c.busy and not shot.isVisible()
    c.cancel_capture()
    assert not c.busy and c.live_session is None and shot.isVisible() and not shot.busy
    QTest.qWait(370)
    assert session.done
    c.close_shots();c.hotkeys.close();c.tray.hide();c.deleteLater()


def test_inline_scroll_controls_never_enter_capture(app, image, monkeypatch):
    import rainshot.scroll_capture as scroll
    from rainshot.imaging import ScreenTile
    session = scroll.ScrollSession(QRect(0,0,640,400),image)
    monkeypatch.setattr(session.controls,'reposition',lambda:False)
    calls = []
    monkeypatch.setattr(scroll,'grab_tiles',lambda: calls.append(True) or [ScreenTile(QRect(0,0,640,400),image)])
    monkeypatch.setattr(QApplication,'platformName',lambda:'offscreen')
    position = [QPoint(1,1)]
    monkeypatch.setattr(scroll.QCursor,'pos',lambda:position[0])
    session.start();session.timer.stop()
    assert session.inline_controls and session.controls.isVisible()
    session.capture()
    assert not session.controls.isVisible() and not calls
    session.capture()
    assert calls and session.worker
    while session.worker: QTest.qWait(20)
    position[0] = session.controls.geometry().center()
    count = len(calls);session.capture()
    assert session.controls.isVisible() and len(calls)==count
    session.cancel();session.deleteLater()

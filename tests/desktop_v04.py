"""Real X11 integration against this script's own synthetic test window."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from PIL import Image
from PyQt5.QtCore import Qt, QRect, QPoint, QTimer, QSettings
from PyQt5.QtGui import QPainter, QColor, QCursor
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtTest import QTest, QSignalSpy
from rainshot.capture import grab_tiles
from rainshot.imaging import compose_tiles, rgb_array
from rainshot.scroll_capture import ScrollSession
from rainshot.recording import RecordingSession
from rainshot.x11 import X11
from rainshot.floating import FloatingShot
from rainshot.settings_window import SettingsWindow
from rainshot.history import History
from rainshot.hotkeys import Hotkeys
from test_v04 import page, viewport, qr_image

out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
temp = tempfile.TemporaryDirectory(prefix='rainshot-desktop-v04-')
for key, suffix in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime')]:
    os.environ[key] = str(Path(temp.name)/suffix)
    Path(os.environ[key]).mkdir(mode=0o700)
app = QApplication([]); app.setQuitOnLastWindowClosed(False)
original_cursor = QCursor.pos()
report = {}


def wait_until(predicate, timeout=8000):
    start = time.monotonic()
    while not predicate() and time.monotonic() - start < timeout / 1000:
        QTest.qWait(30)
    assert predicate(), f'timed out: {timeout}'


class Source(QWidget):
    def __init__(self):
        super().__init__()
        self.offset = 0; self.tick = 0; self.animate = False
        self.image = page()
        self.setWindowTitle('rainshot synthetic capture test')
        self.setFixedSize(640, 480)
        self.move(app.primaryScreen().geometry().topLeft() + QPoint(40,80))
        self.timer = QTimer(self); self.timer.setInterval(120)
        self.timer.timeout.connect(self.advance)
    def paintEvent(self, event):
        p = QPainter(self); p.drawImage(0,0,viewport(self.image,self.offset))
        if self.animate:
            p.fillRect(80,90,400,250,QColor('#f16470' if self.tick % 2 else '#587add'))
            p.setPen(Qt.white); p.drawText(130,210,f'rainshot animation frame {self.tick}')
        p.end()
    def advance(self):
        self.tick += 1; self.update()
    def wheelEvent(self,event):
        self.offset += 70 if event.angleDelta().y() < 0 else -70
        self.offset = max(0,self.offset); self.update()


source = Source(); source.show(); source.raise_(); QTest.qWait(400)
region = QRect(source.mapToGlobal(QPoint()), source.size())
try:
    x = X11(); windows = x.windows(include_own=True); x.close()
    assert any(w['id'] == int(source.winId()) and w['rect'] == region for w in windows)
    report['x11_window_geometry'] = [region.x(),region.y(),region.width(),region.height()]
    initial = compose_tiles(grab_tiles(),region)
    session = ScrollSession(region, initial)
    completed, canceled, failed = QSignalSpy(session.completed), QSignalSpy(session.canceled), QSignalSpy(session.failed)
    session.start(); assert not failed
    for i, offset in enumerate([80,167,311,510]):
        source.offset = offset; source.update()
        wait_until(lambda: session.engine.steps >= i + 1)
    # Real passive grab while the original page has focus.
    import ctypes as C
    xlib=C.CDLL('libX11.so.6'); xt=C.CDLL('libXtst.so.6')
    xlib.XOpenDisplay.argtypes=[C.c_char_p];xlib.XOpenDisplay.restype=C.c_void_p
    xlib.XStringToKeysym.argtypes=[C.c_char_p];xlib.XStringToKeysym.restype=C.c_ulong
    xlib.XKeysymToKeycode.argtypes=[C.c_void_p,C.c_ulong];xlib.XKeysymToKeycode.restype=C.c_ubyte
    xlib.XFlush.argtypes=[C.c_void_p];xlib.XCloseDisplay.argtypes=[C.c_void_p]
    xt.XTestFakeKeyEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
    display=xlib.XOpenDisplay(None)
    source.activateWindow();QTest.qWait(100)
    keys=[xlib.XKeysymToKeycode(display,xlib.XStringToKeysym(name)) for name in [b'Control_L',b'Return']]
    for key in keys:xt.XTestFakeKeyEvent(display,key,1,0)
    for key in reversed(keys):xt.XTestFakeKeyEvent(display,key,0,0)
    xlib.XFlush(display);xlib.XCloseDisplay(display)
    wait_until(lambda: bool(completed))
    report['scroll_finish_shortcut'] = True
    result = completed[0][0]
    assert result.height() == 990 and result.width() == 640
    expected = rgb_array(source.image.copy(0,0,640,990)).copy()
    expected[:45] = rgb_array(initial)[:45]; expected[-32:] = rgb_array(initial)[-32:]
    import numpy as np
    result.save(str(out/'scroll-result.png'))
    from rainshot.scroll_capture import from_rgb
    from_rgb(expected).save(str(out/'scroll-expected.png'))
    difference = np.any(rgb_array(result) != expected,axis=2)
    ys,xs = np.where(difference)
    print('pixel diff',int(difference.sum()),'bbox',([int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())] if xs.size else []),flush=True)
    assert np.array_equal(rgb_array(result),expected)
    result.save(str(out/'scroll-result.png'))
    report['continuous_scroll'] = {'steps':4,'size':[640,990],'pixel_exact':True}
    session.deleteLater()
    # Cancel with a capture worker in flight, without deleting a running QThread.
    session = ScrollSession(region,compose_tiles(grab_tiles(),region)); session.start()
    session.capture(); session.cancel(); wait_until(lambda: session.done)
    assert session.worker is None
    session.deleteLater()
    report['scroll_cancel_worker'] = True
    source.offset = 0; source.update(); source.activateWindow(); QTest.qWait(150)
    session = ScrollSession(region,compose_tiles(grab_tiles(),region)); session.start()
    QCursor.setPos(region.center()); session.auto.setChecked(True)
    wait_until(lambda: session.engine.steps >= 2, 10000)
    QCursor.setPos(region.topLeft() - QPoint(30,30)); stopped_offset = source.offset
    QTest.qWait(900)
    assert source.offset == stopped_offset
    session.cancel(); wait_until(lambda: session.done); session.deleteLater()
    report['auto_scroll_and_pointer_pause'] = True

    source.animate = True; source.timer.start()
    for fmt in ['gif','webp']:
        recording = RecordingSession(region,dict(format=fmt,fps=10,duration=60 if fmt == 'gif' else 2,width=640), output_dir=out)
        if fmt == 'webp':
            recording.controls.reposition = lambda: False
        completed, failed = QSignalSpy(recording.completed), QSignalSpy(recording.failed)
        recording.start()
        if fmt == 'gif':
            QTimer.singleShot(1600, recording.finish)
        else:
            assert not recording.controls.isVisible()
        wait_until(lambda: bool(completed) or bool(failed),45000)
        assert not failed, list(failed)
        file = Path(completed[0][0]); im = Image.open(file)
        assert im.size == (640,480) and im.n_frames >= 10
        pixels = []
        for n in range(im.n_frames):
            im.seek(n); pixels.append(im.convert('RGB').getpixel((100,100)))
        assert len(set(pixels)) >= 2
        assert file.stat().st_mode & 0o777 == 0o600
        report[fmt] = {'size':im.size,'frames':im.n_frames,'bytes':file.stat().st_size,'colors':len(set(pixels)),'stop':'manual' if fmt=='gif' else 'duration limit with hidden controls'}
        recording.deleteLater()
    recording = RecordingSession(region,dict(format='gif',fps=10,duration=60),output_dir=out)
    recording.start(); QTest.qWait(300); recording.cancel()
    assert recording.temp is None and recording.staged_output is None and recording.done
    assert not list(out.glob('.rainshot-*'))
    recording.deleteLater()
    report['record_cancel_cleanup'] = True
    source.timer.stop(); source.hide()
    settings = QSettings(str(out/'preview-settings.ini'),QSettings.IniFormat)
    shot = FloatingShot(qr_image('https://example.org/rainshot'), pinned=True,settings=settings)
    shot.show_active(); shot.run_qr()
    wait_until(lambda: shot.result_row.isVisible())
    assert 'https://example.org/rainshot' in shot.result_text.toPlainText()
    QTest.qWait(200); shot.set_toolbar_visible(True); shot.toolbar_timer.stop(); shot.grab().save(str(out/'qr-panel.png'))
    shot.close()
    hotkeys = Hotkeys(); window = SettingsWindow(settings,History(settings,out/'history'),hotkeys)
    window.show(); QTest.qWait(200)
    window.grab().save(str(out/'settings-dark.png'))
    window.select_page(4); QTest.qWait(100)
    window.grab().save(str(out/'translation-settings.png'))
    window.close(); window.deleteLater(); hotkeys.close()
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
finally:
    source.close()
    QCursor.setPos(original_cursor)
    app.processEvents()

"""Native X11 checks using only our own synthetic windows and private settings."""
import ctypes as C
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint, QRect, QSettings, QTimer, QUrl, QEvent
from PyQt5.QtGui import QImage, QColor, QCursor, QPainter, QDesktopServices
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QMenu, QFileDialog
from PyQt5.QtTest import QTest, QSignalSpy
from rainshot.floating import FloatingShot
from rainshot.imaging import rgb_array
import numpy as np
from rainshot.settings_window import SettingsWindow
from rainshot.history import History
from rainshot.hotkeys import Hotkeys
from rainshot.recording import RecordingSession

out=Path(sys.argv[1]).resolve(); out.mkdir(parents=True,exist_ok=True)
temp=tempfile.TemporaryDirectory(prefix='rainshot-v041-native-')
for name in ('CONFIG','CACHE','RUNTIME'):
    path=Path(temp.name)/name.lower();path.mkdir(mode=0o700)
    os.environ['XDG_'+name+'_HOME' if name!='RUNTIME' else 'XDG_RUNTIME_DIR']=str(path)
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
settings=QSettings(str(Path(temp.name)/'settings.ini'),QSettings.IniFormat)
settings.setValue('save_directory',str(out/'custom-exports'))
settings.setValue('hints_enabled',False)
original=QCursor.pos()
report={}

def wait_until(predicate, timeout=5000):
    start=time.monotonic()
    while not predicate() and time.monotonic()-start<timeout/1000:
        QTest.qWait(30)
    assert predicate(), 'timeout'

class DropTarget(QLabel):
    def __init__(self):
        super().__init__('Synthetic browser upload area\nNative file drag target')
        self.urls=[];self.setAcceptDrops(True)
        self.setStyleSheet('background:#20334e;color:white;font-size:22px;padding:15px;')
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dragMoveEvent(self,event):event.acceptProposedAction()
    def dropEvent(self,event):
        self.urls=event.mimeData().urls()
        event.acceptProposedAction()

class Source(QWidget):
    def __init__(self):
        super().__init__(); self.tick=0
        self.timer=QTimer(self);self.timer.timeout.connect(self.advance);self.timer.start(90)
    def advance(self):self.tick+=1;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#5c65b3' if self.tick%2 else '#2f7463'))
        p.setPen(Qt.white);p.drawText(self.rect(),Qt.AlignCenter,'rainshot 0.4.2 synthetic animation '+str(self.tick))

bounds=app.primaryScreen().availableGeometry()
image=QImage(400,280,QImage.Format_RGB32)
for y in range(image.height()):
    for x in range(image.width()):image.setPixelColor(x,y,QColor(x%256,y%256,(x+y)%256))
image.setPixelColor(100,80,QColor('#abcdef'))
shot=FloatingShot(image,QRect(bounds.topLeft()+QPoint(70,70),image.size()),settings=settings)
keys=Hotkeys(); window=None; target=None; source=None
try:
    shot.show_active(); QTest.qWait(200)
    QCursor.setPos(shot.surface.mapToGlobal(QPoint(100,80)));QTest.qWait(100)
    assert not shot.magnifier.isVisible() and shot.pixel_hex is None
    shot.buttons['color'].click();QTest.qWait(100)
    QCursor.setPos(shot.surface.mapToGlobal(QPoint(100,80)));QTest.qWait(30)
    assert shot.magnifier.isVisible() and not shot.closing and shot.isActiveWindow()
    assert shot.pixel_hex=='#ABCDEF', (shot.pixel_hex,shot.pixel_point,shot.surface.mapFromGlobal(QCursor.pos()),shot.scale,shot.surface.size())
    shot.magnifier.grab().save(str(out/'pixel-magnifier.png'))
    shot.grab().save(str(out/'pixel-shot.png'))
    QTest.keyClick(shot.surface,Qt.Key_Right);QTest.keyClick(shot.surface,Qt.Key_Return)
    assert QApplication.clipboard().text()==image.pixelColor(101,80).name().upper()
    assert not shot.color_mode and not shot.magnifier.isVisible()
    shot.toggle_color()
    QTest.keyClick(shot.surface,Qt.Key_Escape)
    assert not shot.color_mode and not shot.closing and not shot.magnifier.isVisible()
    report['native_pixel_loupe']={'opt_in':True,'focus_preserved':True,'keyboard_exact_pixel':True,'escape_exits_mode':True}
    shot.quick_save();assert np.array_equal(rgb_array(QImage(shot.last_save)),rgb_array(image))
    report['custom_png_export']=shot.last_save
    shot.toggle_image_search()
    opened_search=[];saved_open=QDesktopServices.openUrl
    QDesktopServices.openUrl=lambda url:opened_search.append(url) or True
    shot.open_image_search()
    QDesktopServices.openUrl=saved_open
    assert shot.pinned and opened_search
    # Real OS drag with XTest; destination is our own widget, not a network service.
    target=DropTarget();target.resize(450,260);target.move(bounds.topLeft()+QPoint(650,90));target.show()
    shot.raise_();shot.activateWindow();QTest.qWait(200)
    xlib=C.CDLL('libX11.so.6');xt=C.CDLL('libXtst.so.6')
    xlib.XOpenDisplay.argtypes=[C.c_char_p];xlib.XOpenDisplay.restype=C.c_void_p
    xlib.XFlush.argtypes=[C.c_void_p];xlib.XCloseDisplay.argtypes=[C.c_void_p]
    xt.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
    display=xlib.XOpenDisplay(None)
    def release():
        xt.XTestFakeButtonEvent(display,1,0,0);xlib.XFlush(display)
    start=shot.search_drag.mapToGlobal(shot.search_drag.rect().center())
    QCursor.setPos(start);QTest.qWait(100)
    xt.XTestFakeButtonEvent(display,1,1,0);xlib.XFlush(display)
    QTimer.singleShot(120,lambda:QCursor.setPos(start+QPoint(25,0)))
    QTimer.singleShot(350,lambda:QCursor.setPos(target.mapToGlobal(target.rect().center())))
    QTimer.singleShot(650,release)
    wait_until(lambda:bool(target.urls))
    xlib.XCloseDisplay(display)
    assert np.array_equal(rgb_array(QImage(target.urls[0].toLocalFile())),rgb_array(image)) and shot.pinned
    report['native_file_drag']={'received_png':True,'pixel_exact':True,'automatic_pin':True}
    target.hide()
    opened=[];old_open=QDesktopServices.openUrl
    QDesktopServices.openUrl=lambda url:opened.append(url) or True
    shot.qr_complete([{'text':'https://example.com/first'},{'text':'https://example.org/second'}])
    shot.result_links.setCurrentIndex(1);shot.open_result_button.click()
    assert opened[-1].toString()=='https://example.org/second'
    shot.search_row.hide();shot.reflow();shot.grab().save(str(out/'qr-open.png'))
    report['qr_open_selected_url']=True
    shot.hide()
    history=History(settings,Path(temp.name)/'history');history.record(image)
    window=SettingsWindow(settings,history,keys);window.show();window.raise_();window.activateWindow();QTest.qWait(200)
    window.select_page(1);QTest.qWait(150)
    def trigger_context():
        menu=QApplication.activePopupWidget()
        assert isinstance(menu,QMenu)
        report['history_menu']=[a.text() for a in menu.actions()]
        menu.grab().save(str(out/'history-context.png'))
        menu.actions()[0].trigger();menu.close()
    QTimer.singleShot(200,trigger_context)
    position=window.history_list.visualItemRect(window.history_list.item(0)).center()
    window.history_menu(position)
    assert opened[-1].toLocalFile()==history.entries()[0]
    window.select_page(0);QTest.qWait(100);window.grab().save(str(out/'settings-general.png'))
    window.select_page(4);window.provider.setCurrentIndex(window.provider.findData('qwen-plus'));QTest.qWait(100)
    window.grab().save(str(out/'settings-qwen.png'));window.hide()
    QDesktopServices.openUrl=old_open
    # Actual encoders write a custom directory, not the default pictures path.
    source=Source();source.resize(400,280);source.move(bounds.topLeft()+QPoint(70,70));source.show();QTest.qWait(200)
    region=QRect(source.mapToGlobal(QPoint()),source.size())
    from PIL import Image
    for format in ('gif','webp'):
        session=RecordingSession(region,{'format':format,'fps':10,'duration':1,'width':400,'cursor':False},output_dir=settings.value('save_directory'))
        completed=QSignalSpy(session.completed);failed=QSignalSpy(session.failed)
        session.start();wait_until(lambda:bool(completed) or bool(failed),12000)
        assert completed and not failed, list(failed)
        path=Path(completed[0][0]);movie=Image.open(path)
        assert path.parent==out/'custom-exports' and movie.n_frames>1
        report[format+'_custom_export']={'frames':movie.n_frames,'size':list(movie.size)}
        session.deleteLater()
    report['result']='passed'
finally:
    QCursor.setPos(original)
    if source:source.close()
    if target:target.close()
    if window:window.hide();window.deleteLater()
    shot.close();keys.close();app.processEvents()
    (out/'native-v041.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))

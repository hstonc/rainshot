"""Native X11 checks of pointer transitions, focus, and passive hotkey grabs."""
import ctypes as C
import json
import sys
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint, QEvent, QSettings
from PyQt5.QtGui import QCursor, QImage, QColor, QPainter, QFont, QKeySequence
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtTest import QTest
from rainshot.floating import FloatingShot
from rainshot.hotkeys import Hotkeys
from rainshot.history import History
from rainshot.settings_window import SettingsWindow, ShortcutEdit

out=Path(sys.argv[1]).resolve()
out.mkdir(parents=True,exist_ok=True)
app=QApplication([])
app.setQuitOnLastWindowClosed(False)
assert app.platformName()=='xcb'
settings=QSettings(str(out/'desktop-test.ini'),QSettings.IniFormat)
previous=QCursor.pos()
x=C.CDLL('libX11.so.6'); xt=C.CDLL('libXtst.so.6')
x.XOpenDisplay.argtypes=[C.c_char_p]; x.XOpenDisplay.restype=C.c_void_p
x.XFlush.argtypes=[C.c_void_p]; x.XCloseDisplay.argtypes=[C.c_void_p]
x.XStringToKeysym.argtypes=[C.c_char_p]; x.XStringToKeysym.restype=C.c_ulong
x.XKeysymToKeycode.argtypes=[C.c_void_p,C.c_ulong]; x.XKeysymToKeycode.restype=C.c_ubyte
xt.XTestFakeMotionEvent.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_ulong]
xt.XTestFakeKeyEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
xt.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
d=x.XOpenDisplay(None)
assert d

def move(point,delay=350):
    xt.XTestFakeMotionEvent(d,-1,point.x(),point.y(),0); x.XFlush(d); QTest.qWait(delay)

def keycode(name): return x.XKeysymToKeycode(d,x.XStringToKeysym(name.encode()))
def chord(name,held=40):
    codes=[keycode(k) for k in ['Control_L','Alt_L','Shift_L',name]]
    for code in codes: xt.XTestFakeKeyEvent(d,code,True,0)
    x.XFlush(d); QTest.qWait(held)
    for code in reversed(codes): xt.XTestFakeKeyEvent(d,code,False,0)
    x.XFlush(d); QTest.qWait(180)

first,second=Hotkeys(),Hotkeys()
shot=window=None
try:
    screen=app.primaryScreen().availableGeometry()
    image=QImage(660,330,QImage.Format_ARGB32); image.fill(QColor('#f7faf3'))
    p=QPainter(image); p.setPen(QColor('#203b37')); p.setFont(QFont('Noto Sans CJK TC',22))
    p.drawText(35,90,'rainshot 0.4 · 工具列與提示')
    p.setFont(QFont('Noto Sans CJK TC',14)); p.drawText(35,155,'釘住後移開滑鼠，工具列自動收起。')
    p.drawText(35,195,'移回貼圖，繼續選字、標註或翻譯。'); p.end()
    shot=FloatingShot(image,settings=settings)
    shot.show_active(); QTest.qWait(450)
    assert shot.isActiveWindow() and not shot.closing and shot.corner_message.isVisible()
    assert shot.corner_message.windowFlags() & Qt.WindowDoesNotAcceptFocus
    # A real click inside a native combo popup must not dismiss a transient shot.
    shot.translation_row.show(); shot.reflow()
    shot.translation_provider.showPopup(); QTest.qWait(120)
    view=shot.translation_provider.view()
    point=view.viewport().mapToGlobal(view.visualRect(view.model().index(shot.translation_provider.findData('youdao'),0)).center())
    move(point,50)
    xt.XTestFakeButtonEvent(d,1,True,0); x.XFlush(d); QTest.qWait(25)
    xt.XTestFakeButtonEvent(d,1,False,0); x.XFlush(d); QTest.qWait(200)
    assert not shot.closing and shot.translation_provider.currentData()=='youdao'
    shot.translation_row.hide(); shot.reflow()
    move(shot.surface.mapToGlobal(QPoint(180,120)))
    shot.toggle_pin(); origin=shot.image_origin(); QTest.qWait(350)
    assert not shot.corner_message.isVisible() and shot.tools.isVisible()
    # Crossing the 7px gap must not collapse the toolbar under the pointer.
    gap=shot.surface.mapToGlobal(QPoint(shot.surface.width()//2,shot.surface.height()+3))
    move(gap,70)
    move(shot.tools.mapToGlobal(QPoint(180,15)),350)
    assert shot.tools.isVisible() and shot.image_origin()==origin
    outside=QPoint(screen.right()-15,screen.top()+15)
    move(outside,500)
    assert not shot.tools.isVisible() and shot.image_origin()==origin
    move(shot.surface.mapToGlobal(QPoint(150,100)),350)
    assert shot.tools.isVisible() and shot.image_origin()==origin
    # Native combo popup must survive focus changes and remain reachable.
    shot.translation_row.show(); shot.reflow()
    shot.translation_provider.showPopup(); QTest.qWait(150)
    assert shot.owned_popup()
    shot.check_toolbar(); assert shot.tools.isVisible()
    shot.translation_provider.hidePopup(); shot.translation_row.hide(); shot.reflow()
    shot.grab().save(str(out/'floating-toolbar.png'))
    shot.close(); QTest.qWait(100)
    shot=None
    chosen=None
    for name in ['F10','F11','F12','F9']:
        sequence='Ctrl+Alt+Shift+'+name
        if not first.apply({'region':sequence}):
            chosen=name; break
    assert chosen, 'No unused test hotkey available'
    assert second.apply({'full':'Ctrl+Alt+Shift+'+chosen}), 'Conflict was not detected'
    seen=[]; first.activated.connect(seen.append)
    target=QWidget(); target.setWindowTitle('rainshot keyboard test'); target.show(); target.activateWindow(); QTest.qWait(250)
    chord(chosen,900)
    assert seen==['region'], ('Held key repeated',seen)
    field=ShortcutEdit(QKeySequence(),first); field.setParent(target); field.show(); field.setFocus(); QTest.qWait(150)
    assert first.paused and not first.bindings
    chord(chosen)
    assert seen==['region'] and field.keySequence().toString()=='Ctrl+Alt+Shift+'+chosen
    field.clearFocus(); QTest.qWait(100)
    assert not first.paused and first.bindings
    chord(chosen)
    assert seen==['region','region']
    assert not first.apply({})
    assert not second.apply({'full':'Ctrl+Alt+Shift+'+chosen})
    second.apply({}); target.close()
    window=SettingsWindow(settings,History(settings,out/'history-cache'),first)
    window.show(); QTest.qWait(250)
    for index,name in [(0,'settings-general'),(1,'settings-history'),(2,'settings-shortcuts'),(3,'settings-ocr'),(4,'settings-translation')]:
        window.select_page(index); QTest.qWait(100)
        window.grab().save(str(out/(name+'.png')))
    report={'hint_focus':'nonactivating; transient remains active', 'transient_popup_click':'selection delivered; shot preserved', 'pin_dismisses_hint':True,
            'toolbar':'hides on exit, restores on enter, gap and popup remain usable',
            'image_origin':'unchanged across toolbar transitions','hotkey_activation':'global; held key fires once',
            'hotkey_conflict':'detected without replacing existing binding',
            'hotkey_recording':'temporarily releases own grabs; restores afterward',
            'hotkey_release':'another instance can acquire after clearing'}
    (out/'desktop-v0.3.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
finally:
    if shot: shot.close()
    if window: window.close()
    first.close(); second.close()
    xt.XTestFakeMotionEvent(d,-1,previous.x(),previous.y(),0); x.XFlush(d); x.XCloseDisplay(d)

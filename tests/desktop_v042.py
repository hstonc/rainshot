"""Native Qt 0.4.2 UI checks against synthetic images and local translation only."""
import json,os,sys,tempfile,time,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PyQt5.QtCore import Qt,QPoint,QPointF,QRectF,QSettings
from PyQt5.QtGui import QImage,QPainter,QColor,QFont,QFontMetricsF,QCursor,QKeySequence,QInputMethodEvent
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from rainshot.floating import FloatingShot
from rainshot.ocr_layout import Word
from rainshot.settings_window import SettingsWindow
from rainshot.history import History
from rainshot.hotkeys import Hotkeys

out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
temp=tempfile.TemporaryDirectory(prefix='rainshot-v042-native-')
for variable,suffix in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime')]:
    path=Path(temp.name)/suffix;path.mkdir(mode=0o700);os.environ[variable]=str(path)
requests=[]
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(data)
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        result={'Hello world':'你好世界','Capture text':'截圖文字'}.get(data['q'],'翻譯結果')
        self.wfile.write(json.dumps({'translatedText':result}).encode())
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
assert app.platformName()=='xcb'
settings=QSettings(str(Path(temp.name)/'settings.ini'),QSettings.IniFormat)
settings.setValue('translation/provider','libre')
settings.setValue('translation/libre/endpoint',f'http://127.0.0.1:{server.server_address[1]}/translate')
settings.setValue('save_directory',str(out))
image=QImage(720,400,QImage.Format_ARGB32);image.fill(QColor('#f5f6fa'))
p=QPainter(image);font=QFont('Noto Sans CJK TC');font.setPixelSize(30);p.setFont(font);p.setPen(QColor('#15171d'))
p.drawText(40,84,'Hello world');p.drawText(40,164,'Capture text');p.end()
shot=FloatingShot(image,pinned=True,settings=settings);keys=Hotkeys();window=None;original=QCursor.pos();report={}
try:
    shot.show_active();QTest.qWait(180)
    shot.ocr_complete([Word('Hello world',QFontMetricsF(font).tightBoundingRect('Hello world').translated(40,84),(1,),100),Word('Capture text',QFontMetricsF(font).tightBoundingRect('Capture text').translated(40,164),(2,),100)],'eng')
    shot.activateWindow();shot.surface.setFocus();QTest.qWait(100)
    QTest.keyClick(shot.surface,Qt.Key_T)
    start=time.monotonic()
    while shot.translation_image is None and time.monotonic()-start<10:QTest.qWait(30)
    assert shot.translation_image is not None,shot.status.text()
    assert [r['q'] for r in requests]==['Hello world','Capture text']
    assert all(set(r).issubset({'q','source','target','format'}) for r in requests)
    shot.select_all();shot.copy();assert QApplication.clipboard().text()=='你好世界\n截圖文字'
    shot.set_toolbar_visible(True);shot.grab().save(str(out/'translated-shot.png'))
    shot.quick_save();assert QImage(shot.last_save)==shot.render_image()
    shot.buttons['original_text'].click();assert shot.render_image()==image
    report['positioned_translation']={'local_http_lines':2,'original_boxes':True,'select_copy_export_restore':True}
    shot.buttons['annotate'].click();assert shot.mode=='arrow'
    shot.color_buttons['#1ba78f'].click();shot.width_slider.setValue(6)
    QTest.mousePress(shot.surface,Qt.LeftButton,pos=QPoint(360,70));QTest.mouseRelease(shot.surface,Qt.LeftButton,pos=QPoint(530,130))
    assert len(shot.document.marks)==1 and shot.document.marks[0].color=='#1ba78f'
    shot.annotation_undo.click();assert not shot.document.marks
    shot.annotation_redo.click();assert len(shot.document.marks)==1
    shot.set_mode('text');shot.begin_text(QPointF(40,230))
    event=QInputMethodEvent();event.setCommitString('直接輸入文字')
    app.sendEvent(shot.text_input,event)
    QTest.keyClick(shot.text_input,Qt.Key_Return,Qt.ShiftModifier);QTest.keyClicks(shot.text_input,'Shift+Enter = new line')
    QTest.qWait(100);shot.grab().save(str(out/'inline-text-editing.png'))
    QTest.keyClick(shot.text_input,Qt.Key_Return)
    assert not shot.text_input.isVisible() and len(shot.document.marks)==2
    assert shot.document.marks[-1].text=='直接輸入文字\nShift+Enter = new line'
    shot.grab().save(str(out/'annotations-confirmed.png'))
    shot.buttons['annotate'].click();assert shot.mode=='pan' and not shot.annotation_row.isVisible()
    QTest.mousePress(shot.surface,Qt.LeftButton,pos=QPoint(380,200));QTest.mouseRelease(shot.surface,Qt.LeftButton,pos=QPoint(530,250))
    assert len(shot.document.marks)==2
    report['annotation_and_text']={'marked_color':True,'slider':6,'undo_redo':True,'hidden_tools_inactive':True,'inline_ime_and_multiline_enter':True}
    window=SettingsWindow(settings,History(settings,Path(temp.name)/'history'),keys)
    window.changed.connect(shot.refresh_shortcuts)
    window.show();window.select_page(5);window.activateWindow();QTest.qWait(150)
    field=window.local_key_fields['pin'];field.setFocus();QTest.keyClick(field,Qt.Key_F6);QTest.qWait(1100)
    assert field.keySequence().toString()=='F6'
    window.apply_local_shortcuts()
    assert settings.value('local_shortcuts/pin')=='F6'
    window.grab().save(str(out/'local-shortcut-settings.png'))
    window.hide();shot.show_active();shot.activateWindow();shot.surface.setFocus();QTest.qWait(150)
    QTest.keyClick(shot.surface,Qt.Key_F6);assert not shot.pinned
    QTest.keyClick(shot.surface,Qt.Key_F6);assert shot.pinned
    assert 'F6' in shot.buttons['pin'].toolTip() and 'F6' in shot.corner_message.label.text()
    shot.toggle_color();shot.sample_color(QPoint(10,10))
    expected_color=shot.pixel_hex
    QTest.keyClick(shot.surface,Qt.Key_C)
    assert QApplication.clipboard().text()==expected_color
    assert not shot.color_mode and not shot.magnifier.isVisible() and not shot.closing
    report['copy_color_exits_mode']=True
    report['custom_local_shortcuts']={'native_key_recording':True,'applied_to_open_shot':True,'hint_and_tooltip_updated':True}
    report['result']='passed'
finally:
    QCursor.setPos(original)
    if window:window.hide();window.deleteLater()
    shot.close();keys.close();app.processEvents()
    server.shutdown();server.server_close();thread.join(timeout=2)
    (out/'native-v042.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))

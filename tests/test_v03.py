import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
import pytest
from PyQt5.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QSettings, QSize, QEvent
from PyQt5.QtGui import QCursor
from PyQt5.QtTest import QTest, QSignalSpy
from PyQt5.QtWidgets import QApplication
from rainshot.app import Controller, startup_mode
from rainshot.floating import FloatingShot
from rainshot.hints import corner_position, CORNERS
from rainshot.history import History
from rainshot.hotkeys import Hotkeys, key_parts
from rainshot.ocr_layout import Word
from rainshot.settings_window import SettingsWindow, OCR_COMMAND
from rainshot.translation import TranslationJob, PROVIDERS, build_request, validate_url, get_config

@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)

def test_startup_without_flags_is_idle():
    assert startup_mode(argparse.Namespace()) == 'tray'
    for flag, mode in [('capture','region'), ('settings','show'), ('history','history')]:
        assert startup_mode(argparse.Namespace(**{flag: True})) == mode

def test_settings_open_via_tray_without_capture(app, monkeypatch):
    c = Controller(app)
    requests = []
    monkeypatch.setattr(c, 'capture', lambda *args: requests.append(args))
    c.dispatch({})
    c.dispatch({'mode':'tray'})
    assert c.control_center is None and not requests
    next(a for a in c.menu.actions() if a.text() == '設定…').trigger()
    assert c.control_center.isVisible() and not requests and not c.windows
    c.dispatch({'mode':'history'})
    assert c.control_center.pages.currentIndex() == 1
    c.control_center.close()
    assert not c.control_center.isVisible() and not requests
    c.control_center.deleteLater()
    c.hotkeys.close()
    c.tray.hide()
    c.deleteLater()

def test_history_bounded_private_and_saved_files_preserved(app, settings, tmp_path, image):
    h = History(settings, tmp_path / 'cache')
    settings.setValue('history_limit', 2)
    files = [h.record(image) for _ in range(3)]
    assert len(h.captures()) == 2 and not Path(files[0]).exists()
    assert Path(files[1]).stat().st_mode & 0o777 == 0o600
    external = tmp_path / 'saved.png'
    image.save(str(external))
    settings.setValue('history', [str(external)])
    assert str(external) in h.entries()
    settings.setValue('capture_history_enabled', False)
    assert h.record(image) is None
    h.clear()
    assert not h.entries() and external.exists()

def test_settings_persist_copy_and_session_credentials(app, settings, tmp_path):
    hotkeys = Hotkeys()
    w = SettingsWindow(settings, History(settings, tmp_path), hotkeys)
    w.show()
    w.corner.setCurrentIndex(w.corner.findData('top-left'))
    assert settings.value('hint_corner') == 'top-left'
    w.hints_check.setChecked(False)
    assert not settings.value('hints_enabled', True, type=bool)
    w.select_page(3)
    w.ocr_copy.click()
    assert QApplication.clipboard().text() == OCR_COMMAND
    w.select_page(4)
    w.provider.setCurrentIndex(w.provider.findData('deepl-free'))
    w.api_key.setText('synthetic-key-one')
    w.provider.setCurrentIndex(w.provider.findData('youdao'))
    w.api_key.setText('synthetic-key-two')
    w.appid.setText('test-app')
    w.save_translation()
    assert get_config(settings, 'deepl-free')['key'] == 'synthetic-key-one'
    assert get_config(settings, 'youdao')['appid'] == 'test-app'
    settings.sync()
    assert 'synthetic' not in Path(settings.fileName()).read_text()
    w.close()
    w.deleteLater()
    hotkeys.close()

@pytest.mark.parametrize('corner', [code for _, code in CORNERS])
def test_hint_offset_monitor_corners(corner):
    screen, size = QRect(-1600,180,1600,900), QSize(400,80)
    p = corner_position(screen,size,corner)
    assert screen.contains(QRect(p,size))
    assert p.x() == (-1578 if corner.endswith('left') else -422)
    assert p.y() == (202 if corner.startswith('top') else 978)

@pytest.mark.parametrize('action', ['pin','annotate','ocr','copy','pan'])
def test_tutorial_separate_and_dismisses(app, settings, image, action):
    s = FloatingShot(image,settings=settings)
    s.show_active()
    app.processEvents()
    assert s.corner_message.isVisible() and s.corner_message.tutorial
    assert not s.tools.isAncestorOf(s.status)
    assert all(not s.buttons[k].icon().isNull() for k in ('pin','ocr','translate','save','copy','close'))
    if action == 'pin': s.toggle_pin()
    elif action == 'annotate': s.set_mode('arrow')
    elif action == 'ocr': s.set_mode('ocr')
    elif action == 'copy': s.copy()
    else:
        QTest.mousePress(s.surface,Qt.LeftButton,pos=QPoint(50,50))
        QTest.mouseRelease(s.surface,Qt.LeftButton,pos=QPoint(50,50))
    assert not s.corner_message.isVisible() or not s.corner_message.tutorial
    s.close()

def test_pin_toolbar_hides_without_moving_image(app, image, monkeypatch):
    s = FloatingShot(image,pinned=True)
    s.show_active()
    origin = s.image_origin()
    monkeypatch.setattr(QCursor,'pos',lambda:QPoint(-10000,-10000))
    s.check_toolbar()
    assert not s.toolbar_visible and not s.tools.isVisible()
    assert s.image_origin() == origin and s.mask().boundingRect() == s.surface.geometry()
    QApplication.sendEvent(s.surface,QEvent(QEvent.Enter))
    assert s.tools.isVisible() and s.image_origin() == origin
    monkeypatch.setattr(QCursor,'pos',lambda:s.tools.mapToGlobal(QPoint(15,15)))
    s.check_toolbar()
    assert s.toolbar_visible
    s.toggle_pin()
    monkeypatch.setattr(QCursor,'pos',lambda:QPoint(-10000,-10000))
    s.check_toolbar()
    assert s.toolbar_visible
    s.close()

@pytest.mark.parametrize('sequence',['Ctrl+Alt+A','Print','Ctrl+Shift+F8','Meta+Q'])
def test_hotkey_valid(sequence):
    assert key_parts(sequence)[0]

@pytest.mark.parametrize('sequence',['A','Shift+A','Ctrl+A, Ctrl+B',''])
def test_hotkey_rejects_text_interception(sequence):
    with pytest.raises(ValueError): key_parts(sequence)

@pytest.fixture
def service():
    state = {'status':200,'response':{'translatedText':'你好'},'requests':[],'delay':0}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length',0)))
            state['requests'].append((self.path,dict(self.headers),raw))
            time.sleep(state['delay'])
            self.send_response(state['status'])
            if state['status'] == 302: self.send_header('Location',state['base']+'/redirect-target')
            self.send_header('Content-Type','application/json')
            self.end_headers()
            try:
                data = state['response']
                self.wfile.write(data if isinstance(data,bytes) else json.dumps(data).encode())
            except (BrokenPipeError,ConnectionResetError): pass
        do_GET = do_POST
        def log_message(self,*args): pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    state['base'] = f'http://127.0.0.1:{server.server_address[1]}'
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)

def config(provider='libre',endpoint='http://127.0.0.1:5000/translate'):
    return dict(provider=provider,endpoint=endpoint,key='synthetic',appid='test-app',source='auto',target='zh-TW',model='test-model')

@pytest.mark.parametrize('provider',PROVIDERS)
def test_provider_http_contract(app,service,provider):
    if provider == 'google': response=[[['譯文', 'Hello world']], None, 'en']
    elif provider == 'microsoft': response=[{'translations':[{'text':'譯文','to':'zh-Hant'}]}]
    elif provider.startswith('deepl'): response={'translations':[{'text':'譯文'}]}
    elif provider == 'youdao': response={'errorCode':'0','translation':['譯文']}
    elif provider == 'libre': response={'translatedText':'譯文'}
    else: response={'choices':[{'message':{'content':'譯文'}}]}
    service['response']=response
    job=TranslationJob(config(provider,service['base']+'/translate'),'Hello world')
    done,failed=QSignalSpy(job.finished),QSignalSpy(job.failed)
    job.start()
    assert done.wait(3000) and done[0][0]=='譯文' and not failed
    path,headers,raw=service['requests'][0]
    assert path.split('?')[0]=='/translate'
    if provider == 'google':
        assert parse_qs(path.split('?')[1])['q'] == ['Hello world'] and not raw
        assert 'Authorization' not in headers
    elif provider == 'microsoft':
        assert json.loads(raw) == ['Hello world'] and path.endswith('?to=zh-Hant')
        assert 'Authorization' not in headers
    elif provider=='youdao':
        data=parse_qs(raw.decode())
        assert data['q']==['Hello world'] and data['to']==['zh-CHT'] and data['signType']==['v3']
    else:
        data=json.loads(raw)
        if provider.startswith('deepl'):
            assert data['text']==['Hello world'] and data['target_lang']=='ZH-HANT' and 'source_lang' not in data
            assert headers['Authorization']=='DeepL-Auth-Key synthetic'
        elif provider=='libre': assert data['q']=='Hello world' and data['target']=='zt'
        else:
            assert data['messages'][-1]=={'role':'user','content':'Hello world'}
            assert headers['Authorization']=='Bearer synthetic'
    assert job.reply is None and job.done
    job.deleteLater()

def test_youdao_signature_unicode_length():
    text='rainshot你好🙂'*8
    _,_,body=build_request(config('youdao'),text,salt='fixed-salt',timestamp='1234567890')
    part=text[:10]+str(len(text))+text[-10:]
    expected=hashlib.sha256(('test-app'+part+'fixed-salt1234567890synthetic').encode()).hexdigest()
    assert parse_qs(body.decode())['sign']==[expected]

@pytest.mark.parametrize('url',['http://remote.example/translate','https://user:password@example.com/api','https://example.com/api?key=a','file:///tmp/file'])
def test_invalid_endpoint(url):
    with pytest.raises(ValueError): validate_url(url)

@pytest.mark.parametrize('status',[401,403,429,456,500,302])
def test_http_errors_no_redirect(app,service,status):
    service['status']=status
    job=TranslationJob(config(endpoint=service['base']+'/translate'),'Hello')
    failed=QSignalSpy(job.failed)
    job.start()
    assert failed.wait(2000) and str(status) in failed[0][0]
    assert len(service['requests'])==1 and 'synthetic' not in failed[0][0]
    job.deleteLater()

@pytest.mark.parametrize('response',[b'not-json',[],{'translatedText':None},{'translatedText':''}])
def test_malformed_response(app,service,response):
    service['response']=response
    job=TranslationJob(config(endpoint=service['base']+'/translate'),'Hello')
    failed=QSignalSpy(job.failed)
    job.start()
    assert failed.wait(2000)
    job.deleteLater()

def test_translation_timeout_is_bounded(app,service):
    service['delay']=.2
    job=TranslationJob(config(endpoint=service['base']+'/translate'),'Hello')
    job.timer.setInterval(40)
    failed,done=QSignalSpy(job.failed),QSignalSpy(job.finished)
    job.start()
    assert failed.wait(1000) and '逾時' in failed[0][0] and job.reply is None
    QTest.qWait(240)
    assert not done and len(failed)==1
    job.deleteLater()

def test_selected_translation_and_close_during_request(app,settings,image,service):
    settings.setValue('translation/provider','libre')
    settings.setValue('translation/libre/endpoint',service['base']+'/translate')
    s=FloatingShot(image,pinned=True,settings=settings)
    s.show_active()
    s.ocr_complete([Word('Hello',QRectF(10,10,50,20),(1,1,1,1),99),Word('world',QRectF(90,10,50,20),(1,1,1,1),99)],'eng')
    s.selection.select_word(QPointF(15,15))
    s.run_translation()
    done=QSignalSpy(s.translation_job.finished)
    assert done.wait(2000)
    assert json.loads(service['requests'][0][2])['q']=='Hello'
    assert s.translation_output.toPlainText()=='你好'
    s.copy_translation()
    assert QApplication.clipboard().text()=='你好'
    service['delay']=.2
    s.translate_selection()
    job=s.translation_job
    s.close()
    assert job.done and job.current is None
    QTest.qWait(300)

def test_edit_invalidates_ocr_and_translation(app,image):
    from rainshot.imaging import Mark
    s=FloatingShot(image,pinned=True)
    s.show_active()
    s.translation_output.setPlainText('Old translation')
    s.add_mark(Mark('rect',((10,10),(100,100))))
    assert not s.translation_output.toPlainText() and s.selection is None
    s.close()

@pytest.mark.parametrize('row',['annotation_row','ocr_row','translation_row'])
def test_expanded_rows_are_not_clipped(app,image,row):
    shot=FloatingShot(image,pinned=True)
    shot.show_active()
    widget=getattr(shot,row)
    widget.show()
    shot.reflow()
    app.processEvents()
    assert shot.tools.rect().contains(widget.geometry())
    assert shot.tools.height() >= shot.tools.layout().minimumSize().height()
    if row=='translation_row':
        assert not shot.translation_output.isVisible()
        assert widget.height() < 100
    shot.set_toolbar_visible(False)
    shot.set_toolbar_visible(True)
    app.processEvents()
    assert shot.tools.rect().contains(widget.geometry())
    shot.close()

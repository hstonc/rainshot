"""Behavioral regressions for explicit picking, exports and browser handoff."""
import json
from pathlib import Path
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QSettings, QPoint, QRect, Qt, QUrl
from PyQt5.QtGui import QColor, QImage, QDesktopServices
from PyQt5.QtTest import QTest, QSignalSpy
from PyQt5.QtWidgets import QApplication, QFileDialog, QMenu
from rainshot.floating import FloatingShot
from rainshot.settings_window import SettingsWindow
from rainshot.history import History
from rainshot.hotkeys import Hotkeys
from rainshot.config import save_directory, copy_original
from rainshot.image_search import web_url, prepare_image, image_mime
from rainshot.translation import get_config, build_request, parse_result
from rainshot.hints import saved_notice_manager


@pytest.fixture
def settings(tmp_path):
    result = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
    result.setValue('save_directory', str(tmp_path/'exports'))
    return result


@pytest.fixture
def shot(app, settings):
    image = QImage(320, 240, QImage.Format_RGB32)
    image.fill(QColor('#123456'))
    image.setPixelColor(100, 80, QColor('#abcdef'))
    image.setPixelColor(101, 80, QColor('#fedcba'))
    w = FloatingShot(image, QRect(0, 0, 320, 240), pinned=True, settings=settings)
    w.show_active(); app.processEvents()
    yield w
    if not sip.isdeleted(w):
        w.close()
    saved_notice_manager().clear()
    app.processEvents()


@pytest.fixture
def window(app, settings, tmp_path):
    keys = Hotkeys()
    w = SettingsWindow(settings, History(settings, tmp_path/'cache'), keys)
    w.show(); app.processEvents()
    yield w
    w.close(); w.deleteLater(); keys.close(); app.processEvents()


def test_explicit_pixel_mode_zoom_nudge_edges_and_escape(app, shot):
    shot.sample_color(QPoint(100,80))
    assert shot.pixel_hex is None and not shot.magnifier.isVisible()
    shot.buttons['color'].click()
    shot.zoom_at(shot.image_origin(), 2)
    shot.sample_color(QPoint(200,160))
    assert shot.pixel_hex == '#ABCDEF' and shot.pixel_point == QPoint(100,80)
    assert shot.magnifier.isVisible()
    shot.activateWindow(); shot.surface.setFocus(); app.processEvents()
    QTest.keyClick(shot.surface, Qt.Key_Right)
    assert shot.pixel_point == QPoint(101,80) and shot.pixel_hex == '#FEDCBA'
    QTest.keyClick(shot.surface, Qt.Key_Return)
    assert QApplication.clipboard().text() == '#FEDCBA'
    assert not shot.color_mode and not shot.magnifier.isVisible()
    shot.toggle_color()
    shot.show_pixel(QPoint(-200,-20), QPoint(0,0))
    assert shot.pixel_point == QPoint(0,0)
    shot.nudge_color(-1,-1)
    assert shot.pixel_point == QPoint(0,0)
    shot.show_pixel(QPoint(999,999), QPoint(799,599))
    assert shot.pixel_point == QPoint(319,239)
    assert QApplication.primaryScreen().availableGeometry().contains(shot.magnifier.geometry())
    QTest.keyClick(shot.surface, Qt.Key_Escape)
    assert not shot.color_mode and not shot.magnifier.isVisible() and not shot.closing
    shot.sample_color(QPoint(100,80))
    assert shot.pixel_hex is None


def test_leaving_and_editing_hide_magnifier(shot):
    shot.toggle_color(); shot.sample_color(QPoint(100,80))
    shot.set_mode('rect')
    assert not shot.magnifier.isVisible() and not shot.color_mode
    assert shot.document.render().pixelColor(100,80).name() == '#abcdef'


def test_custom_save_location_png_and_save_as_defaults(shot, settings, monkeypatch):
    calls = []
    def dialog(*args):
        calls.append(args)
        return '', ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', dialog)
    shot.save_as()
    assert Path(calls[0][2]).parent == save_directory(settings)
    assert not shot.closing
    shot.quick_save()
    assert Path(shot.last_save).parent == save_directory(settings)
    assert QImage(shot.last_save).pixelColor(100,80).name() == '#abcdef'
    assert shot.closing


def test_ask_save_path_setting_defaults_off_and_persists(window, settings):
    folder = save_directory(settings)
    assert not window.ask_save_path_check.isChecked()
    changed = QSignalSpy(window.changed)
    window.ask_save_path_check.setChecked(True)
    settings.sync()
    stored = QSettings(settings.fileName(), QSettings.IniFormat)
    assert stored.value('ask_save_path', False, type=bool)
    assert len(changed) == 1 and save_directory(settings) == folder
    window.ask_save_path_check.setChecked(False)
    assert not settings.value('ask_save_path', True, type=bool)
    assert len(changed) == 2 and save_directory(settings) == folder


@pytest.mark.parametrize('entry, selected, suffix', [
    ('button', 'PNG (*.png)', '.png'),
    ('shortcut', 'JPEG (*.jpg)', '.jpg'),
    ('direct', 'WebP (*.webp)', '.webp'),
])
def test_manual_save_uses_chosen_folder_format_and_folder_hint(
        app, shot, settings, tmp_path, monkeypatch, entry, selected, suffix):
    folder = save_directory(settings)
    destination = tmp_path/'手動選擇的資料夾'
    destination.mkdir()
    target = destination/'自選圖片'
    calls, opened = [], []
    def dialog(*args):
        calls.append(args)
        return str(target), selected
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', dialog)
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: opened.append(url) or True)
    settings.setValue('ask_save_path', True)
    saved = QSignalSpy(shot.saved)
    expected_size = shot.render_image().size()
    shot.activateWindow(); shot.surface.setFocus(); app.processEvents()
    if entry == 'button':
        shot.buttons['save'].click()
    elif entry == 'shortcut':
        QTest.keyClick(shot.surface, Qt.Key_S, Qt.ControlModifier)
    else:
        shot.quick_save()
    expected = target.with_suffix(suffix)
    assert len(calls) == 1 and Path(calls[0][2]).parent == folder
    assert Path(shot.last_save) == expected and saved[0][0] == str(expected)
    assert expected.is_file() and QImage(str(expected)).size() == expected_size
    assert save_directory(settings) == folder and not folder.exists()
    assert shot.hold == 0 and shot.closing
    message = saved_notice_manager().notice
    assert message.action and '點擊開啟資料夾' in message.label.text()
    QTest.mouseClick(message, Qt.LeftButton, pos=message.rect().center())
    assert len(opened) == 1 and opened[0].toLocalFile() == str(destination.absolute())
    assert saved_notice_manager().notice is None


def test_existing_shot_observes_save_path_switch_before_save(shot, settings, monkeypatch):
    settings.setValue('ask_save_path', True)
    settings.setValue('ask_save_path', False)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        lambda *args: (_ for _ in ()).throw(AssertionError('Unexpected dialog')))
    shot.quick_save()
    assert Path(shot.last_save).parent == save_directory(settings)
    assert shot.closing


def test_cancel_manual_save_keeps_existing_save_and_default_folder(
        shot, settings, tmp_path, monkeypatch):
    previous = str(tmp_path/'earlier.png')
    assert shot.render_image().save(previous, 'PNG')
    shot.last_save = previous
    folder = save_directory(settings)
    existing_files = {path for path in tmp_path.rglob('*') if path.is_file()}
    settings.setValue('ask_save_path', True)
    saved = QSignalSpy(shot.saved)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: ('', 'PNG (*.png)'))
    shot.quick_save()
    assert shot.last_save == previous and Path(previous).is_file()
    assert not saved and save_directory(settings) == folder
    assert {path for path in tmp_path.rglob('*') if path.is_file()} == existing_files
    assert shot.hold == 0 and not shot.closing
    assert not shot.corner_message.isVisible() and shot.corner_message.action is None


def test_save_folder_validation_retains_previous_choice(window, settings, tmp_path):
    destination = tmp_path/'圖片 路徑'/'雨'
    window.save_folder.setText(str(destination)); window.apply_save_folder()
    assert destination.is_dir() and save_directory(settings) == destination
    window.save_folder.setText('relative/path'); window.apply_save_folder()
    assert save_directory(settings) == destination and '絕對' in window.save_folder_note.text()
    invalid = tmp_path/'file'; invalid.write_text('keep')
    window.save_folder.setText(str(invalid)); window.apply_save_folder()
    assert save_directory(settings) == destination and invalid.read_text() == 'keep'


@pytest.mark.parametrize('extension', ['gif','webp'])
def test_history_save_preserves_animation_and_original(window, settings, tmp_path, monkeypatch, extension):
    from PIL import Image
    source = tmp_path/('animation.'+extension)
    Image.new('RGB',(30,20),'red').save(source, save_all=True,
        append_images=[Image.new('RGB',(30,20),'blue')], duration=100, loop=0)
    original = source.read_bytes()
    settings.setValue('history',[str(source)])
    window.select_page(1)
    requested = QSignalSpy(window.fileRequested)
    window.history_list.itemDoubleClicked.emit(window.history_list.item(0))
    assert requested[0][0] == str(source)
    opened = []
    monkeypatch.setattr(QDesktopServices,'openUrl',lambda url: opened.append(url) or True)
    window.open_history(str(source))
    assert opened[0].toLocalFile() == str(source)
    target = tmp_path/('copy.'+extension)
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(target),''))
    window.save_history(str(source))
    assert target.read_bytes() == original == source.read_bytes()
    assert Image.open(target).n_frames == 2
    wrong = tmp_path/'wrong.png'
    with pytest.raises(ValueError):
        copy_original(source, wrong)
    assert not wrong.exists()


def test_history_menu_only_valid_item_and_expected_actions(window, image, monkeypatch):
    path = window.history.record(image); window.select_page(1)
    actions = []
    def menu_exec(menu, pos):
        actions.extend(action.text() for action in menu.actions())
    monkeypatch.setattr(QMenu,'exec_', menu_exec)
    window.history_menu(window.history_list.visualItemRect(window.history_list.item(0)).center())
    assert actions == ['開啟（系統預設程式）','保存副本…']
    actions.clear(); window.history_menu(QPoint(-10,-10))
    assert actions == [] and Path(path).exists()


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'file:///etc/passwd','data:text/plain,x',
    'https://example.com\nfile:///tmp/x', 'https://user:pass@example.com','WIFI:T:WPA;S:x;;','not a URL'])
def test_qr_non_web_data_stays_inert(value):
    assert web_url(value) is None


def test_qr_multiple_links_explicit_open_and_clear(shot, monkeypatch):
    calls = []
    monkeypatch.setattr(QDesktopServices,'openUrl',lambda url: calls.append(url) or True)
    shot.qr_complete([{'text':'https://example.com/a?q=1'},{'text':'https://example.org/b'}, {'text':'ordinary text'}])
    assert not calls and shot.open_result_button.isVisible() and shot.result_links.count() == 2
    shot.result_links.setCurrentIndex(1); shot.open_result_button.click()
    assert calls[0].toString() == 'https://example.org/b'
    shot.qr_complete([{'text':'javascript:alert(1)'}])
    assert not shot.open_result_button.isVisible() and shot.result_links.count() == 0
    shot.open_result(); assert len(calls) == 1
    shot.show_result('動畫','/tmp/movie.gif',path='/tmp/movie.gif'); shot.open_result()
    assert calls[-1].toLocalFile() == '/tmp/movie.gif'
    shot.hide_result(); shot.open_result(); assert len(calls) == 2


def test_search_current_pixels_private_mime_and_pin(shot, monkeypatch, tmp_path):
    from rainshot.imaging import Mark
    shot.document.add(Mark('redact',((20,20),(80,60)),'#000000',4))
    shot.crop(__import__('PyQt5.QtCore',fromlist=['QRectF']).QRectF(10,10,200,150))
    image = shot.document.render()
    path = prepare_image(image)
    assert path.stat().st_mode & 0o777 == 0o600
    assert QImage(str(path)) == image
    mime = image_mime(image,path)
    assert mime.hasImage() and mime.urls()[0].toLocalFile() == str(path)
    assert mime.imageData() == image
    calls=[]
    monkeypatch.setattr(QDesktopServices,'openUrl',lambda url:calls.append(url) or True)
    shot.toggle_pin(); assert not shot.pinned
    shot.open_image_search()
    assert shot.pinned and calls[0].scheme() == 'https' and not calls[0].isLocalFile()
    shot.copy_search_path()
    copied = Path(QApplication.clipboard().text())
    assert QImage(str(copied)) == image


@pytest.mark.parametrize('provider', ['qwen-turbo','qwen-plus','qwen-max'])
def test_qwen_request_contract_and_credentials(window, settings, provider):
    window.select_page(4); window.provider.setCurrentIndex(window.provider.findData(provider))
    assert window.model.text() == provider and window.model.isVisible()
    assert window.api_key.isVisible() and '阿里雲' in window.key_env.text()
    with pytest.raises(ValueError,match='金鑰'):
        build_request(get_config(settings,provider),'Hello')
    window.api_key.setText('synthetic-secret'); window.save_translation()
    config = get_config(settings,provider)
    url,headers,body=build_request(config,'Hello')
    payload=json.loads(body)
    assert url.host()=='dashscope.aliyuncs.com'
    assert payload['model']==provider and payload['enable_thinking'] is False and payload['stream'] is False
    assert headers['Authorization']=='Bearer synthetic-secret'
    assert payload['messages'][1]=={'role':'user','content':'Hello'}
    assert parse_result(provider,{'choices':[{'message':{'content':'你好'}}]})=='你好'
    settings.sync(); assert 'synthetic-secret' not in Path(settings.fileName()).read_text()


def test_controller_recording_uses_saved_directory(app, settings, image, monkeypatch):
    import rainshot.app as module
    controller = module.Controller(app)
    controller.settings = settings
    shot = controller.edit(image,QRect(0,0,640,400),pinned=True)
    captured=[]
    monkeypatch.setattr(controller,'begin_session',lambda session, shot:captured.append(session))
    controller.start_recording(shot,{'format':'webp'})
    assert captured[0].output_dir == save_directory(settings)
    captured[0].cancel(); captured[0].deleteLater()
    shot.close(); controller.hotkeys.close(); controller.tray.hide(); controller.deleteLater()

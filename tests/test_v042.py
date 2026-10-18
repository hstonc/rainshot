import json
from pathlib import Path
import numpy as np
import pytest
from PyQt5.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QSettings, QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QColor, QPainter, QFont, QKeySequence, QInputMethodEvent
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest,QSignalSpy
from rainshot.floating import FloatingShot
from rainshot.settings_window import SettingsWindow
from rainshot.hotkeys import Hotkeys
from rainshot.history import History
from rainshot.ocr_layout import Word, TextSelection
from rainshot.translated_overlay import selected_lines, overlay, PositionedTranslationJob
from rainshot.shortcuts import bindings,validate,hint
from rainshot.imaging import rgb_array,Mark
from rainshot.hints import saved_notice_manager

@pytest.fixture
def settings(tmp_path):
    value=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    value.setValue('save_directory',str(tmp_path))
    return value

@pytest.fixture
def shot(app,settings,image):
    w=FloatingShot(image,QRect(0,0,640,400),pinned=True,settings=settings)
    w.show_active();app.processEvents()
    yield w
    w.close();saved_notice_manager().clear();app.processEvents()

@pytest.fixture
def window(app,settings,tmp_path):
    keys=Hotkeys();w=SettingsWindow(settings,History(settings,tmp_path),keys)
    w.show();app.processEvents()
    yield w
    w.hide();w.deleteLater();keys.close();app.processEvents()


def focus(app,shot):
    shot.activateWindow();shot.surface.setFocus();app.processEvents()


def test_default_keys_t_c_and_text_no_conflict(app,shot):
    keys=validate(bindings())
    assert keys['translate']=='T' and keys['copy_color']=='C' and keys['text']=='X'
    shot.toggle_color();shot.sample_color(QPoint(10,10));focus(app,shot)
    QTest.keyClick(shot.surface,Qt.Key_C)
    assert QApplication.clipboard().text()=='#FFFFFF'
    QTest.keyClick(shot.surface,Qt.Key_X)
    assert shot.mode=='text' and shot.annotation_row.isVisible()
    assert not shot.color_mode


def test_local_shortcuts_conflicts_save_refresh_and_disable(app,window,shot,settings):
    window.changed.connect(shot.refresh_shortcuts)
    window.local_key_fields['translate'].setKeySequence(QKeySequence('P'))
    window.apply_local_shortcuts()
    assert '相同' in window.local_key_status.text() and not settings.contains('local_shortcuts/translate')
    window.local_key_fields['translate'].setKeySequence(QKeySequence('F2'))
    window.local_key_fields['pin'].setKeySequence(QKeySequence('F3'))
    window.local_key_fields['qr'].clear()
    window.apply_local_shortcuts()
    assert bindings(settings)['translate']=='F2' and bindings(settings)['qr']==''
    assert 'F2 翻譯' in hint(settings) and 'F2' in shot.buttons['translate'].toolTip()
    focus(app,shot);previous=shot.pinned
    QTest.keyClick(shot.surface,Qt.Key_P)
    assert shot.pinned==previous
    QTest.keyClick(shot.surface,Qt.Key_F3)
    assert shot.pinned!=previous
    shot.toggle_pin()
    settings.sync();again=QSettings(settings.fileName(),QSettings.IniFormat)
    assert bindings(again)['pin']=='F3'
    window.reset_local_shortcuts()
    assert bindings(settings)['pin']=='P' and bindings(settings)['translate']=='T'


@pytest.mark.parametrize('key',['Up','Return','Shift+Return','Ctrl+K, Ctrl+T','nonsense'])
def test_reserved_and_invalid_shortcuts(key):
    values=bindings();values['pin']=key
    with pytest.raises(ValueError):validate(values)


def test_annotation_color_slider_history_and_disable(app,shot):
    assert 'crop' not in shot.buttons and 'pan' not in shot.buttons
    shot.buttons['annotate'].click();assert shot.mode=='arrow'
    shot.color_buttons['#4e80df'].click();shot.width_slider.setValue(13)
    assert sum(b.isChecked() for b in shot.color_buttons.values())==1
    assert shot.color_buttons['#4e80df'].text()=='✓'
    QTest.mousePress(shot.surface,Qt.LeftButton,pos=QPoint(30,30))
    QTest.mouseRelease(shot.surface,Qt.LeftButton,pos=QPoint(100,100))
    assert len(shot.document.marks)==1
    assert shot.document.marks[0].color=='#4e80df' and shot.document.marks[0].width==13
    shot.annotation_undo.click();assert not shot.document.marks
    shot.annotation_redo.click();assert len(shot.document.marks)==1
    focus(app,shot);QTest.keyClick(shot.surface,Qt.Key_Z,Qt.ControlModifier)
    assert not shot.document.marks
    QTest.keyClick(shot.surface,Qt.Key_Z,Qt.ControlModifier|Qt.ShiftModifier)
    assert len(shot.document.marks)==1
    shot.set_mode('arrow');shot.buttons['annotate'].click()
    assert shot.mode=='pan' and not shot.annotation_row.isVisible() and not shot.surface.points
    QTest.mousePress(shot.surface,Qt.LeftButton,pos=QPoint(30,30))
    QTest.mouseRelease(shot.surface,Qt.LeftButton,pos=QPoint(180,130))
    assert len(shot.document.marks)==1


def test_inline_text_enter_shift_enter_ime_and_undo(app,shot):
    shot.set_mode('text');shot.begin_text(QPointF(40,60))
    assert 'transparent' in shot.text_input.styleSheet() and not shot.more_row.isVisible()
    QTest.keyClicks(shot.text_input,'Test CTP')
    QTest.keyClick(shot.text_input,Qt.Key_Return,Qt.ShiftModifier)
    ime=QInputMethodEvent();ime.setCommitString('直接輸入中文')
    app.sendEvent(shot.text_input,ime)
    assert shot.text_input.toPlainText()=='Test CTP\n直接輸入中文'
    assert not shot.color_mode and not shot.translation_job and shot.pinned
    assert shot.text_input.geometry().topLeft()==QPoint(40,60)
    QTest.keyClick(shot.text_input,Qt.Key_Return)
    assert not shot.text_input.isVisible() and shot.document.marks[-1].text=='Test CTP\n直接輸入中文'
    assert shot.document.marks[-1].points==((40.0,60.0),)
    focus(app,shot);QTest.keyClick(shot.surface,Qt.Key_Z,Qt.ControlModifier)
    assert not shot.document.marks


def test_text_preview_matches_committed_layout(app,shot):
    shot.set_mode('text');shot.begin_text(QPointF(40,60))
    shot.text_input.setPlainText('Two lines\n文字')
    shot.text_input.setCursorWidth(0)
    app.processEvents()
    before=shot.surface.grab().toImage().convertToFormat(QImage.Format_RGB32)
    shot.commit_text();app.processEvents()
    after=shot.surface.grab().toImage().convertToFormat(QImage.Format_RGB32)
    # Compare ink position; excludes the image boundary and empty editor area.
    b=rgb_array(before)[45:170,30:250];a=rgb_array(after)[45:170,30:250]
    mb=np.any(b<220,axis=2);ma=np.any(a<220,axis=2)
    assert mb.any() and ma.any()
    by,bx=np.where(mb);ay,ax=np.where(ma)
    assert abs(int(by.min())-int(ay.min()))<=1
    assert abs(int(bx.min())-int(ax.min()))<=1
    assert abs(int(by.max())-int(ay.max()))<=1


def sample_ocr():
    return TextSelection([Word('Hello',QRectF(40,50,140,32),(1,),99),
        Word('world',QRectF(190,50,110,32),(1,),99),Word('Keep this',QRectF(40,130,260,32),(2,),99)])


def test_translation_partial_selection_overlay_and_selectable_text(app,image):
    selection=sample_ocr();selection.select_word(QPointF(55,60))
    lines=selected_lines(selection)
    assert len(lines)==1 and lines[0].text=='Hello'
    result,translated,sizes=overlay(image,selection,lines,['你好'])
    assert translated.all_text=='你好 world\nKeep this'
    translated.select_word(QPointF(45,60));assert translated.selected_text=='你好'
    assert result.copy(QRect(190,50,110,32))==image.copy(QRect(190,50,110,32))
    assert sizes[0]>=18
    assert result!=image and image.pixelColor(45,55)==QColor('white')


def test_overlay_fit_does_not_paint_outside_boxes(app,image):
    selection=sample_ocr();selection.select_all();lines=selected_lines(selection)
    result,translated,sizes=overlay(image,selection,lines,['A much longer translated sentence '*3,'保留大小'])
    assert sizes[0]<sizes[1]
    mask=np.any(rgb_array(result)!=rgb_array(image),axis=2)
    for y,x in zip(*np.where(mask)):
        assert any(line.rect.contains(int(x),int(y)) for line in lines)


def test_translation_shown_in_image_exports_and_save_closes_shot(shot):
    shot.selection=sample_ocr();shot.set_mode('ocr')
    shot.translation_source_selection=shot.selection
    shot.translation_lines=selected_lines(shot.selection)
    shot.translation_source_image=shot.document.render()
    original=shot.document.render().copy()
    shot.translation_complete(['你好世界','保持此處'])
    assert shot.translation_image is not None and not shot.translation_output.isVisible()
    assert shot.selection.all_text=='你好世界\n保持此處'
    shot.select_all();shot.copy();assert QApplication.clipboard().text()=='你好世界\n保持此處'
    expected=shot.render_image().copy()
    shot.quick_save();assert QImage(shot.last_save)==expected
    assert shot.document.render()==original
    assert shot.closing and not shot.isVisible()


def test_translation_restore_preserves_original_image_and_ocr(shot):
    shot.selection=sample_ocr();shot.set_mode('ocr')
    shot.translation_source_selection=shot.selection
    shot.translation_lines=selected_lines(shot.selection)
    shot.translation_source_image=shot.document.render()
    original=shot.document.render().copy()
    shot.translation_complete(['你好世界','保持此處'])
    shot.restore_original_translation()
    assert shot.translation_image is None and shot.selection.all_text=='Hello world\nKeep this'
    assert shot.render_image()==original


def test_translation_batch_order_and_cancel_no_late_result(app,monkeypatch):
    import rainshot.translated_overlay as module
    calls=[];jobs=[]
    class Fake(QObject):
        finished=pyqtSignal(str);failed=pyqtSignal(str)
        def __init__(self,config,text,parent):
            super().__init__(parent);self.text=text;self.canceled=False;jobs.append(self)
        def start(self):calls.append(self.text)
        def cancel(self):self.canceled=True
    monkeypatch.setattr(module,'TranslationJob',Fake)
    batch=PositionedTranslationJob({'key':'synthetic'},selected_lines(sample_ocr()))
    result=QSignalSpy(batch.finished);batch.start()
    assert calls==['Hello world']
    jobs[0].finished.emit('你好世界');QTest.qWait(10)
    assert calls==['Hello world','Keep this']
    jobs[1].finished.emit('保留此處');QTest.qWait(10)
    assert result[0][0]==['你好世界','保留此處'] and batch.done and 'key' not in batch.config
    batch.deleteLater()
    batch=PositionedTranslationJob({},selected_lines(sample_ocr()));result=QSignalSpy(batch.finished)
    batch.start();current=jobs[-1];batch.cancel()
    assert current.canceled
    current.finished.emit('late');QTest.qWait(10)
    assert not result
    batch.deleteLater()


def test_switching_tools_cancels_pending_translation(shot):
    shot.selection=sample_ocr()
    class Job:
        done=False
        def cancel(self):self.done=True
        def deleteLater(self):pass
    job=Job();shot.translation_job=job
    shot.set_mode('arrow')
    assert job.done and shot.translation_job is None and shot.mode=='arrow'


def test_owned_tool_activation_does_not_dismiss_transient(app,shot,monkeypatch):
    from PyQt5.QtWidgets import QWidget
    shot.toggle_pin();assert not shot.pinned
    monkeypatch.setattr(QApplication,'activeWindow',lambda:shot.corner_message)
    monkeypatch.setattr(shot,'isActiveWindow',lambda:False)
    shot.dismiss_if_inactive();assert not shot.closing
    external=QWidget()
    monkeypatch.setattr(QApplication,'activeWindow',lambda:external)
    shot.dismiss_if_inactive();assert shot.closing
    external.deleteLater()


def test_translation_survives_pick_and_annotation_undo(shot):
    shot.selection=sample_ocr();shot.set_mode('ocr')
    shot.translation_source_selection=shot.selection
    shot.translation_lines=selected_lines(shot.selection)
    shot.translation_source_image=shot.document.render()
    shot.translation_complete(['你好世界','繼續編輯'])
    translated=shot.render_image().copy()
    shot.toggle_color();assert shot.render_image()==translated
    shot.sample_color(QPoint(40,50))
    assert shot.pixel_hex==translated.pixelColor(40,50).name().upper()
    shot.set_mode('arrow');assert shot.render_image()==translated
    shot.add_mark(Mark('arrow',((350,200),(400,240)),'#ef5b5b',4))
    assert shot.translation_image is None and shot.document.base==translated
    shot.undo();assert shot.render_image()==translated
    shot.redo();assert shot.render_image()!=translated


@pytest.mark.parametrize('trigger',['click','enter','default_key','custom_key'])
def test_copy_color_exits_immediately(app,shot,settings,trigger):
    if trigger=='custom_key':
        settings.setValue('local_shortcuts/copy_color','F4');shot.refresh_shortcuts()
    shot.toggle_color();shot.sample_color(QPoint(80,80));expected=shot.pixel_hex
    focus(app,shot)
    if trigger=='click':QTest.mouseClick(shot.surface,Qt.LeftButton,pos=QPoint(80,80))
    else:QTest.keyClick(shot.surface,{'enter':Qt.Key_Return,'default_key':Qt.Key_C,'custom_key':Qt.Key_F4}[trigger])
    assert QApplication.clipboard().text()==expected
    assert not shot.color_mode and not shot.buttons['color'].isChecked()
    assert not shot.magnifier.isVisible() and shot.mode=='pan' and not shot.closing
    assert shot.pixel_hex is None and not shot.document.marks
    shot.sample_color(QPoint(90,90));assert not shot.magnifier.isVisible()

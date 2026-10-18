"""Text layout and corner positioning regressions independent of the X11 WM."""
import json
import os
import subprocess
import sys

import pytest
from PyQt5.QtCore import QRect, QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

from rainshot.hints import CORNERS, CornerMessage
from rainshot.shortcuts import hint


@pytest.fixture
def message(app, tmp_path):
    owner = QWidget()
    owner.closing = owner.suspended = False
    owner.surface = QWidget(owner)
    owner.resize(320, 200)
    owner.surface.resize(320, 200)
    owner.show()
    settings = QSettings(str(tmp_path/'corner-settings.ini'), QSettings.IniFormat)
    result = CornerMessage(owner, settings)
    yield result
    result.close()
    owner.close()
    owner.deleteLater()
    app.processEvents()


def assert_fits(message):
    label = message.label
    assert message.rect().contains(label.geometry())
    assert label.contentsRect().height() >= label.heightForWidth(label.width())
    assert message.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert message.testAttribute(Qt.WA_ShowWithoutActivating)


@pytest.mark.parametrize('text', [
    '已儲存：rainshot_20261002_135252_102498.png · 點擊開啟資料夾',
    '已完成截圖，可點擊提示開啟資料夾\n按 P 釘住 · T 翻譯 · C 複製色碼',
    '已儲存：' + '很長的圖片名稱' * 25 + '.png · 點擊開啟資料夾',
    '已儲存：' + 'Long_name-without_spaces_' * 15 + '.png · 點擊開啟資料夾',
])
def test_saved_text_fits_after_tutorial_and_action_transitions(app, message, text):
    actions = []
    message.present('拖曳移動，滾輪縮放\n' + hint(message.settings),
                    tutorial=True, duration=0)
    app.processEvents()
    assert_fits(message)
    message.present(text, action=lambda: actions.append('opened'), duration=0)
    app.processEvents()
    assert_fits(message)
    assert not message.windowFlags() & Qt.WindowTransparentForInput
    QTest.mouseClick(message, Qt.LeftButton, pos=message.rect().center())
    assert actions == ['opened'] and not message.isVisible()
    message.present('一般提示\n再次點擊不會開啟資料夾', duration=0)
    app.processEvents()
    assert_fits(message)
    assert message.action is None and message.windowFlags() & Qt.WindowTransparentForInput
    message.present(text, action=lambda: actions.append('opened-again'), duration=0)
    app.processEvents()
    assert_fits(message)
    QTest.mouseClick(message, Qt.LeftButton, pos=message.rect().center())
    assert actions == ['opened', 'opened-again']


@pytest.mark.parametrize('corner', [code for name, code in CORNERS])
@pytest.mark.parametrize('available', [QRect(-1600, -400, 1200, 800),
                                      QRect(1920, -80, 320, 220)])
def test_negative_origin_and_small_workarea_keep_hint_inside(
        app, message, monkeypatch, corner, available):
    class Screen:
        def availableGeometry(self):
            return QRect(available)
    monkeypatch.setattr(QApplication, 'screenAt', lambda point: Screen())
    message.settings.setValue('hint_corner', corner)
    message.present('已儲存：rainshot_20261002_135252.png · 點擊開啟資料夾',
                    action=lambda: None, duration=0)
    app.processEvents()
    assert_fits(message)
    assert available.contains(message.geometry())
    assert message.width() <= min(400, available.width() - 44)


def test_real_qt_scale_two_fits_tutorial_and_saved_text(tmp_path):
    # A separate Qt application is needed because the DPI scale is fixed at
    # QApplication creation. It still uses offscreen and never opens a real app.
    program = '''
import json, sys
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QWidget
from rainshot.hints import CornerMessage
from rainshot.shortcuts import hint
app = QApplication([])
owner = QWidget()
owner.closing = owner.suspended = False
owner.surface = QWidget(owner)
owner.resize(320, 200)
owner.surface.resize(320, 200)
owner.show()
settings = QSettings(sys.argv[1], QSettings.IniFormat)
message = CornerMessage(owner, settings)
metrics = []
for text, action in [('拖曳移動，滾輪縮放\\n' + hint(settings), None),
                     ('已儲存：rainshot_20261002_135252.png · 點擊開啟資料夾', lambda: None),
                     ('一般操作提示\\n回復非互動狀態', None)]:
    message.present(text, duration=0, action=action)
    app.processEvents()
    metrics.append({'actual': message.label.contentsRect().height(),
                    'required': message.label.heightForWidth(message.label.width()),
                    'within': app.primaryScreen().availableGeometry().contains(message.geometry())})
print(json.dumps({'ratio': app.primaryScreen().devicePixelRatio(), 'metrics': metrics}))
message.close()
owner.close()
'''
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR='2')
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path/'scaled.ini')],
                            env=environment, text=True, capture_output=True,
                            timeout=10, check=True)
    report = json.loads(result.stdout)
    assert report['ratio'] == 2
    assert all(item['actual'] >= item['required'] and item['within']
               for item in report['metrics'])

"""Opt-in native X11 checks for clickable, nonactivating saved-image hints.

Run from the source directory on an X11 desktop:
    PYTHONPATH=. /usr/bin/python3 tests/desktop_save_v044.py /tmp/rainshot-save-qa

The script injects pointer events only over its own test windows. It saves
synthetic images in an isolated temporary directory, mocks external URL opens,
and restores the pointer and closes its windows even if an assertion fails.
It is deliberately separate from the normal, offscreen pytest suite.
"""
import argparse
import ctypes as C
import json
import os
import tempfile
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import QPoint, QRect, QSettings, Qt
from PyQt5.QtGui import QColor, QCursor, QDesktopServices, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

from rainshot.floating import FloatingShot


class ClickTarget(QWidget):
    """Our own native window behind the hint; never another user's app."""
    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint |
                         Qt.WindowStaysOnTopHint)
        self.setWindowTitle('rainshot native save hint test')
        self.setStyleSheet('background:#34435d;')
        self.presses = []

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.presses.append(bool(event.spontaneous()))
        super().mousePressEvent(event)


class NativePointer:
    def __init__(self):
        self.x = C.CDLL('libX11.so.6')
        self.xt = C.CDLL('libXtst.so.6')
        self.x.XOpenDisplay.argtypes = [C.c_char_p]
        self.x.XOpenDisplay.restype = C.c_void_p
        self.x.XFlush.argtypes = [C.c_void_p]
        self.x.XCloseDisplay.argtypes = [C.c_void_p]
        self.xt.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int,
                                                C.c_int, C.c_int, C.c_ulong]
        self.xt.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint,
                                                C.c_int, C.c_ulong]
        self.previous = QCursor.pos()
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Cannot connect to the X11 display')
        self.pressed = False

    def click(self, point):
        self.xt.XTestFakeMotionEvent(self.display, -1, point.x(), point.y(), 0)
        self.x.XFlush(self.display)
        QTest.qWait(150)
        self.xt.XTestFakeButtonEvent(self.display, 1, True, 0)
        self.pressed = True
        self.x.XFlush(self.display)
        QTest.qWait(35)
        self.xt.XTestFakeButtonEvent(self.display, 1, False, 0)
        self.pressed = False
        self.x.XFlush(self.display)
        QTest.qWait(300)

    def close(self):
        if not self.display:
            return
        try:
            if self.pressed:
                self.xt.XTestFakeButtonEvent(self.display, 1, False, 0)
            self.xt.XTestFakeMotionEvent(self.display, -1,
                                        self.previous.x(), self.previous.y(), 0)
            self.x.XFlush(self.display)
        finally:
            self.x.XCloseDisplay(self.display)
            self.display = None


def check_flags(message, clickable):
    assert message.isVisible()
    assert message.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert message.windowHandle().flags() & Qt.WindowDoesNotAcceptFocus
    assert message.testAttribute(Qt.WA_ShowWithoutActivating)
    assert message.testAttribute(Qt.WA_TransparentForMouseEvents) == (not clickable)
    assert not message.isActiveWindow()


def place_target(target, message, shot):
    target.setGeometry(message.geometry().adjusted(-8, -8, 8, 8))
    target.show()
    target.raise_()
    message.raise_()
    QTest.qWait(180)
    point = message.geometry().center()
    image_rect = QRect(shot.surface.mapToGlobal(QPoint()), shot.surface.size())
    assert not image_rect.contains(point), 'Test hint overlaps the test screenshot'
    assert target.rect().contains(target.mapFromGlobal(point))
    return point


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('outdir', type=Path, help='Directory for the JSON report')
    out = parser.parse_args().outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'result': 'failed', 'platform': None, 'stages': []}
    app = pointer = target = None
    shots = []
    previous_open = QDesktopServices.openUrl
    opened = []
    environment = {}
    temporary = tempfile.TemporaryDirectory(prefix='rainshot-save-native-')
    try:
        for variable, name in [('XDG_CONFIG_HOME', 'config'),
                               ('XDG_CACHE_HOME', 'cache'),
                               ('XDG_RUNTIME_DIR', 'runtime')]:
            environment[variable] = os.environ.get(variable)
            directory = Path(temporary.name)/name
            directory.mkdir(mode=0o700)
            os.environ[variable] = str(directory)
        assert os.environ.get('XDG_SESSION_TYPE') != 'wayland'
        assert not os.environ.get('WAYLAND_DISPLAY'), 'Run on native X11, not XWayland'
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        report['platform'] = app.platformName()
        assert app.platformName() == 'xcb', 'This opt-in test requires the X11 Qt backend'
        pointer = NativePointer()
        QDesktopServices.openUrl = lambda url: opened.append(url.toLocalFile()) or True
        settings = QSettings(str(Path(temporary.name)/'settings.ini'), QSettings.IniFormat)
        settings.setValue('hint_corner', 'bottom-right')
        settings.setValue('hints_enabled', True)
        settings.setValue('ask_save_path', False)
        settings.setValue('save_directory', str(Path(temporary.name)/'default-exports'))
        image = QImage(280, 160, QImage.Format_RGB32)
        image.fill(QColor('#123456'))
        screen = app.primaryScreen().availableGeometry()
        assert screen.width() >= 800 and screen.height() >= 600
        region = QRect(screen.left()+35, screen.top()+35, image.width(), image.height())
        target = ClickTarget()

        # The first ordinary/tutorial show must already pass native input through.
        pinned = FloatingShot(image, region, pinned=True, settings=settings)
        shots.append(pinned)
        pinned.show_active()
        pinned.set_toolbar_visible(False)
        QTest.qWait(200)
        message = pinned.corner_message
        assert message.tutorial and message.action is None
        point = place_target(target, message, pinned)
        check_flags(message, clickable=False)
        pointer.click(point)
        assert target.presses == [True] and not opened
        assert not pinned.closing and not message.isActiveWindow()
        report['stages'].append('initial ordinary hint passes a native click through')

        first_folder = Path(temporary.name)/'manual-destination-one'
        first_folder.mkdir()
        assert pinned.save_to(first_folder/'chosen.png')
        point = place_target(target, message, pinned)
        check_flags(message, clickable=True)
        pointer.click(point)
        assert target.presses == [True]
        assert opened == [str(first_folder.absolute())]
        assert not message.isVisible() and message.action is None
        assert not pinned.closing
        report['stages'].append('saved hint receives native input and opens actual file parent')

        # Reusing the same native hint window must restore input transparency.
        pinned.set_status('一般操作提示')
        point = place_target(target, message, pinned)
        check_flags(message, clickable=False)
        pointer.click(point)
        assert target.presses == [True, True] and len(opened) == 1
        report['stages'].append('ordinary hint after saved hint passes native input through')

        second_folder = Path(temporary.name)/'manual-destination-two'
        second_folder.mkdir()
        assert pinned.save_to(second_folder/'another.png')
        point = place_target(target, message, pinned)
        check_flags(message, clickable=True)
        pointer.click(point)
        assert target.presses == [True, True]
        assert opened == [str(first_folder.absolute()), str(second_folder.absolute())]
        assert not pinned.closing
        report['stages'].append('subsequent saved hint becomes natively clickable again')
        pinned.close()
        QTest.qWait(100)

        # A transient shot first creates a nonclickable tutorial, then a save hint.
        transient = FloatingShot(image, region, settings=settings)
        shots.append(transient)
        transient.show_active()
        QTest.qWait(250)
        assert transient.corner_message.tutorial and not transient.closing
        assert transient.outside_clicks and transient.outside_clicks.display
        observed = []
        transient.outside_clicks.pressed.connect(
            lambda pos: observed.append((pos.x(), pos.y())))
        transient.quick_save()
        actual_parent = str(Path(transient.last_save).parent.absolute())
        message = transient.corner_message
        point = place_target(target, message, transient)
        transient.activateWindow()
        transient.surface.setFocus()
        QTest.qWait(180)
        check_flags(message, clickable=True)
        pointer.click(point)
        assert (point.x(), point.y()) in observed, 'Native outside-click observer did not run'
        assert not sip.isdeleted(transient) and not transient.closing
        assert transient.isVisible() and not transient.pinned
        assert target.presses == [True, True]
        assert opened[-1] == actual_parent and len(opened) == 3
        assert not message.isVisible() and message.action is None
        report['stages'].append('native saved-hint click preserves transient shot through outside-click observer')
        report.update(result='passed', native_underlying_presses=len(target.presses),
                      mocked_folder_opens=opened, transient_raw_clicks=len(observed),
                      no_external_app_opened=True)
    except BaseException as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        QDesktopServices.openUrl = previous_open
        for window in shots + ([target] if target is not None else []):
            if not sip.isdeleted(window):
                window.close()
        if app is not None:
            app.processEvents()
        if pointer is not None:
            pointer.close()
        temporary.cleanup()
        for variable, previous in environment.items():
            if previous is None:
                os.environ.pop(variable, None)
            else:
                os.environ[variable] = previous
        (out/'desktop-save-v044.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()

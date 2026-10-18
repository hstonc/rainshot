"""Explicit desktop activation with mocked or isolated D-Bus, never the desktop."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QSettings, QTimer
from PyQt5.QtDBus import QDBusConnection, QDBusPendingCall, QDBusVariant
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QLabel

from rainshot.desktop_accessibility import DesktopAccessibility, SERVICE, PATH, STATUS, PROPERTIES
from rainshot import settings_window


def wait_for(predicate, timeout_ms=2000):
    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


class CompletedBus:
    def __init__(self, *answers, connected=True):
        self.answers = list(answers)
        self.connected = connected
        self.calls = []

    def isConnected(self):
        return self.connected

    def asyncCall(self, message, timeout):
        assert (message.service(), message.path(), message.interface()) == (SERVICE, PATH, PROPERTIES)
        self.calls.append((message.member(), message.arguments(), timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, str):
            reply = message.createErrorReply('org.freedesktop.DBus.Error.AccessDenied', answer)
        else:
            reply = message.createReply([] if answer is None else [answer])
        return QDBusPendingCall.fromCompletedCall(reply)


@pytest.mark.parametrize('enabled,reader', [(False, False), (True, False), (False, True), (True, True)])
def test_construction_and_refresh_never_write_desktop_status(app, enabled, reader):
    bus = CompletedBus({'IsEnabled': QDBusVariant(enabled), 'ScreenReaderEnabled': QDBusVariant(reader)})
    status = DesktopAccessibility(bus=bus)
    finished = QSignalSpy(status.enable_finished)
    assert bus.calls == [] and status.enabled is None
    assert status.refresh() and status.pending
    wait_for(lambda: not status.pending)
    assert status.enabled is enabled and status.screen_reader_enabled is reader
    assert not status.error and not finished
    assert [(method, args) for method, args, _ in bus.calls] == [('GetAll', [STATUS])]


@pytest.mark.parametrize('reader', [False, True])
def test_enable_sets_only_is_enabled_and_verifies_actual_status(app, reader):
    bus = CompletedBus(None, {'IsEnabled': True, 'ScreenReaderEnabled': reader})
    status = DesktopAccessibility(bus=bus)
    finished = QSignalSpy(status.enable_finished)
    assert status.enable() and status.pending and status.enabled is None
    assert not status.enable() and not status.refresh(), 'Do not overlap an explicit operation'
    wait_for(lambda: not status.pending)
    assert list(finished) == [[True]]
    assert status.enabled is True and status.screen_reader_enabled is reader
    assert [method for method, _, _ in bus.calls] == ['Set', 'GetAll']
    interface, name, value = bus.calls[0][1]
    assert interface == STATUS and name == 'IsEnabled'
    # QDBusMessage.arguments() unwraps variants on some PyQt5 builds. The
    # isolated service test below verifies the actual ss v wire signature.
    assert (value.variant() if isinstance(value, QDBusVariant) else value) is True
    assert all(timeout == status.timeout_ms for _, _, timeout in bus.calls)


@pytest.mark.parametrize('answers,error', [
    (('Denied by the desktop',), 'Denied'),
    ((None, 'Read unavailable'), 'Read unavailable'),
    ((None, {'IsEnabled': False, 'ScreenReaderEnabled': True}), '尚未確認'),
])
def test_failed_enable_resets_pending_and_never_claims_success(app, answers, error):
    bus = CompletedBus(*answers)
    status = DesktopAccessibility(bus=bus)
    finished = QSignalSpy(status.enable_finished)
    status.enable()
    wait_for(lambda: not status.pending)
    assert list(finished) == [[False]] and error in status.error
    assert not status.enabling and status._watcher is None
    bus.answers.extend([None, {'IsEnabled': True, 'ScreenReaderEnabled': True}])
    assert status.enable()
    wait_for(lambda: not status.pending)
    assert list(finished) == [[False], [True]] and status.error == ''


def test_modern_status_without_legacy_reader_property_is_supported(app):
    status = DesktopAccessibility(bus=CompletedBus({'IsEnabled': True}))
    status.refresh()
    wait_for(lambda: not status.pending)
    assert status.enabled is True and status.screen_reader_enabled is None and not status.error


@pytest.mark.parametrize('values', [[], {}, {'IsEnabled': 'false', 'ScreenReaderEnabled': False},
                                    {'IsEnabled': True, 'ScreenReaderEnabled': 0}])
def test_malformed_status_is_reported_without_boolean_coercion(app, values):
    status = DesktopAccessibility(bus=CompletedBus(values))
    status.refresh()
    wait_for(lambda: not status.pending)
    assert status.enabled is None and status.screen_reader_enabled is None
    assert '有效' in status.error


def test_disconnected_bus_and_dispatch_failure_allow_retry(app):
    bus = CompletedBus(connected=False)
    status = DesktopAccessibility(bus=bus)
    finished = QSignalSpy(status.enable_finished)
    status.refresh()
    assert not status.pending and 'D-Bus' in status.error and not bus.calls
    status.enable()
    assert list(finished) == [[False]] and not status.pending and not bus.calls
    bus.connected = True
    bus.answers.extend([RuntimeError('Cannot dispatch'), {'IsEnabled': False, 'ScreenReaderEnabled': False}])
    status.enable()
    assert not status.pending and 'Cannot dispatch' in status.error
    status.refresh()
    wait_for(lambda: not status.pending)
    assert status.error == '' and status.enabled is False


def make_window(monkeypatch, tmp_path, bus):
    monkeypatch.setattr(settings_window, 'DesktopAccessibility',
                        lambda parent: DesktopAccessibility(parent, bus=bus))
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    settings.setValue('save_directory', str(tmp_path))
    class History:
        directory = tmp_path
        def entries(self):
            return []
    class Keys:
        supported = False
        def pause(self):
            pass
        def resume(self):
            pass
    return settings_window.SettingsWindow(settings, History(), Keys())


def dispose(obj):
    obj.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_settings_read_only_refresh_and_explicit_button_failure_retry(app, monkeypatch, tmp_path):
    bus = CompletedBus({'IsEnabled': False, 'ScreenReaderEnabled': True},
                       {'IsEnabled': False, 'ScreenReaderEnabled': True},
                       'Activation denied', None, {'IsEnabled': True, 'ScreenReaderEnabled': True})
    window = make_window(monkeypatch, tmp_path, bus)
    status = window.desktop_accessibility
    button = window.enable_accessibility_button
    try:
        assert '讀取中' in window.desktop_accessibility_status.text() and not button.isEnabled()
        wait_for(lambda: not status.pending)
        assert '未啟用' in window.desktop_accessibility_status.text()
        assert '朗讀已啟用' in window.desktop_accessibility_status.text() and button.isEnabled()
        assert button.text() == '啟用更多軟體的元素識別'
        assert any(label.text() == '允許 Firefox、Qt 等軟體提供元素範圍；會啟用桌面的輔助功能，不會啟動朗讀。部分軟體需要重啟。'
                   for label in window.findChildren(QLabel))
        window.select_page(1)
        window.select_page(0)
        wait_for(lambda: not status.pending)
        assert [method for method, _, _ in bus.calls] == ['GetAll', 'GetAll']
        button.click()
        assert status.pending and not button.isEnabled()
        wait_for(lambda: not status.pending)
        assert 'Activation denied' in window.desktop_accessibility_status.text() and button.isEnabled()
        button.click()
        wait_for(lambda: not status.pending)
        assert '已啟用' in window.desktop_accessibility_status.text() and not button.isEnabled()
        assert status.screen_reader_enabled is True
        assert [method for method, _, _ in bus.calls] == ['GetAll', 'GetAll', 'Set', 'Set', 'GetAll']
    finally:
        dispose(window)


PEER = r'''
import json, os
import dbus, dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
name = dbus.service.BusName('org.a11y.Bus', bus)
enabled = os.environ['INITIAL_ENABLED'] == '1'
reader = os.environ['INITIAL_READER'] == '1'
def trace(method, interface, prop=None, value=None):
    with open(os.environ['TRACE'], 'a') as stream:
        stream.write(json.dumps({'method': method, 'interface': interface,
                                 'property': prop, 'value': value}) + '\n')
def later(callback, value=None):
    if os.environ['MODE'] == 'timeout':
        return
    def send():
        callback() if value is None else callback(value)
        return False
    GLib.timeout_add(int(os.environ['DELAY']), send)
class Status(dbus.service.Object):
    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='s', out_signature='a{sv}',
                         async_callbacks=('ok', 'error'))
    def GetAll(self, interface, ok, error):
        trace('GetAll', str(interface))
        later(ok, {'IsEnabled': dbus.Boolean(enabled), 'ScreenReaderEnabled': dbus.Boolean(reader)})
    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='ssv', out_signature='',
                         async_callbacks=('ok', 'error'))
    def Set(self, interface, prop, value, ok, error):
        global enabled
        trace('Set', str(interface), str(prop), bool(value))
        if str(interface) != 'org.a11y.Status' or str(prop) != 'IsEnabled' or not bool(value):
            error(dbus.exceptions.DBusException('Unexpected write', name='org.freedesktop.DBus.Error.InvalidArgs'))
            return
        enabled = True
        later(ok)
status = Status(bus, '/org/a11y/bus')
print('READY', flush=True)
GLib.MainLoop().run()
'''


@pytest.fixture
def isolated_status_factory(app, tmp_path):
    peers, connections = [], []
    daemon = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1',
                               '--address=unix:path=' + str(tmp_path / 'bus')],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    address = daemon.stdout.readline().strip()
    assert address, 'Cannot start isolated D-Bus'
    def factory(enabled=False, reader=False, delay=1, mode=''):
        trace = tmp_path / ('trace-' + uuid.uuid4().hex + '.jsonl')
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, INITIAL_ENABLED=str(int(enabled)),
                   INITIAL_READER=str(int(reader)), DELAY=str(delay), MODE=mode, TRACE=str(trace))
        peer = subprocess.Popen(['/usr/bin/python3', '-u', '-c', PEER], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        peers.append(peer)
        assert peer.stdout.readline().strip() == 'READY'
        connection = 'a11y-test-' + uuid.uuid4().hex
        bus = QDBusConnection.connectToBus(address, connection)
        connections.append(connection)
        assert bus.isConnected()
        return bus, trace
    yield factory
    for peer in peers:
        peer.terminate()
        peer.wait(timeout=3)
    for connection in connections:
        QDBusConnection.disconnectFromBus(connection)
    daemon.terminate()
    daemon.wait(timeout=3)


def read_trace(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize('reader', [False, True])
def test_actual_qtdbus_protocol_preserves_screen_reader(app, isolated_status_factory, reader):
    bus, trace = isolated_status_factory(reader=reader)
    status = DesktopAccessibility(bus=bus)
    finished = QSignalSpy(status.enable_finished)
    status.refresh()
    wait_for(lambda: not status.pending)
    assert status.enabled is False and status.screen_reader_enabled is reader and not status.error
    status.enable()
    wait_for(lambda: not status.pending)
    assert list(finished) == [[True]] and status.enabled is True
    assert status.screen_reader_enabled is reader
    assert read_trace(trace) == [
        {'method': 'GetAll', 'interface': STATUS, 'property': None, 'value': None},
        {'method': 'Set', 'interface': STATUS, 'property': 'IsEnabled', 'value': True},
        {'method': 'GetAll', 'interface': STATUS, 'property': None, 'value': None}]
    dispose(status)


def test_pending_status_keeps_gui_responsive_and_timeout_recovers(app, isolated_status_factory):
    bus, _ = isolated_status_factory(mode='timeout')
    status = DesktopAccessibility(bus=bus, timeout_ms=100)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start()
    try:
        status.refresh()
        QTest.qWait(40)
        assert status.pending and len(ticks) >= 2
        wait_for(lambda: not status.pending)
        assert status.error and status._watcher is None
        assert status.enabled is None
    finally:
        timer.stop()
        dispose(status)


def test_destroyed_window_disconnects_delayed_status_callbacks(app, monkeypatch, tmp_path, isolated_status_factory):
    bus, trace = isolated_status_factory(delay=100)
    window = make_window(monkeypatch, tmp_path, bus)
    status = window.desktop_accessibility
    wait_for(lambda: bool(read_trace(trace)))
    dispose(window)
    assert sip.isdeleted(status)
    QTest.qWait(160)
    assert [call['method'] for call in read_trace(trace)] == ['GetAll']


def test_destroyed_controller_does_not_issue_post_set_verification(app, isolated_status_factory):
    bus, trace = isolated_status_factory(delay=100)
    status = DesktopAccessibility(bus=bus)
    status.enable()
    wait_for(lambda: bool(read_trace(trace)))
    dispose(status)
    QTest.qWait(160)
    assert [call['method'] for call in read_trace(trace)] == ['Set']

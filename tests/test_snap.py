"""Accessibility selection coordinates and nonblocking subprocess ownership."""
from contextlib import nullcontext
import json
import sys
import time

import pytest
from PyQt5.QtCore import QObject, QPoint, QProcess, QRect, pyqtSignal
from PyQt5.QtTest import QSignalSpy, QTest

from rainshot import snap
from rainshot.x11 import X11


class FakeProcess(QObject):
    finished = pyqtSignal(int, int)
    errorOccurred = pyqtSignal(int)
    NotRunning, Running = QProcess.NotRunning, QProcess.Running
    NormalExit, CrashExit = QProcess.NormalExit, QProcess.CrashExit
    FailedToStart = QProcess.FailedToStart

    def __init__(self, parent):
        super().__init__(parent)
        self.current_state = self.NotRunning
        self.output = b''
        self.starts = []
        self.kills = 0

    def state(self):
        return self.current_state

    def isOpen(self):
        return bool(self.starts)

    def start(self, executable, arguments):
        assert self.current_state == self.NotRunning, 'Started over a live subprocess'
        self.current_state = self.Running
        self.starts.append((executable, arguments))

    def readAllStandardOutput(self):
        assert self.isOpen(), 'Read from a closed process'
        result, self.output = self.output, b''
        return result

    def readAllStandardError(self):
        assert self.isOpen(), 'Read from a closed process'
        return b''

    def kill(self):
        self.kills += 1

    def waitForFinished(self, *args):
        raise AssertionError('Pointer handling must never block on subprocess teardown')

    def finish(self, data, code=0, status=QProcess.NormalExit):
        self.output = json.dumps(data).encode()
        self.current_state = self.NotRunning
        self.finished.emit(code, status)


@pytest.fixture
def probe(app, monkeypatch):
    window = {'id': 10, 'pid': 12345, 'rect': QRect(100, 50, 200, 100),
              'native_rect': QRect(200, 100, 400, 200)}
    class FakeX11:
        def windows(self):
            return [window]
        def close(self):
            pass
    monkeypatch.setattr(snap, 'X11', FakeX11)
    monkeypatch.setattr(snap, 'QProcess', FakeProcess)
    result = snap.SnapProbe()
    yield result
    result.cancel()
    result.process.current_state = QProcess.NotRunning
    result.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('logical, native, point, expected_point, physical_rect, expected_rect', [
    (QRect(100, 50, 200, 100), QRect(200, 100, 400, 200), QPoint(140, 70),
     QPoint(280, 140), QRect(260, 120, 120, 80), QRect(130, 60, 60, 40)),
    (QRect(-800, 100, 400, 300), QRect(-1600, 200, 800, 600), QPoint(-650, 180),
     QPoint(-1300, 360), QRect(-1400, 300, 300, 200), QRect(-700, 150, 150, 100)),
    (QRect(1920, 0, 800, 600), QRect(1920, 0, 1200, 900), QPoint(2000, 100),
     QPoint(2040, 150), QRect(1980, 60, 303, 151), QRect(1960, 40, 202, 101)),
])
def test_point_and_rectangle_use_window_mapping(
        logical, native, point, expected_point, physical_rect, expected_rect):
    assert snap.native_point(point, logical, native) == expected_point
    assert snap.logical_rectangle(physical_rect, logical, native) == expected_rect
    assert snap.logical_rectangle(native.adjusted(-200, -200, 200, 200), logical, native) == logical
    assert snap.logical_rectangle(native.translated(native.width()*2, 0), logical, native).isEmpty()


def test_probe_passes_physical_point_and_bounds_then_returns_logical_rectangles(probe):
    ready = QSignalSpy(probe.ready)
    contextual = QSignalSpy(probe.ready_at)
    completed = QSignalSpy(probe.finished_at)
    point = QPoint(140, 70)
    probe.request(point)
    assert probe.is_busy() and probe.active_point == point
    assert probe.process.starts[0][1] == [
        '-m', 'rainshot.accessible', '12345', '280', '140', '200', '100', '400', '200']
    probe.process.finish([[200, 100, 400, 200], [260, 120, 120, 80],
                          [260, 120, 120, 80], [0, 0, 100, 100]])
    expected = [QRect(130, 60, 60, 40), QRect(100, 50, 200, 100)]
    assert contextual[0][0] == point and contextual[0][1] == expected
    assert ready[0][0] == expected and completed[0][0] == point
    assert not probe.is_busy() and probe.active_point is None and not probe.timer.isActive()


def test_cancelled_result_cannot_complete_new_request_and_only_latest_is_started(probe):
    results = QSignalSpy(probe.ready_at)
    probe.request(QPoint(140, 70))
    probe.request(QPoint(150, 80))
    probe.request(QPoint(170, 90))
    assert len(probe.process.starts) == 1 and probe.process.kills == 2
    assert probe.active_point == QPoint(170, 90)
    probe.process.finish([[200, 100, 400, 200]])
    assert not results and len(probe.process.starts) == 2
    assert probe.process.starts[-1][1][3:5] == ['340', '180']
    probe.process.finish([[200, 100, 400, 200]])
    assert len(results) == 1 and results[0][0] == QPoint(170, 90)
    assert results[0][1] == [QRect(100, 50, 200, 100)]


def test_repeated_point_keeps_active_probe_and_cancel_discards_late_result(probe):
    results = QSignalSpy(probe.ready_at)
    probe.request(QPoint(140, 70))
    probe.request(QPoint(140, 70))
    assert len(probe.process.starts) == 1 and not probe.process.kills
    probe.cancel()
    assert not probe.is_busy() and probe.active_point is None
    probe.process.finish([[200, 100, 400, 200]])
    assert not results and len(probe.process.starts) == 1


def test_timeout_falls_back_without_waiting_or_accepting_late_result(probe):
    results = QSignalSpy(probe.ready_at)
    probe.request(QPoint(140, 70))
    assert 650 < probe.timer.interval() <= 2000
    probe.expire()
    assert results[0][0] == QPoint(140, 70) and results[0][1] == []
    assert not probe.is_busy() and probe.process.kills == 1
    probe.request(QPoint(160, 80))
    probe.process.finish([[200, 100, 400, 200]])
    assert len(results) == 1 and len(probe.process.starts) == 2
    probe.process.finish([[200, 100, 400, 200]])
    assert len(results) == 2 and results[1][0] == QPoint(160, 80)


def test_failed_to_start_completes_once_and_allows_retry(probe):
    results = QSignalSpy(probe.ready_at)
    probe.request(QPoint(140, 70))
    probe.process.current_state = QProcess.NotRunning
    probe.process.errorOccurred.emit(QProcess.FailedToStart)
    assert len(results) == 1 and results[0][1] == []
    assert not probe.is_busy() and not probe.timer.isActive()
    probe.request(QPoint(160, 80))
    probe.process.finish([[200, 100, 400, 200]])
    assert len(results) == 2 and results[1][0] == QPoint(160, 80)


@pytest.mark.parametrize('output', [b'not JSON', b'{}', b'null',
    b'[[true,100,400,200]]', b'[[200,100,-400,200]]',
    b'[[200,100,400,null]]', b'[[200,100,400]]', b'[[200,100,10000001,200]]',
    b'[]' + b' '*65536, json.dumps([[200, 100, 400, 200]]*129).encode()])
def test_bad_or_excessive_subprocess_geometry_stays_inert(probe, output):
    probe.request(QPoint(140, 70))
    assert snap.SnapProbe.parse(output, probe._active) == []


def test_window_metadata_retains_native_bounds_without_changing_logical_geometry(app, monkeypatch):
    adapter = object.__new__(X11)
    adapter.display, adapter.root = 1, 2
    class Library:
        @staticmethod
        def XInternAtom(*args):
            return 99
    adapter.lib = Library()
    properties = {'_NET_CURRENT_DESKTOP': [0], '_NET_CLIENT_LIST_STACKING': [10],
                  '_NET_WM_PID': [12345], '_NET_WM_STATE': [], '_NET_WM_DESKTOP': [0]}
    monkeypatch.setattr(adapter, 'safe', lambda: nullcontext())
    monkeypatch.setattr(adapter, 'property', lambda wid, name: properties[name])
    native, logical = QRect(200, 100, 400, 200), QRect(100, 50, 200, 100)
    monkeypatch.setattr(adapter, 'raw_geometry', lambda wid: QRect(native))
    monkeypatch.setattr(adapter, 'logical_geometry', lambda rect: QRect(logical))
    assert adapter.geometry(10) == logical
    assert adapter.windows() == [{'id': 10, 'pid': 12345,
                                  'rect': logical, 'native_rect': native}]


def test_real_process_cancel_and_reentrant_result_cannot_replace_latest_context(app, monkeypatch):
    class FakeX11:
        def windows(self):
            return [{'id': 10, 'pid': 12345, 'rect': QRect(100, 50, 200, 100),
                     'native_rect': QRect(200, 100, 400, 200)}]
        def close(self):
            pass
    monkeypatch.setattr(snap, 'X11', FakeX11)
    probe = snap.SnapProbe()
    start = probe.process.start
    program = ('import sys,time; '
               'time.sleep(2 if sys.argv[1] == "280" else 0); '
               'print("[[200,100,400,200]]")')
    monkeypatch.setattr(probe.process, 'start',
                        lambda executable, args: start(sys.executable, ['-c', program, args[3]]))
    results = QSignalSpy(probe.ready_at)
    # Starting a new probe directly from the result receiver is legal: the old
    # finished callback must not stop the new timer or swallow its context.
    def another_query(point, rects):
        if point == QPoint(170, 90):
            probe.request(QPoint(180, 100))
    probe.ready_at.connect(another_query)
    try:
        probe.cancel()  # Closed QProcess output must not be read.
        probe.request(QPoint(140, 70))
        QTest.qWait(30)
        probe.request(QPoint(170, 90))
        deadline = time.monotonic() + 2
        while len(results) < 2 and time.monotonic() < deadline:
            QTest.qWait(10)
        assert len(results) == 2
        assert [entry[0] for entry in results] == [QPoint(170, 90), QPoint(180, 100)]
        assert all(entry[1] == [QRect(100, 50, 200, 100)] for entry in results)
        assert not probe.is_busy() and not probe.timer.isActive()
    finally:
        probe.cancel()
        # Test teardown only; pointer callbacks in SnapProbe never wait.
        if probe.process.state() != QProcess.NotRunning:
            probe.process.waitForFinished(1000)
        probe.deleteLater()
        app.processEvents()

"""Hover stability, stale results and manual overrides for automatic selection."""
import pytest
from PyQt5.QtCore import QObject, QPoint, QRect, QSettings, Qt, pyqtSignal
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest
import rainshot.capture as capture
from rainshot.imaging import ScreenTile


class Probe(QObject):
    ready_at = pyqtSignal(object, object)
    finished_at = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.windows = [{'id': 1, 'pid': 111, 'rect': QRect(100, 100, 400, 300)}]
        self.requests = []
        self.cancellations = 0
        self.busy = False

    def window_at(self, point):
        return next((w for w in self.windows if w['rect'].contains(point)), None)

    def request(self, point):
        self.requests.append(QPoint(point))
        self.busy = True

    def cancel(self):
        self.cancellations += 1
        self.busy = False

    def is_busy(self):
        return self.busy


@pytest.fixture
def overlay(app, tmp_path, monkeypatch):
    monkeypatch.setattr(capture, 'SnapProbe', Probe)
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    image = QImage(800, 600, QImage.Format_RGB32)
    image.fill(Qt.white)
    widget = capture.SelectionOverlay([ScreenTile(QRect(0, 0, 800, 600), image)], settings)
    widget.update_hover(QPoint(170, 165))
    widget.snap_timer.stop()
    yield widget
    widget.cancel()


def test_hover_keeps_element_until_leaving_its_bounds(overlay):
    button = QRect(150, 150, 120, 35)
    card = QRect(120, 130, 320, 180)
    overlay.snap_ready_at(QPoint(170, 165), [card, button])
    assert overlay.selection == button
    overlay.snap.busy = True
    cancellations = overlay.snap.cancellations
    overlay.update_hover(QPoint(200, 170))
    assert overlay.selection == button
    assert overlay.snap.cancellations == cancellations
    overlay.update_hover(QPoint(300, 220))
    assert overlay.selection == card
    overlay.update_hover(QPoint(480, 380))
    assert overlay.selection == QRect(100, 100, 400, 300)


@pytest.mark.parametrize('first', [[], [QRect(100, 100, 400, 300)]])
def test_stationary_cold_tree_retries_once_then_recovers(overlay, first):
    point = QPoint(170, 165)
    overlay.request_hover()
    overlay.snap.busy = False
    overlay.snap.ready_at.emit(point, first)
    overlay.snap.finished_at.emit(point)
    assert overlay.snap_timer.isActive() and overlay.snap_timer.interval() == 450
    overlay.snap_timer.stop()
    overlay.request_hover()
    assert overlay.snap.requests == [point, point]
    overlay.snap.busy = False
    button = QRect(150, 150, 120, 35)
    overlay.snap.ready_at.emit(point, [button])
    overlay.snap.finished_at.emit(point)
    assert overlay.selection == button and not overlay.snap_timer.isActive()
    overlay.request_hover()
    assert len(overlay.snap.requests) == 2


def test_stationary_empty_provider_has_no_unbounded_retry(overlay):
    point = QPoint(170, 165)
    for _ in range(2):
        overlay.request_hover()
        overlay.snap.busy = False
        overlay.snap.ready_at.emit(point, [])
        overlay.snap.finished_at.emit(point)
        overlay.snap_timer.stop()
    overlay.request_hover()
    assert len(overlay.snap.requests) == 2 and not overlay.snap_timer.isActive()
    overlay.update_hover(QPoint(180, 165))
    assert overlay.snap_timer.interval() == 140
    overlay.snap_timer.stop()
    overlay.request_hover()
    assert overlay.snap.requests[-1] == QPoint(180, 165)


def test_movement_does_not_starve_running_probe(overlay):
    overlay.request_hover()
    assert overlay.snap.requests == [QPoint(170, 165)]
    overlay.update_hover(QPoint(300, 220))
    overlay.request_hover()
    assert len(overlay.snap.requests) == 1
    overlay.snap.busy = False
    overlay.snap.ready_at.emit(QPoint(170, 165), [QRect(150, 150, 120, 35)])
    overlay.snap.finished_at.emit(QPoint(170, 165))
    assert overlay.snap_timer.isActive()
    overlay.request_hover()
    assert overlay.snap.requests[-1] == QPoint(300, 220)


def test_tab_parent_survives_mouse_jitter_and_late_result(overlay):
    button, card = QRect(150, 150, 120, 35), QRect(120, 130, 320, 180)
    overlay.snap_ready_at(QPoint(170, 165), [card, button])
    QTest.keyClick(overlay, Qt.Key_Tab)
    assert overlay.selection == card
    overlay.update_hover(QPoint(180, 165))
    overlay.snap_ready_at(QPoint(170, 165), [button])
    assert overlay.selection == card
    overlay.request_hover()
    assert not overlay.snap.requests
    overlay.update_hover(QPoint(350, 240))
    overlay.request_hover()
    assert overlay.snap.requests == [QPoint(350, 240)]


def test_late_other_window_and_disabled_results_are_ignored(overlay):
    overlay.snap.windows.append({'id': 2, 'pid': 222, 'rect': QRect(520, 100, 220, 300)})
    overlay.update_hover(QPoint(580, 180))
    overlay.snap_ready_at(QPoint(170, 165), [QRect(150, 150, 120, 35)])
    assert overlay.selection == QRect(520, 100, 220, 300)
    overlay.settings.setValue('smart_selection', False)
    overlay.update_hover(QPoint(580, 180))
    overlay.snap_ready_at(QPoint(580, 180), [QRect(550, 150, 100, 40)])
    assert overlay.selection.isEmpty() and not overlay.snap_timer.isActive()
    assert not overlay.snap_rects


def test_shift_pauses_and_release_restores_without_mouse_move(overlay, monkeypatch):
    point = QPoint(170, 165)
    monkeypatch.setattr(capture.QCursor, 'pos', lambda: point)
    overlay.request_hover()
    QTest.keyPress(overlay, Qt.Key_Shift)
    overlay.snap_ready_at(point, [QRect(150, 150, 120, 35)])
    assert overlay.selection.isEmpty() and not overlay.snap_timer.isActive()
    QTest.keyRelease(overlay, Qt.Key_Shift)
    assert overlay.selection == QRect(100, 100, 400, 300)
    overlay.request_hover()
    assert overlay.snap.requests == [point, point]


def test_disabling_elements_drops_cached_rects_but_keeps_window(overlay):
    overlay.snap_ready_at(QPoint(170, 165), [QRect(150, 150, 120, 35)])
    overlay.settings.setValue('element_selection', False)
    overlay.update_hover(QPoint(170, 165))
    assert overlay.selection == QRect(100, 100, 400, 300)
    assert not overlay.snap_timer.isActive()


def test_window_spanning_screens_is_not_clipped_to_hover_screen(overlay):
    image = QImage(400, 600, QImage.Format_RGB32)
    image.fill(Qt.white)
    overlay.tiles = [ScreenTile(QRect(0, 0, 400, 600), image),
                     ScreenTile(QRect(400, 0, 400, 600), image)]
    overlay.snap.windows = [{'id': 1, 'pid': 111, 'rect': QRect(300, 100, 300, 200)}]
    overlay.update_hover(QPoint(350, 150))
    assert overlay.selection == QRect(300, 100, 300, 200)

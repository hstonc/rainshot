"""Opt-in X11 browser element selection QA, using a disposable local fixture.

Run from the source directory with an output directory argument::

    PYTHONPATH=. /usr/bin/python3 tests/desktop_browser_snap.py /tmp/rainshot-browser-qa

Only the browser started here is queried and terminated. The helper reads names
only inside that browser's accessibility tree; production probes return geometry
alone. Exit 77 means the required native browser/accessibility surface is absent.
"""
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from browser_gap_fixture import GAP_LABELS, assert_overlay_default_union, multi_gap_cases


LABELS = {
    'button': 'Rainshot fixture button',
    'image': 'Rainshot fixture image',
    'card': 'Rainshot fixture card',
    'article': 'Rainshot fixture article',
    **GAP_LABELS,
}


def inspect_fixture(pid):
    """The caller bounds this potentially slow AT-SPI operation with a timeout."""
    import pyatspi
    desktop = pyatspi.Registry.getDesktop(0)
    targets = {}
    for application in desktop:
        if application.get_process_id() != pid:
            continue
        queue = [(application, [])]
        visited = 0
        while queue and visited < 1200:
            node, ancestors = queue.pop(0)
            visited += 1
            try:
                ext = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                rect = [ext.x, ext.y, ext.width, ext.height]
                valid = ext.width > 3 and ext.height > 3 and ext.x > -100000
            except (NotImplementedError, RuntimeError, AttributeError):
                rect, valid = None, False
            try:
                name = node.name
                if valid and name in LABELS.values():
                    key = next(key for key, value in LABELS.items() if value == name)
                    targets[key] = {'rect': rect, 'ancestors': ancestors, 'role': node.getRoleName()}
                parents = ancestors + ([rect] if valid and rect not in ancestors else [])
                for child in node:
                    queue.append((child, parents))
            except (NotImplementedError, RuntimeError, AttributeError):
                continue
        break
    return targets


if len(sys.argv) > 1 and sys.argv[1] == '--inspect':
    try:
        print(json.dumps(inspect_fixture(int(sys.argv[2]))))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
    raise SystemExit(0)


def main():
    from PyQt5.QtCore import QPoint, QRect, QSettings, Qt
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    from rainshot.capture import SelectionOverlay
    from rainshot.imaging import ScreenTile
    from rainshot.snap import SnapProbe

    if len(sys.argv) != 2:
        raise SystemExit('Provide a report output directory.')
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'fixture': 'local file; isolated Chromium profile; no external pages',
              'renderer_accessibility_forced': False,
              'result': 'failed', 'targets': {}}
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    browser = overlay = probe = None
    temp = tempfile.TemporaryDirectory(prefix='rainshot-browser-snap-')
    browser_log = None
    exit_code = 1

    def wait_until(predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            QTest.qWait(35)
        return bool(predicate())

    def rect_list(rect):
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    def matching(expected, candidates, tolerance=3):
        return any(all(abs(a - b) <= tolerance for a, b in zip(rect_list(expected), rect_list(candidate)))
                   for candidate in candidates)

    try:
        browser_binary = shutil.which('chromium') or shutil.which('chromium-browser')
        if app.platformName() != 'xcb' or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            report.update(result='skipped', reason='This native browser test requires an X11 session.')
            return 77
        if not browser_binary:
            report.update(result='skipped', reason='Chromium is not installed.')
            return 77
        try:
            address = subprocess.check_output([
                'gdbus', 'call', '--session', '--dest', 'org.a11y.Bus',
                '--object-path', '/org/a11y/bus', '--method', 'org.a11y.Bus.GetAddress',
            ], text=True, timeout=4)
            os.environ['AT_SPI_BUS_ADDRESS'] = ast.literal_eval(address.strip())[0]
        except (OSError, subprocess.SubprocessError, ValueError, SyntaxError) as error:
            report.update(result='skipped', reason='AT-SPI bus unavailable: ' + str(error))
            return 77
        fixture = Path(__file__).with_name('browser_snap_fixture.html').resolve()
        assert fixture.is_file(), fixture
        browser_log = open(Path(temp.name) / 'chromium.log', 'w')
        env = dict(os.environ, NO_AT_BRIDGE='0')
        env.pop('QT_QPA_PLATFORM', None)
        browser = subprocess.Popen([
            browser_binary, '--user-data-dir=' + str(Path(temp.name) / 'profile'),
            '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
            '--disable-component-update', '--disable-sync', '--disable-extensions',
            '--disable-default-apps', '--metrics-recording-only', '--password-store=basic',
            '--window-size=1000,760', '--window-position=70,70',
            fixture.as_uri(),
        ], env=env, stdout=browser_log, stderr=browser_log, start_new_session=True)
        # Exercise the production probe before the fixture inspector reads any
        # accessible names. A default Chromium process initially exposes only
        # frames, unlike the forced-accessibility fixture used in 0.4.4.
        deadline = time.monotonic() + 18
        window = None
        while time.monotonic() < deadline and browser.poll() is None:
            QTest.qWait(100)
            if probe is not None:
                probe.cancel()
                probe.deleteLater()
            probe = SnapProbe()
            window = next((item for item in probe.windows if item['pid'] == browser.pid), None)
            if window is not None:
                break
        if window is None:
            report.update(result='skipped', reason='Isolated Chromium has no native window.')
            return 77
        # Let the local page render independently of AX activation. Creating a
        # native frame is earlier than the document becoming ready to display.
        QTest.qWait(800)
        warmup_replies = []
        probe.ready_at.connect(lambda point, rects: warmup_replies.append(list(rects)))
        started = time.monotonic()
        probe.request(window['rect'].center())
        assert wait_until(lambda: bool(warmup_replies), 5), 'Initial default Chromium probe timed out.'
        report['first_production_probe'] = {
            'elapsed_ms': round((time.monotonic() - started) * 1000),
            'candidates': [rect_list(rect) for rect in warmup_replies[0]],
        }
        assert any(rect != window['rect'] for rect in warmup_replies[0]), \
            'First probe of the loaded default Chromium page returned only its frame.'
        targets = {}
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline and browser.poll() is None:
            QTest.qWait(400)
            try:
                data = subprocess.check_output([
                    sys.executable, str(Path(__file__).resolve()), '--inspect', str(browser.pid),
                ], env=env, text=True, timeout=4)
                targets = json.loads(data)
            except (subprocess.SubprocessError, ValueError):
                continue
            if all(key in targets for key in LABELS):
                break
        if not all(key in targets for key in LABELS):
            report.update(result='skipped', reason='Chromium did not expose all local fixture targets via AT-SPI.',
                          available_targets=sorted(set(targets).intersection(LABELS)))
            return 77

        own_windows = [window for window in probe.windows if window['pid'] == browser.pid]
        assert own_windows, 'Started browser was not found in the native window snapshot.'
        window = own_windows[0]
        physical = window.get('native_rect', window['rect'])
        logical = window['rect']

        def logical_rect(values):
            px, py, width, height = values
            sx = logical.width() / physical.width()
            sy = logical.height() / physical.height()
            left = logical.x() + round((px - physical.x()) * sx)
            top = logical.y() + round((py - physical.y()) * sy)
            right = logical.x() + round((px + width - physical.x()) * sx)
            bottom = logical.y() + round((py + height - physical.y()) * sy)
            return QRect(left, top, right - left, bottom - top)

        expected = {key: logical_rect(value['rect']) for key, value in targets.items() if key in LABELS}
        points = {key: rect.center() for key, rect in expected.items()}
        # The button text is itself an accessible child. Its blank left padding
        # tests the button bounds instead of expecting the text hit to be ignored.
        points['button'] = QPoint(expected['button'].x() + 12, expected['button'].center().y())
        points['card'] = expected['card'].topLeft() + QPoint(12, 12)
        points['article'] = expected['article'].bottomRight() - QPoint(12, 12)
        for key in GAP_LABELS:
            points[key] = QPoint(expected[key].x() + 8, expected[key].center().y())
        replies = []
        probe.ready_at.connect(lambda point, rects: replies.append((QPoint(point), list(rects))))
        for key, point in points.items():
            replies.clear()
            probe.request(point)
            assert wait_until(lambda: any(query == point for query, _ in replies), 5), ('Probe timeout', key)
            rects = next(rects for query, rects in replies if query == point)
            assert matching(expected[key], rects), (key, rect_list(expected[key]), [rect_list(r) for r in rects])
            parent_found = any(rect != expected[key] and rect.contains(expected[key]) for rect in rects)
            assert parent_found, ('Missing enclosing candidate', key, [rect_list(r) for r in rects])
            report['targets'][key] = {'expected': rect_list(expected[key]), 'candidates': [rect_list(r) for r in rects],
                                      'exact_element': True, 'enclosing_candidate': True}

        combined = expected['card'].united(expected['article'])
        gap_point = QPoint(expected['card'].center().x(),
                           (expected['card'].bottom() + expected['article'].top()) // 2)
        replies.clear()
        probe.request(gap_point)
        assert wait_until(lambda: any(query == gap_point for query, _ in replies), 5)
        gap_rects = next(rects for query, rects in replies if query == gap_point)
        assert matching(combined, gap_rects), ('Missing combined gap region', [rect_list(r) for r in gap_rects])
        report['gap_selection'] = {'expected': rect_list(combined), 'exact_combined_region': True,
                                   'candidates': [rect_list(r) for r in gap_rects]}
        multi_cases = multi_gap_cases(expected)
        report['multi_gap_selection'] = {}
        for case in multi_cases:
            point = case['point']
            replies.clear()
            probe.request(point)
            assert wait_until(lambda: any(query == point for query, _ in replies), 5), case['name']
            rects = next(rects for query, rects in replies if query == point)
            assert matching(case['expected'], rects), (
                'Missing multi-element combined region', case['name'], rect_list(case['expected']),
                [rect_list(rect) for rect in rects])
            report['multi_gap_selection'][case['name']] = {
                'members': list(case['members']), 'point': [point.x(), point.y()],
                'expected': rect_list(case['expected']), 'exact_combined_region': True,
                'candidates': [rect_list(rect) for rect in rects],
            }

        # Synthetic pixels avoid recording other desktop content. Native overlay
        # windows still cover the fixture and exercise the frozen selection path.
        tiles = []
        for screen in app.screens():
            image = QImage(screen.geometry().size(), QImage.Format_RGB32)
            image.fill(QColor('#26324b'))
            tiles.append(ScreenTile(screen.geometry(), image))
        settings = QSettings(str(Path(temp.name) / 'settings.ini'), QSettings.IniFormat)
        settings.setValue('smart_selection', True)
        settings.setValue('element_selection', True)
        settings.setValue('hints_enabled', False)
        # A user may keep moving their pointer during an opt-in test. Initialize
        # this native overlay with a synthetic fixture point, then send hover
        # coordinates directly so the test never moves or monopolizes the cursor.
        with patch('rainshot.capture.QCursor') as cursor:
            cursor.pos.return_value = points['button']
            overlay = SelectionOverlay(tiles, settings)
        overlay.setMouseTracking(False)
        overlay_replies = []
        overlay.snap.ready_at.connect(lambda point, rects: overlay_replies.append({
            'point': [point.x(), point.y()], 'candidates': [rect_list(rect) for rect in rects]}))
        if not wait_until(lambda: matching(expected['button'], overlay.snap_rects), 5):
            report['overlay_debug'] = {
                'hover': [overlay.hover_point.x(), overlay.hover_point.y()],
                'candidates': [rect_list(rect) for rect in overlay.snap_rects],
                'probe_replies': overlay_replies,
                'browser_in_window_snapshot': any(item['pid'] == browser.pid for item in overlay.snap.windows),
            }
            raise AssertionError('Frozen overlay missed the browser button.')
        chosen = overlay.selection.translated(overlay.bounds.topLeft())
        assert matching(expected['button'], [chosen]), ('Smallest button selection was not used', rect_list(chosen))
        QTest.keyClick(overlay, Qt.Key_Tab)
        after_tab = overlay.selection.translated(overlay.bounds.topLeft())
        assert after_tab != chosen and after_tab.contains(chosen), ('Tab did not select an enclosing region', rect_list(after_tab))
        overlay.update_hover(points['image'])
        assert wait_until(lambda: matching(expected['image'], overlay.snap_rects), 5), 'Frozen overlay missed the browser image.'
        overlay.update_hover(gap_point)
        assert wait_until(lambda: matching(combined, overlay.snap_rects), 5), 'Frozen overlay missed the gap region.'
        assert matching(combined, [overlay.selection.translated(overlay.bounds.topLeft())])
        multi_overlay = {}
        for case in multi_cases:
            overlay.update_hover(case['point'])
            multi_overlay[case['name']] = assert_overlay_default_union(
                overlay, case['expected'], matching, wait_until)
        report['frozen_overlay'] = {'button': True, 'image': True, 'tab_parent': True,
                                    'gap_combined': True,
                                    'multi_gap_combined': multi_overlay,
                                    'hover_input': 'fixed fixture points; native pointer unchanged',
                                    'background_pixels': 'synthetic; no desktop image exported'}
        report['result'] = 'passed'
        exit_code = 0
        return exit_code
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if overlay is not None:
            overlay.cancel()
        if probe is not None:
            probe.cancel()
        app.processEvents()
        if browser is not None:
            try:
                os.killpg(browser.pid, signal.SIGTERM)
                browser.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(browser.pid, signal.SIGKILL)
                browser.wait(timeout=2)
            except ProcessLookupError:
                pass
        if browser_log is not None:
            browser_log.close()
        temp.cleanup()
        (out / 'browser-snap-native.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    raise SystemExit(main())

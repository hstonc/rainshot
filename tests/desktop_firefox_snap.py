"""Opt-in native Firefox selection test, with an owned disposable profile.

No accessibility preferences or forced accessibility flags are used. The first
probe runs before accessible names are read. Names are inspected only in the
local fixture started here, never in any existing browser window/profile.
Exit 77 means no native X11/Firefox/AT-SPI fixture was available.
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
from collections import Counter, deque
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


def inspect_fixture(pid, names=False):
    import pyatspi
    from rainshot.accessible import _owned_process
    pyatspi.Atspi.set_timeout(100, 100)
    desktop = pyatspi.Registry.getDesktop(0)
    report = {'applications': [], 'role_counts': {}, 'state_counts': {},
              'roots': [], 'targets': {}, 'visited_nodes': 0}
    roles, states = Counter(), Counter()
    deadline = time.monotonic() + 4
    for index in range(min(48, desktop.childCount)):
        if time.monotonic() >= deadline:
            break
        application = desktop.getChildAtIndex(index)
        try:
            app_pid = int(application.get_process_id())
            if not _owned_process(app_pid, pid):
                continue
        except Exception:
            continue
        report['applications'].append({'pid': app_pid, 'exact_window_pid': app_pid == pid})
        queue = deque([(application, 0, [])])
        while queue and report['visited_nodes'] < 1400 and time.monotonic() < deadline:
            node, depth, ancestors = queue.popleft()
            report['visited_nodes'] += 1
            try:
                role = node.getRoleName()
                roles[role] += 1
                state = node.getState()
                flags = {key.lower(): bool(state.contains(getattr(pyatspi, 'STATE_' + key)))
                         for key in ('VISIBLE', 'SHOWING', 'ACTIVE', 'DEFUNCT', 'ICONIFIED', 'MANAGES_DESCENDANTS')}
                states.update(key for key, value in flags.items() if value)
                geometry = None
                try:
                    component = node.queryComponent()
                    ext = component.getExtents(pyatspi.DESKTOP_COORDS)
                    geometry = [ext.x, ext.y, ext.width, ext.height]
                except Exception:
                    pass
                if depth < 3:
                    report['roots'].append({'role': role, 'depth': depth, 'geometry': geometry,
                                            'states': flags, 'children': node.childCount})
                valid = geometry and geometry[2] > 3 and geometry[3] > 3 and geometry[0] > -100000
                if names:
                    name = node.name
                    if valid and name in LABELS.values():
                        key = next(key for key, label in LABELS.items() if label == name)
                        report['targets'][key] = {'role': role, 'rect': geometry,
                                                 'ancestors': ancestors, 'states': flags}
                parents = ancestors + ([geometry] if valid and geometry not in ancestors else [])
                if depth < 32 and not flags['defunct']:
                    for child_index in range(min(96, node.childCount)):
                        child = node.getChildAtIndex(child_index)
                        if child is not None:
                            queue.append((child, depth + 1, parents))
            except Exception:
                continue
    report['role_counts'], report['state_counts'] = dict(roles), dict(states)
    return report


def trace_point(pid, x, y):
    """Geometry/states along actual native hit testing, for the owned fixture."""
    import pyatspi
    from rainshot.accessible import _owned_process
    pyatspi.Atspi.set_timeout(100, 100)
    desktop = pyatspi.Registry.getDesktop(0)
    paths = []
    deadline = time.monotonic() + 3
    for application in desktop:
        try:
            if not _owned_process(int(application.get_process_id()), pid):
                continue
            for node in application:
                chain, seen = [], set()
                for _ in range(32):
                    if time.monotonic() >= deadline or node in seen:
                        break
                    seen.add(node)
                    states = node.getState()
                    item = {'role': node.getRoleName(), 'pid': node.get_process_id(),
                            'states': {key.lower(): bool(states.contains(getattr(pyatspi, 'STATE_' + key)))
                                       for key in ('VISIBLE', 'SHOWING', 'DEFUNCT', 'MANAGES_DESCENDANTS')}}
                    try:
                        component = node.queryComponent()
                        ext = component.getExtents(pyatspi.DESKTOP_COORDS)
                        item['rect'] = [ext.x, ext.y, ext.width, ext.height]
                        child = component.getAccessibleAtPoint(x, y, pyatspi.DESKTOP_COORDS)
                    except Exception as error:
                        item['component_error_type'] = type(error).__name__
                        child = None
                    if child is not None:
                        item['hit_role'] = child.getRoleName()
                    if child is not None and child != node:
                        ancestors = []
                        parent = child.parent
                        for _ in range(32):
                            if parent is None or parent == node:
                                break
                            ancestors.append({'role': parent.getRoleName(),
                                              'states': {key.lower(): bool(parent.getState().contains(getattr(pyatspi, 'STATE_' + key)))
                                                         for key in ('VISIBLE', 'SHOWING', 'DEFUNCT')}})
                            parent = parent.parent
                        item['hit_ancestors'] = ancestors
                    chain.append(item)
                    if child is None or child == node:
                        break
                    node = child
                paths.append(chain)
        except Exception:
            continue
    return paths


if len(sys.argv) > 1 and sys.argv[1] == '--inspect':
    print(json.dumps(inspect_fixture(int(sys.argv[2]), '--names' in sys.argv)))
    raise SystemExit(0)
if len(sys.argv) > 1 and sys.argv[1] == '--trace':
    print(json.dumps(trace_point(*map(int, sys.argv[2:5]))))
    raise SystemExit(0)


def main():
    from PyQt5.QtCore import QPoint, QRect, QSettings, Qt
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    from rainshot.snap import SnapProbe, native_point, logical_rectangle
    from rainshot.capture import SelectionOverlay
    from rainshot.imaging import ScreenTile

    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--bridge-diagnostic'):
        raise SystemExit('Provide a report directory, optionally --bridge-diagnostic for an owned-browser-only environment test.')
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    bridge_diagnostic = '--bridge-diagnostic' in sys.argv
    report = {'fixture': 'local file; isolated owned Firefox profile; no external pages',
              'accessibility_forced': bridge_diagnostic, 'result': 'failed', 'targets': {}}
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    browser = probe = overlay = None
    temp = tempfile.TemporaryDirectory(prefix='rainshot-firefox-snap-')
    browser_log = None

    def wait_until(predicate, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if predicate():
                return True
            QTest.qWait(35)
        return bool(predicate())

    def values(rect):
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    def inspector(*arguments):
        data = subprocess.check_output([sys.executable, str(Path(__file__).resolve())] + list(arguments),
                                       env=env, text=True, timeout=6)
        return json.loads(data)

    def request(point):
        replies = []
        started = time.monotonic()
        receiver = lambda queried, rects: replies.append(list(rects)) if queried == point else None
        probe.ready_at.connect(receiver)
        probe.request(point)
        assert wait_until(lambda: bool(replies), 4), 'Production probe timed out.'
        probe.ready_at.disconnect(receiver)
        return replies[0], round((time.monotonic() - started) * 1000)

    try:
        executable = shutil.which('firefox')
        if app.platformName() != 'xcb' or os.environ.get('XDG_SESSION_TYPE') == 'wayland' or not executable:
            report.update(result='skipped', reason='An X11 session with Firefox is required.')
            return 77
        response = subprocess.check_output(['gdbus', 'call', '--session', '--dest', 'org.a11y.Bus',
                                            '--object-path', '/org/a11y/bus', '--method', 'org.a11y.Bus.GetAddress'],
                                           text=True, timeout=4)
        os.environ['AT_SPI_BUS_ADDRESS'] = ast.literal_eval(response.strip())[0]
        report['accessibility_bus'] = os.environ['AT_SPI_BUS_ADDRESS'].split(',guid=')[0]
        status = subprocess.check_output([
            'gdbus', 'call', '--session', '--dest', 'org.a11y.Bus', '--object-path', '/org/a11y/bus',
            '--method', 'org.freedesktop.DBus.Properties.GetAll', 'org.a11y.Status',
        ], text=True, timeout=4)
        report['initial_session_status'] = status.strip()
        profile = Path(temp.name) / 'profile'
        profile.mkdir()
        # Only an owned disposable profile gets these first-run/network prefs;
        # none influence accessibility services or the AT-SPI bridge.
        (profile / 'user.js').write_text('\n'.join([
            'user_pref("browser.shell.checkDefaultBrowser", false);',
            'user_pref("browser.startup.homepage_override.mstone", "ignore");',
            'user_pref("browser.aboutwelcome.enabled", false);',
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
            'user_pref("toolkit.telemetry.enabled", false);',
            'user_pref("app.update.enabled", false);',
            'user_pref("browser.safebrowsing.phishing.enabled", false);',
            'user_pref("browser.safebrowsing.malware.enabled", false);',
        ]))
        fixture = Path(__file__).with_name('browser_snap_fixture.html').resolve()
        env = dict(os.environ, NO_AT_BRIDGE='0')
        env.pop('QT_QPA_PLATFORM', None)
        if bridge_diagnostic:
            # A clearly reported secondary diagnostic; the normal test above
            # remains unforced and proves whether Firefox registered by default.
            env['GNOME_ACCESSIBILITY'] = '1'
            report['bridge_diagnostic'] = 'GNOME_ACCESSIBILITY=1 only for this owned Firefox and its fixture inspectors; no global flag/profile changes'
        browser_log = open(Path(temp.name) / 'firefox.log', 'w')
        browser = subprocess.Popen([executable, '-no-remote', '-profile', str(profile),
                                    '-width', '1000', '-height', '760', fixture.as_uri()],
                                   env=env, stdout=browser_log, stderr=browser_log, start_new_session=True)
        deadline = time.monotonic() + 20
        window = None
        while time.monotonic() < deadline and browser.poll() is None:
            QTest.qWait(120)
            if probe is not None:
                probe.cancel()
                probe.deleteLater()
            probe = SnapProbe()
            window = next((window for window in probe.windows if window['pid'] == browser.pid), None)
            if window is not None:
                break
        if window is None:
            report.update(result='skipped', reason='Owned Firefox did not create a native window.',
                          browser_exit=browser.poll())
            return 77
        QTest.qWait(1000)
        physical, logical = window.get('native_rect', window['rect']), window['rect']
        report['window'] = {'pid': browser.pid, 'id': window['id'],
                            'logical': values(logical), 'native': values(physical)}
        # Restrict backend probes to the owned browser, without moving input or
        # raising existing user windows. The selection UI freezes this snapshot.
        probe.windows = [window]
        report['before_production_metadata'] = inspector('--inspect', str(browser.pid))
        rects, elapsed = request(logical.center())
        report['first_production_probe'] = {'point': [logical.center().x(), logical.center().y()],
                                            'elapsed_ms': elapsed, 'rectangles': [values(r) for r in rects]}
        metadata = inspector('--inspect', str(browser.pid), '--names')
        report['fixture_metadata'] = metadata
        if not all(key in metadata['targets'] for key in LABELS):
            report.update(result='failed', reason='Firefox did not expose every fixture target.',
                          available_targets=sorted(metadata['targets']))
            return 1
        passed = True
        expected_rects, query_points = {}, {}
        for key, target in metadata['targets'].items():
            expected = logical_rectangle(QRect(*target['rect']), logical, physical)
            point = expected.center()
            if key == 'button':
                point = QPoint(expected.x() + 12, expected.center().y())
            elif key == 'card':
                point = expected.topLeft() + QPoint(12, 12)
            elif key == 'article':
                point = expected.bottomRight() - QPoint(12, 12)
            elif key in GAP_LABELS:
                point = QPoint(expected.x() + 8, expected.center().y())
            expected_rects[key], query_points[key] = expected, point
            rects, elapsed = request(point)
            exact = any(all(abs(a-b) <= 3 for a, b in zip(values(expected), values(rect))) for rect in rects)
            parent = any(rect != expected and rect.contains(expected) for rect in rects)
            native = native_point(point, logical, physical)
            report['targets'][key] = {'expected': values(expected), 'point': [point.x(), point.y()],
                                      'rectangles': [values(r) for r in rects], 'elapsed_ms': elapsed,
                                      'exact_element': exact, 'enclosing_candidate': parent,
                                      'native_hit_paths': inspector('--trace', str(browser.pid), str(native.x()), str(native.y()))}
            passed = passed and exact and parent
        if passed:
            combined = expected_rects['card'].united(expected_rects['article'])
            gap_point = QPoint(expected_rects['card'].center().x(),
                               (expected_rects['card'].bottom() + expected_rects['article'].top()) // 2)
            gap_rects, elapsed = request(gap_point)
            assert combined in gap_rects, ('Missing Firefox combined gap region', [values(r) for r in gap_rects])
            report['gap_selection'] = {'expected': values(combined), 'exact_combined_region': True,
                                       'elapsed_ms': elapsed, 'candidates': [values(r) for r in gap_rects]}
            multi_cases = multi_gap_cases(expected_rects)
            report['multi_gap_selection'] = {}
            for case in multi_cases:
                rects, elapsed = request(case['point'])
                assert case['expected'] in rects, (
                    'Missing Firefox multi-element combined region', case['name'],
                    values(case['expected']), [values(rect) for rect in rects])
                report['multi_gap_selection'][case['name']] = {
                    'members': list(case['members']),
                    'point': [case['point'].x(), case['point'].y()],
                    'expected': values(case['expected']), 'exact_combined_region': True,
                    'elapsed_ms': elapsed, 'candidates': [values(rect) for rect in rects],
                }
            tiles = []
            for screen in app.screens():
                image = QImage(screen.geometry().size(), QImage.Format_RGB32)
                image.fill(QColor('#26324b'))
                tiles.append(ScreenTile(screen.geometry(), image))
            settings = QSettings(str(Path(temp.name) / 'settings.ini'), QSettings.IniFormat)
            settings.setValue('smart_selection', True)
            settings.setValue('element_selection', True)
            settings.setValue('hints_enabled', False)
            with patch('rainshot.capture.QCursor') as cursor:
                cursor.pos.return_value = query_points['button']
                overlay = SelectionOverlay(tiles, settings)
            overlay.setMouseTracking(False)
            assert wait_until(lambda: expected_rects['button'] in overlay.snap_rects, 5), 'Frozen overlay missed Firefox button.'
            chosen = overlay.selection.translated(overlay.bounds.topLeft())
            assert chosen == expected_rects['button'], 'Frozen overlay did not choose the exact Firefox button.'
            QTest.keyClick(overlay, Qt.Key_Tab)
            enclosing = overlay.selection.translated(overlay.bounds.topLeft())
            assert enclosing != chosen and enclosing.contains(chosen), 'Tab did not choose an enclosing Firefox region.'
            overlay.update_hover(query_points['image'])
            assert wait_until(lambda: expected_rects['image'] in overlay.snap_rects, 5), 'Frozen overlay missed Firefox image.'
            overlay.update_hover(gap_point)
            assert wait_until(lambda: combined in overlay.snap_rects, 5), 'Frozen overlay missed Firefox gap region.'
            assert overlay.selection.translated(overlay.bounds.topLeft()) == combined
            multi_overlay = {}
            for case in multi_cases:
                overlay.update_hover(case['point'])
                multi_overlay[case['name']] = assert_overlay_default_union(
                    overlay, case['expected'], lambda expected, rects: expected in rects, wait_until)
            report['frozen_overlay'] = {'button': True, 'image': True, 'tab_parent': True,
                                        'gap_combined': True,
                                        'multi_gap_combined': multi_overlay,
                                        'background_pixels': 'synthetic; no desktop image exported',
                                        'hover_input': 'fixed fixture coordinates; pointer unchanged'}
        report['result'] = 'passed' if passed else 'failed'
        return 0 if passed else 1
    except Exception as error:
        report['error_type'], report['error'] = type(error).__name__, str(error)
        return 1
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
            if report['result'] != 'passed':
                report['owned_browser_log_tail'] = (Path(temp.name) / 'firefox.log').read_text(errors='replace')[-4000:]
        temp.cleanup()
        (output / 'firefox-snap-native.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({'result': report['result'], 'report': str(output / 'firefox-snap-native.json')}))


if __name__ == '__main__':
    raise SystemExit(main())

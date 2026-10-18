"""Opt-in native large-element gap QA using only an owned local browser/profile.

Run ``PYTHONPATH=. python3 tests/desktop_large_gap_snap.py REPORTDIR chromium``
or replace chromium with firefox. Firefox needs an enabled accessibility bridge;
the private session runner enables it without changing the live desktop.
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
from collections import deque
from pathlib import Path
from unittest.mock import patch

from browser_gap_fixture import assert_overlay_default_union


LABELS = {
    'tall': 'Rainshot 600 tall element',
    'tall_a': 'Rainshot tall small A',
    'tall_b': 'Rainshot tall small B',
    'wide': 'Rainshot 500 wide element',
    'wide_a': 'Rainshot wide small A',
    'wide_b': 'Rainshot wide small B',
}


def inspect_fixture(pid):
    import pyatspi
    from rainshot.accessible import _owned_process
    pyatspi.Atspi.set_timeout(100, 100)
    targets = {}
    deadline = time.monotonic() + 4
    for application in pyatspi.Registry.getDesktop(0):
        if time.monotonic() >= deadline:
            break
        try:
            if not _owned_process(int(application.get_process_id()), pid):
                continue
            queue = deque([application])
            visited = 0
            while queue and visited < 1200 and time.monotonic() < deadline:
                node = queue.popleft()
                visited += 1
                try:
                    state = node.getState()
                    ext = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                    valid = (state.contains(pyatspi.STATE_VISIBLE) and state.contains(pyatspi.STATE_SHOWING)
                             and ext.width > 3 and ext.height > 3 and ext.x > -100000)
                    name = node.name
                    if valid and name in LABELS.values():
                        key = next(key for key, label in LABELS.items() if label == name)
                        targets[key] = [ext.x, ext.y, ext.width, ext.height]
                except Exception:
                    pass
                try:
                    queue.extend(node.getChildAtIndex(index) for index in range(min(96, node.childCount)))
                except Exception:
                    pass
        except Exception:
            continue
    return targets


if len(sys.argv) > 1 and sys.argv[1] == '--inspect':
    print(json.dumps(inspect_fixture(int(sys.argv[2]))))
    raise SystemExit(0)


def main():
    from PyQt5.QtCore import QPoint, QRect, QSettings
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    from rainshot.capture import SelectionOverlay
    from rainshot.imaging import ScreenTile
    from rainshot.snap import SnapProbe, logical_rectangle

    if len(sys.argv) != 3 or sys.argv[2] not in ('chromium', 'firefox'):
        raise SystemExit('Provide report directory and chromium/firefox.')
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    kind = sys.argv[2]
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {'result': 'failed', 'browser': kind, 'scope': 'Owned local fixture/disposable profile only',
              'accessibility_forced': False, 'targets': {}, 'gap_selection': {}}
    browser = probe = overlay = log = None
    temp = tempfile.TemporaryDirectory(prefix='rainshot-large-gap-')

    def wait_until(predicate, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if predicate():
                return True
            QTest.qWait(35)
        return bool(predicate())

    def values(rect):
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    def matching(expected, rects):
        return any(all(abs(a - b) <= 3 for a, b in zip(values(expected), values(rect))) for rect in rects)

    def request(point):
        replies = []
        receiver = lambda query, rects: replies.append(list(rects)) if query == point else None
        probe.ready_at.connect(receiver)
        probe.request(point)
        assert wait_until(lambda: bool(replies), 5), 'Production probe timed out.'
        probe.ready_at.disconnect(receiver)
        return replies[0]

    try:
        binary = shutil.which(kind) or (shutil.which('chromium-browser') if kind == 'chromium' else None)
        if not binary or app.platformName() != 'xcb' or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            report.update(result='skipped', reason='Required native X11 browser unavailable.')
            return 77
        address = subprocess.check_output([
            'gdbus', 'call', '--session', '--dest', 'org.a11y.Bus', '--object-path', '/org/a11y/bus',
            '--method', 'org.a11y.Bus.GetAddress'], text=True, timeout=4)
        os.environ['AT_SPI_BUS_ADDRESS'] = ast.literal_eval(address.strip())[0]
        env = dict(os.environ, NO_AT_BRIDGE='0')
        for key in ('QT_QPA_PLATFORM', 'GNOME_ACCESSIBILITY', 'QT_ACCESSIBILITY', 'QT_LINUX_ACCESSIBILITY_ALWAYS_ON'):
            env.pop(key, None)
        fixture = Path(__file__).with_name('browser_large_gap_fixture.html').resolve()
        profile = Path(temp.name) / 'profile'
        log = open(Path(temp.name) / 'browser.log', 'w')
        if kind == 'chromium':
            command = [binary, '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check',
                       '--disable-background-networking', '--disable-component-update', '--disable-sync',
                       '--disable-extensions', '--disable-default-apps', '--metrics-recording-only',
                       '--password-store=basic', '--window-size=1000,760', fixture.as_uri()]
        else:
            profile.mkdir()
            (profile / 'user.js').write_text('\n'.join([
                'user_pref("browser.shell.checkDefaultBrowser", false);',
                'user_pref("browser.startup.homepage_override.mstone", "ignore");',
                'user_pref("browser.aboutwelcome.enabled", false);',
                'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
                'user_pref("toolkit.telemetry.enabled", false);',
                'user_pref("browser.safebrowsing.phishing.enabled", false);',
                'user_pref("browser.safebrowsing.malware.enabled", false);',
            ]))
            command = [binary, '-no-remote', '-profile', str(profile), '-width', '1000', '-height', '760', fixture.as_uri()]
        browser = subprocess.Popen(command, env=env, stdout=log, stderr=log, start_new_session=True)
        window = None
        until = time.monotonic() + 20
        while time.monotonic() < until and browser.poll() is None:
            QTest.qWait(120)
            if probe is not None:
                probe.cancel()
                probe.deleteLater()
            probe = SnapProbe()
            window = next((window for window in probe.windows if window['pid'] == browser.pid), None)
            if window is not None:
                break
        assert window is not None, 'Owned browser did not create a native window.'
        probe.windows = [window]
        QTest.qWait(1000)
        logical, physical = window['rect'], window.get('native_rect', window['rect'])
        report['window'] = {'logical': values(logical), 'native': values(physical)}
        # Activate default Chromium through the production geometry probe before
        # the inspector reads any accessible name in the owned fixture.
        report['first_production_probe'] = [values(rect) for rect in request(logical.center())]
        targets = {}
        until = time.monotonic() + 15
        while time.monotonic() < until:
            try:
                targets = json.loads(subprocess.check_output([
                    sys.executable, str(Path(__file__).resolve()), '--inspect', str(browser.pid),
                ], env=env, text=True, timeout=6))
            except (subprocess.SubprocessError, ValueError):
                pass
            if all(key in targets for key in LABELS):
                break
            QTest.qWait(300)
        assert all(key in targets for key in LABELS), ('Missing visible fixture targets', sorted(targets))
        expected = {key: logical_rectangle(QRect(*rect), logical, physical) for key, rect in targets.items()}
        for key, rect in expected.items():
            candidates = request(QPoint(rect.x() + 8, rect.center().y()))
            assert matching(rect, candidates), ('Missing exact element', key, values(rect), [values(r) for r in candidates])
            report['targets'][key] = {'expected': values(rect), 'exact_element': True}
        tall = expected['tall'].united(expected['tall_a']).united(expected['tall_b'])
        wide = expected['wide'].united(expected['wide_a']).united(expected['wide_b'])
        cases = [
            ('600_tall', tall, QPoint((expected['tall_a'].right() + expected['tall_b'].left()) // 2,
                                     expected['tall_a'].center().y())),
            ('500_wide', wide, QPoint(expected['wide_a'].center().x(),
                                     (expected['wide_a'].bottom() + expected['wide_b'].top()) // 2)),
        ]
        for name, rect, point in cases:
            candidates = request(point)
            assert matching(rect, candidates), ('Missing large combined region', name, values(rect), [values(r) for r in candidates])
            report['gap_selection'][name] = {'expected': values(rect), 'point': [point.x(), point.y()],
                                            'exact_combined_region': True, 'candidates': [values(r) for r in candidates]}
        tiles = []
        for screen in app.screens():
            image = QImage(screen.geometry().size(), QImage.Format_RGB32)
            image.fill(QColor('#26324b'))
            tiles.append(ScreenTile(screen.geometry(), image))
        settings = QSettings(str(Path(temp.name) / 'settings.ini'), QSettings.IniFormat)
        for key in ('smart_selection', 'element_selection'):
            settings.setValue(key, True)
        settings.setValue('hints_enabled', False)
        with patch('rainshot.capture.QCursor') as cursor:
            cursor.pos.return_value = cases[0][2]
            overlay = SelectionOverlay(tiles, settings)
        overlay.snap.windows = [window]
        overlay.setMouseTracking(False)
        report['frozen_overlay'] = {}
        for name, rect, point in cases:
            overlay.update_hover(point)
            report['frozen_overlay'][name] = assert_overlay_default_union(overlay, rect, matching, wait_until)
        report['background_pixels'] = 'Synthetic; no desktop image exported'
        report['hover_input'] = 'Fixed fixture coordinates; pointer unchanged'
        report['result'] = 'passed'
        return 0
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
        if log is not None:
            log.close()
            if report['result'] != 'passed':
                report['owned_browser_log_tail'] = (Path(temp.name) / 'browser.log').read_text(errors='replace')[-2000:]
        temp.cleanup()
        path = output / 'large-gap-native.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({'result': report['result'], 'report': str(path)}))


if __name__ == '__main__':
    raise SystemExit(main())

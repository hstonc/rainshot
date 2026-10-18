"""Opt-in native GTK3/Qt5 element-selection regression with owned fixtures.

Run from the source root with ``PYTHONPATH=. /usr/bin/python3
tests/desktop_toolkit_snap.py /tmp/rainshot-toolkit-qa``. No user application,
pointer, clipboard or screenshot is read or changed. Two fixture windows per
toolkit cover input, scrolling/virtual items, nested containers and a button
beyond the first 64 siblings. Target widgets and AT-SPI queries run in separate
processes. Only the fixtures' geometry, roles and states enter the report.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def gtk_target():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    windows, targets = [], []
    main = Gtk.Window(title='rainshot synthetic GTK fixture')
    main.set_default_size(760, 1000)
    main.move(120, 110)
    windows.append(main)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_border_width(18)
    main.add(box)

    def attach(key, widget, exact=True, point=None):
        targets.append((key, widget, main, exact, point))
        return widget

    header = Gtk.Box(spacing=12)
    button = attach('button', Gtk.Button(label='Synthetic button'))
    header.pack_start(button, False, False, 0)
    entry = attach('entry', Gtk.Entry())
    entry.set_text('Synthetic entry')
    header.pack_start(entry, True, True, 0)
    box.pack_start(header, False, False, 0)
    label = attach('label', Gtk.Label(label='Synthetic plain label'))
    label.set_halign(Gtk.Align.START)
    box.pack_start(label, False, False, 0)
    text_scroll = Gtk.ScrolledWindow()
    text_scroll.set_size_request(-1, 105)
    text = attach('editor', Gtk.TextView())
    text.get_buffer().set_text('Synthetic editor\nSecond synthetic line')
    text_scroll.add(text)
    box.pack_start(text_scroll, False, False, 0)

    list_scroll = Gtk.ScrolledWindow()
    list_scroll.set_size_request(-1, 100)
    listing = Gtk.ListBox()
    listing.set_selection_mode(Gtk.SelectionMode.NONE)
    list_scroll.add(listing)
    for index in range(90):
        row = Gtk.ListBoxRow()
        child = Gtk.Label(label='Synthetic list item ' + str(index))
        child.set_margin_top(3)
        child.set_margin_bottom(3)
        row.add(child)
        listing.add(row)
        if index == 84:
            attach('list_row', row, point=(12, 10))
    attach('list_viewport', list_scroll, exact=False, point=(500, 80))
    box.pack_start(list_scroll, False, False, 0)

    tree_scroll = Gtk.ScrolledWindow()
    tree_scroll.set_size_request(-1, 120)
    store = Gtk.TreeStore(str)
    for index in range(90):
        parent = store.append(None, ['Synthetic tree item ' + str(index)])
        store.append(parent, ['Synthetic nested item'])
    tree = Gtk.TreeView(model=store)
    column = Gtk.TreeViewColumn('Synthetic column', Gtk.CellRendererText(), text=0)
    tree.append_column(column)
    tree_scroll.add(tree)
    attach('tree_cell', tree, exact=False, point=(80, 57))
    box.pack_start(tree_scroll, False, False, 0)

    # GTK's alignment/box wrappers reproduce the nested containers in ordinary
    # application panels without constructing any fake accessibility proxies.
    frame = Gtk.Frame(label='Synthetic nested frame')
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    inner.set_border_width(8)
    frame.add(inner)
    nested = attach('nested_button', Gtk.Button(label='Synthetic nested button'))
    inner.pack_start(nested, False, False, 0)
    box.pack_start(frame, False, False, 0)
    grid = Gtk.Grid(column_spacing=2, row_spacing=2)
    for index in range(85):
        item = Gtk.Button(label=str(index))
        item.set_size_request(60, 27)
        grid.attach(item, index % 10, index // 10, 1, 1)
        if index == 84:
            attach('late_sibling_button', item)
    box.pack_start(grid, False, False, 0)
    other = Gtk.Window(title='rainshot synthetic GTK second window')
    other.set_default_size(350, 130)
    other.move(960, 170)
    other_button = Gtk.Button(label='Synthetic second window button')
    other.add(other_button)
    windows.append(other)
    targets.append(('second_window_button', other_button, other, True, (20, 50)))
    for window in windows:
        window.connect('destroy', Gtk.main_quit)
        window.show_all()

    def emit_geometry():
        values = []
        for key, widget, window, exact, point in targets:
            origin = window.get_window().get_origin()
            x, y = widget.translate_coordinates(window, 0, 0)
            alloc = widget.get_allocation()
            rect = [origin.x + x, origin.y + y, alloc.width, alloc.height]
            point = point or (min(12, alloc.width // 2), alloc.height // 2)
            values.append({'key': key, 'rect': rect,
                           'point': [rect[0] + point[0], rect[1] + point[1]],
                           'exact_expected': exact})
        add_header_gap(values)
        print(json.dumps({'pid': os.getpid(), 'targets': values}), flush=True)
        return False

    def ready():
        # Scroll only these owned widgets through their normal toolkit APIs.
        # A late visible row must remain discoverable when the first 64 rows
        # are outside the viewport; no desktop pointer/input is generated.
        row = listing.get_row_at_index(84)
        list_scroll.get_vadjustment().set_value(row.get_allocation().y)
        tree.scroll_to_cell(Gtk.TreePath.new_from_indices([84]), column, True, 0, 0)
        GLib.timeout_add(150, emit_geometry)
        return False

    GLib.timeout_add(800, ready)
    Gtk.main()


def qt_target():
    from PyQt5.QtCore import QPoint, QTimer
    from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLineEdit, QLabel, QTextEdit, QListWidget, QTreeWidget,
        QTreeWidgetItem, QGroupBox, QGridLayout)
    app = QApplication([])
    main = QWidget()
    main.setWindowTitle('rainshot synthetic Qt fixture')
    main.resize(760, 1000)
    main.move(120, 110)
    targets = []
    box = QVBoxLayout(main)
    box.setContentsMargins(18, 18, 18, 18)
    box.setSpacing(8)

    def attach(key, widget, exact=True, point=None):
        targets.append((key, widget, exact, point))
        return widget

    header = QHBoxLayout()
    header.addWidget(attach('button', QPushButton('Synthetic button')))
    header.addWidget(attach('entry', QLineEdit('Synthetic entry')))
    box.addLayout(header)
    box.addWidget(attach('label', QLabel('Synthetic plain label')))
    editor = attach('editor', QTextEdit('Synthetic editor\nSecond synthetic line'))
    editor.setFixedHeight(105)
    box.addWidget(editor)
    listing = attach('list_viewport', QListWidget(), exact=False, point=(500, 80))
    listing.setFixedHeight(100)
    listing.addItems(['Synthetic list item ' + str(index) for index in range(90)])
    box.addWidget(listing)
    tree = attach('tree_cell', QTreeWidget(), exact=False, point=(80, 57))
    tree.setHeaderLabels(['Synthetic column'])
    tree.setFixedHeight(120)
    for index in range(90):
        parent = QTreeWidgetItem(tree, ['Synthetic tree item ' + str(index)])
        QTreeWidgetItem(parent, ['Synthetic nested item'])
    box.addWidget(tree)
    frame = QGroupBox('Synthetic nested frame')
    inner = QVBoxLayout(frame)
    inner.addWidget(attach('nested_button', QPushButton('Synthetic nested button')))
    box.addWidget(frame)
    grid = QGridLayout()
    grid.setSpacing(2)
    for index in range(85):
        item = QPushButton(str(index))
        item.setMinimumSize(60, 27)
        grid.addWidget(item, index // 10, index % 10)
        if index == 84:
            attach('late_sibling_button', item)
    box.addLayout(grid)
    other = QWidget()
    other.setWindowTitle('rainshot synthetic Qt second window')
    other.resize(350, 130)
    other.move(960, 170)
    second_box = QVBoxLayout(other)
    second_box.addWidget(attach('second_window_button', QPushButton('Synthetic second window button')))
    main.show()
    other.show()

    def emit_geometry():
        values = []
        for key, widget, exact, point in targets:
            origin = widget.mapToGlobal(QPoint())
            rect = [origin.x(), origin.y(), widget.width(), widget.height()]
            point = point or (min(12, widget.width() // 2), widget.height() // 2)
            values.append({'key': key, 'rect': rect,
                           'point': [rect[0] + point[0], rect[1] + point[1]],
                           'exact_expected': exact})
        row = listing.visualItemRect(listing.item(84))
        origin = listing.viewport().mapToGlobal(row.topLeft())
        values.append({'key': 'list_row',
                       'rect': [origin.x(), origin.y(), row.width(), row.height()],
                       'point': [origin.x() + 12, origin.y() + row.height() // 2],
                       'exact_expected': True})
        add_header_gap(values)
        print(json.dumps({'pid': os.getpid(), 'targets': values}), flush=True)

    def ready():
        listing.scrollToItem(listing.item(84), listing.PositionAtTop)
        tree.scrollToItem(tree.topLevelItem(84), tree.PositionAtTop)
        QTimer.singleShot(150, emit_geometry)

    QTimer.singleShot(800, ready)
    raise SystemExit(app.exec_())


def add_header_gap(targets):
    first = next(target['rect'] for target in targets if target['key'] == 'button')
    second = next(target['rect'] for target in targets if target['key'] == 'entry')
    left, top = min(first[0], second[0]), min(first[1], second[1])
    right = max(first[0] + first[2], second[0] + second[2])
    bottom = max(first[1] + first[3], second[1] + second[3])
    assert first[0] + first[2] < second[0]
    targets.append({'key': 'header_gap', 'rect': [left, top, right - left, bottom - top],
                    'point': [(first[0] + first[2] + second[0]) // 2,
                              (max(first[1], second[1]) + min(first[1] + first[3], second[1] + second[3])) // 2],
                    'exact_expected': True})


def inspect_target(pid, x, y):
    """Read only geometry/roles/states of a known owned fixture, never names."""
    import pyatspi
    pyatspi.Atspi.set_timeout(100, 100)
    application = next((app for app in pyatspi.Registry.getDesktop(0)
                        if app.get_process_id() == pid), None)
    if application is None:
        return {'available': False, 'nodes': []}
    pending = [application]
    nodes, seen = [], set()
    deadline = time.monotonic() + 1.5
    while pending and len(seen) < 450 and time.monotonic() < deadline:
        node = pending.pop(0)
        if node in seen:
            continue
        seen.add(node)
        try:
            states = node.getState()
            component = node.queryComponent()
            ext = component.getExtents(pyatspi.DESKTOP_COORDS)
            role = node.getRoleName()
            valid = (ext.width > 0 and ext.height > 0 and ext.x <= x < ext.x + ext.width
                     and ext.y <= y < ext.y + ext.height)
            if valid or role in ('viewport', 'list box'):
                item = {'rect': [ext.x, ext.y, ext.width, ext.height],
                        'role': role, 'contains_point': valid,
                        'visible': states.contains(pyatspi.STATE_VISIBLE),
                        'showing': states.contains(pyatspi.STATE_SHOWING),
                        'managed': states.contains(pyatspi.STATE_MANAGES_DESCENDANTS)}
                try:
                    hit = component.getAccessibleAtPoint(x, y, pyatspi.DESKTOP_COORDS)
                    if hit is not None:
                        hit_rect = hit.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                        item['hit'] = {'role': hit.getRoleName(),
                                       'rect': [hit_rect.x, hit_rect.y, hit_rect.width, hit_rect.height],
                                       'self': hit == node}
                except Exception:
                    pass
                nodes.append(item)
            if not valid and node != application and role not in ('viewport', 'list box'):
                continue
        except Exception:
            pass
        try:
            pending.extend(node.getChildAtIndex(index)
                           for index in range(min(120, node.childCount)))
        except Exception:
            continue
    return {'available': True, 'nodes': nodes, 'visited': len(seen)}


def main(out):
    from PyQt5.QtCore import QPoint, QRect, QProcessEnvironment
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    from rainshot.snap import SnapProbe, logical_rectangle
    out.mkdir(parents=True, exist_ok=True)
    def refresh_bus():
        address = subprocess.check_output([
            'gdbus', 'call', '--session', '--dest', 'org.a11y.Bus',
            '--object-path', '/org/a11y/bus', '--method', 'org.a11y.Bus.GetAddress',
        ], text=True, timeout=4)
        os.environ['AT_SPI_BUS_ADDRESS'] = ast.literal_eval(address.strip())[0]

    refresh_bus()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {'fixture': 'owned synthetic GTK3 and Qt5 widgets',
              'platform': app.platformName(), 'inherited_qt_accessibility': os.environ.get('QT_ACCESSIBILITY'),
              'scrolling': 'Owned list and tree fixtures scroll to item 84 before querying.',
              'window_snapshot_restricted_to_fixture': True, 'toolkits': {}}
    def read_status():
        result = {}
        for key in ('IsEnabled', 'ScreenReaderEnabled'):
            try:
                value = subprocess.check_output([
                    'gdbus', 'call', '--session', '--dest', 'org.a11y.Bus',
                    '--object-path', '/org/a11y/bus', '--method', 'org.freedesktop.DBus.Properties.Get',
                    'org.a11y.Status', key], text=True, timeout=3)
                result[key] = 'true' in value
            except subprocess.SubprocessError:
                result[key] = None
        return result

    report['desktop_a11y_status_before'] = read_status()
    if app.platformName() != 'xcb':
        report.update(result='skipped', reason='Native X11 is required.')
        (out / 'toolkit-snap.json').write_text(json.dumps(report, indent=2))
        return 77
    script = str(Path(__file__).resolve())
    temp = tempfile.TemporaryDirectory(prefix='rainshot-toolkit-snap-')
    overall = True
    try:
        cases = [('gtk', False), ('qt', False)]
        for toolkit, forced in cases:
            refresh_bus()
            env = dict(os.environ, NO_AT_BRIDGE='0', XDG_CONFIG_HOME=str(Path(temp.name) / 'config'),
                       XDG_CACHE_HOME=str(Path(temp.name) / 'cache'))
            env.pop('QT_QPA_PLATFORM', None)
            env.pop('QT_ACCESSIBILITY', None)
            env.pop('QT_LINUX_ACCESSIBILITY_ALWAYS_ON', None)
            if forced:
                # Diagnostic only: this affects the disposable Qt fixture and
                # never changes desktop accessibility settings or user apps.
                env['QT_LINUX_ACCESSIBILITY_ALWAYS_ON'] = '1'
            fixture = subprocess.Popen([sys.executable, script, '--target-' + toolkit], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            probe = None
            try:
                # Target supplies only known synthetic geometry, after native
                # realization. Its output is bounded by the same cold-start time
                # as other opt-in desktop tests, independent of probe execution.
                import select
                if not select.select([fixture.stdout], [], [], 8)[0]:
                    raise RuntimeError('Fixture did not publish its geometry.')
                line = fixture.stdout.readline()
                if not line:
                    raise RuntimeError('Fixture exited: ' + fixture.stderr.read(2000))
                data = json.loads(line)
                toolkit_report = {'forced_qt_accessibility': forced, 'targets': {}}
                report['toolkits'][toolkit + ('_forced' if forced else '')] = toolkit_report
                probe = SnapProbe()
                query_env = dict(env)
                # Qt 5 can take its bridge address from the X11 root property,
                # even when its enable status comes from a private session bus.
                # Isolated status tests may query that existing bridge for the
                # owned fixture only, without changing the real root property.
                query_bus = os.environ.get('RAINSHOT_TEST_QT_QUERY_BUS') if toolkit == 'qt' else None
                if query_bus:
                    query_env['AT_SPI_BUS_ADDRESS'] = query_bus
                    process_env = QProcessEnvironment.systemEnvironment()
                    process_env.insert('AT_SPI_BUS_ADDRESS', query_bus)
                    probe.process.setProcessEnvironment(process_env)
                    toolkit_report['query_bus_source'] = 'unchanged X11 root property'
                probe.windows = [window for window in probe.windows if window['pid'] == fixture.pid]
                assert len(probe.windows) == 2, 'Both fixture windows must exist in the native snapshot.'
                replies = []
                probe.ready_at.connect(lambda point, rects: replies.append((QPoint(point), list(rects))))
                for target in data['targets']:
                    physical_point = QPoint(*target['point'])
                    window = next((window for window in probe.windows
                                   if window['native_rect'].contains(physical_point)), None)
                    assert window is not None, ('Target is outside its own native windows', target['key'])
                    logical, native = window['rect'], window['native_rect']
                    point = QPoint(logical.x() + round((physical_point.x() - native.x()) * logical.width() / native.width()),
                                   logical.y() + round((physical_point.y() - native.y()) * logical.height() / native.height()))
                    expected = logical_rectangle(QRect(*target['rect']), logical, native)
                    replies.clear()
                    started = time.monotonic()
                    probe.request(point)
                    deadline = time.monotonic() + 4
                    while not replies and time.monotonic() < deadline:
                        QTest.qWait(25)
                    rects = replies[0][1] if replies else []
                    elapsed_ms = round((time.monotonic() - started) * 1000)
                    values = [[r.x(), r.y(), r.width(), r.height()] for r in rects]
                    expected_values = [expected.x(), expected.y(), expected.width(), expected.height()]
                    exact = any(all(abs(a - b) <= 3 for a, b in zip(expected_values, values_rect))
                                for values_rect in values)
                    smaller = any(r.width() * r.height() < expected.width() * expected.height() / 2
                                  and r.contains(point) for r in rects)
                    passed = exact if target['exact_expected'] else smaller
                    diagnostic = json.loads(subprocess.check_output([
                        sys.executable, script, '--inspect', str(fixture.pid), *map(str, target['point'])],
                        env=query_env, text=True, stderr=subprocess.PIPE, timeout=3))
                    toolkit_report['targets'][target['key']] = {
                        'expected': expected_values,
                        'point': [point.x(), point.y()], 'candidates': values,
                        'elapsed_ms': elapsed_ms,
                        'exact_expected': target['exact_expected'], 'passed': passed,
                        'atspi': diagnostic}
                    overall = overall and passed
                toolkit_report['passed'] = all(value['passed'] for value in toolkit_report['targets'].values())
                if toolkit == 'qt' and not forced and not toolkit_report['passed']:
                    cases.append(('qt', True))
            finally:
                if probe is not None:
                    probe.cancel()
                    QTest.qWait(50)
                fixture.terminate()
                try:
                    fixture.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    fixture.kill()
                    fixture.wait(timeout=3)
    except Exception as error:
        report['error'] = str(error)
        overall = False
    finally:
        temp.cleanup()
    report['result'] = 'passed' if overall else 'failed'
    report['desktop_a11y_status_after'] = read_status()
    (out / 'toolkit-snap.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'result': report['result'], 'report': str(out / 'toolkit-snap.json'),
                      'toolkits': {key: {'passed': value.get('passed'),
                                        'failed': [name for name, target in value['targets'].items() if not target['passed']]}
                                   for key, value in report['toolkits'].items()},
                      'error': report.get('error')}, indent=2))
    return 0 if overall else 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--target-gtk']:
        gtk_target()
    elif sys.argv[1:] == ['--target-qt']:
        qt_target()
    elif len(sys.argv) == 5 and sys.argv[1] == '--inspect':
        print(json.dumps(inspect_target(*map(int, sys.argv[2:]))))
    elif len(sys.argv) == 2:
        raise SystemExit(main(Path(sys.argv[1]).resolve()))
    else:
        raise SystemExit('Provide an output directory.')

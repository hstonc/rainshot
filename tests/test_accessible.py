"""AT-SPI probes use visible geometry without reading application content."""
import sys
from types import SimpleNamespace

import pytest

from rainshot import accessible


VISIBLE = {'visible', 'showing'}


class States:
    def __init__(self, values):
        self.values = values

    def contains(self, value):
        return value in self.values


class Node:
    def __init__(self, rect=None, *, role='panel', pid=100, children=(),
                 states=None, hit='self', failures=()):
        self.rect, self.role, self.pid = rect, role, pid
        self.children = list(children)
        self.states = set(VISIBLE if states is None else states)
        self.hit, self.failures = hit, set(failures)
        self.parent = None
        self.calls = []
        self.bad_indices = set()
        for child in self.children:
            child.parent = self

    def call(self, name):
        self.calls.append(name)
        if name in self.failures:
            raise RuntimeError('Stale proxy')

    @property
    def childCount(self):
        self.call('child_count')
        return len(self.children)

    def getChildAtIndex(self, index):
        self.call('child_index')
        if index in self.bad_indices:
            raise RuntimeError('Child vanished')
        return self.children[index]

    def get_process_id(self):
        self.call('pid')
        return self.pid

    def getState(self):
        self.call('state')
        return States(self.states)

    def getRole(self):
        self.call('role')
        return self.role

    def queryComponent(self):
        self.call('component')
        if self.rect is None:
            raise NotImplementedError
        return self

    def getExtents(self, coords):
        self.call('extents')
        assert coords == 'screen'
        return SimpleNamespace(**dict(zip(('x', 'y', 'width', 'height'), self.rect)))

    def getAccessibleAtPoint(self, x, y, coords):
        self.call('hit')
        assert coords == 'screen'
        if self.hit == 'unsupported':
            raise NotImplementedError
        if self.hit == 'self':
            return self
        if callable(self.hit):
            return self.hit(x, y)
        return self.hit

    @property
    def name(self):
        raise AssertionError('A geometry probe must not read application names')

    @property
    def description(self):
        raise AssertionError('A geometry probe must not read descriptions')

    def queryText(self):
        raise AssertionError('A geometry probe must not read text')

    def queryAction(self):
        raise AssertionError('A geometry probe must not manipulate applications')

    def getAttributes(self):
        raise AssertionError('A geometry probe must not inspect DOM attributes')

    def __str__(self):
        raise AssertionError('pyatspi.__str__ reads names')


@pytest.fixture
def atspi(monkeypatch):
    desktop = Node(role='desktop')
    timeouts = []
    api = SimpleNamespace(
        Registry=SimpleNamespace(getDesktop=lambda index: desktop),
        Atspi=SimpleNamespace(set_timeout=lambda *args: timeouts.append(args)),
        DESKTOP_COORDS='screen', STATE_VISIBLE='visible', STATE_SHOWING='showing',
        STATE_DEFUNCT='defunct', STATE_ICONIFIED='iconified', STATE_ACTIVE='active',
        STATE_MANAGES_DESCENDANTS='managed', ROLE_INVALID='invalid',
        ROLE_APPLICATION='application', ROLE_DESKTOP_FRAME='desktop',
        ROLE_GROUPING='grouping', ROLE_PANEL='panel', ROLE_FILLER='filler',
        ROLE_SECTION='section', ROLE_VIEWPORT='viewport',
        ROLE_REDUNDANT_OBJECT='redundant', ROLE_UNKNOWN='unknown')
    monkeypatch.setitem(sys.modules, 'pyatspi', api)
    return desktop, timeouts


def attach(desktop, *windows, pid=100):
    application = Node(role='application', pid=pid, children=windows)
    desktop.children.append(application)
    application.parent = desktop
    return application


@pytest.mark.parametrize('rects,point,combined', [
    ([(20, 40, 100, 90), (140, 55, 120, 70)], (130, 80), [20, 40, 240, 90]),
    ([(20, 40, 100, 90), (35, 150, 90, 60)], (70, 140), [20, 40, 105, 170]),
])
@pytest.mark.parametrize('hit', ['self', 'unsupported'])
def test_gap_between_visible_siblings_adds_combined_selection(atspi, rects, point, combined, hit):
    desktop, _ = atspi
    children = [Node(rect, role='button') for rect in rects]
    panel = Node((10, 20, 300, 230), children=children, hit=hit)
    window = Node((0, 0, 400, 300), role='frame', children=[panel], hit=panel)
    attach(desktop, window)
    results = accessible.rectangles(100, *point, (0, 0, 400, 300))
    assert results[0] == combined
    assert [10, 20, 300, 230] in results and [0, 0, 400, 300] in results


@pytest.mark.parametrize('second,states,point', [
    ((140, 40, 100, 90), {'visible'}, (130, 80)),
    ((300, 40, 20, 90), VISIBLE, (200, 80)),
    ((140, 160, 100, 90), VISIBLE, (130, 80)),
    ((140, 40, 100, 90), VISIBLE, (70, 80)),
])
def test_gap_does_not_join_hidden_distant_misaligned_or_hit_controls(atspi, second, states, point):
    desktop, _ = atspi
    first = Node((20, 40, 100, 90), role='button')
    other = Node(second, role='button', states=states)
    panel = Node((10, 20, 340, 250), children=[first, other])
    window = Node((0, 0, 400, 300), role='frame', children=[panel], hit=panel)
    attach(desktop, window)
    results = accessible.rectangles(100, *point, (0, 0, 400, 300))
    union = [20, 40, max(120, second[0] + second[2]) - 20,
             max(130, second[1] + second[3]) - 40]
    assert union not in results


def test_gap_groups_three_neighbours_and_clips_each_sibling_to_parent(atspi):
    desktop, _ = atspi
    panel = Node((10, 20, 280, 130), children=[
        Node((-50, 40, 90, 180), role='button'),
        Node((60, 40, 100, 180), role='button'),
        Node((180, 40, 150, 180), role='button')])
    window = Node((0, 0, 400, 300), role='frame', children=[panel], hit=panel)
    attach(desktop, window)
    assert accessible.rectangles(100, 170, 80, (0, 0, 400, 300))[0] == [10, 40, 280, 110]


@pytest.mark.parametrize('rects,point,combined', [
    ([(20, 40, 100, 90), (140, 40, 100, 90), (260, 40, 100, 90)],
     (130, 85), (20, 40, 340, 90)),
    ([(20, 40, 100, 90), (140, 40, 100, 90), (260, 40, 100, 90), (380, 40, 100, 90)],
     (250, 85), (20, 40, 460, 90)),
    ([(20, 40, 100, 48), (140, 40, 100, 48), (20, 108, 100, 48)],
     (130, 98), (20, 40, 220, 116)),
    ([(20, 40, 100, 48), (140, 40, 100, 48), (20, 108, 100, 48), (140, 108, 100, 48)],
     (130, 98), (20, 40, 220, 116)),
    ([(20, 40, 76, 92), (116, 60, 124, 44), (38, 152, 112, 66), (170, 132, 70, 86)],
     (160, 140), (20, 40, 220, 178)),
    ([(0, 0, 100, 100), (120, 0, 100, 100), (0, 120, 100, 600), (120, 120, 100, 100)],
     (110, 110), (0, 0, 220, 720)),
    ([(0, 0, 100, 100), (120, 0, 100, 100), (240, 0, 500, 100)],
     (110, 50), (0, 0, 740, 100)),
    ([(0, 0, 100, 100), (0, 120, 100, 100), (0, 240, 100, 500)],
     (50, 110), (0, 0, 100, 740)),
    ([(0, 0, 100, 100), (120, 0, 100, 100), (0, 120, 100, 100),
      (120, 120, 100, 100), (80, 70, 160, 30)],
     (110, 110), (0, 0, 240, 220)),
])
def test_multi_element_gap_uses_complete_extrema_and_is_order_independent(rects, point, combined):
    assert accessible._gap_rectangles(rects, *point) == {combined}
    assert accessible._gap_rectangles(list(reversed(rects)), *point) == {combined}


@pytest.mark.parametrize('vertical', [False, True])
def test_gap_neighbourhood_stays_fixed_in_long_uniform_rows(vertical):
    rects = [(20 + index * 120, 40, 100, 90) for index in range(20)]
    point, expected = (970, 85), (740, 40, 460, 90)
    if vertical:
        rects = [(y, x, height, width) for x, y, width, height in rects]
        point = point[::-1]
        expected = (expected[1], expected[0], expected[3], expected[2])
    assert accessible._gap_rectangles(rects, *point) == {expected}


def test_gap_grid_neighbourhood_does_not_flood_into_adjacent_cells():
    rects = [(20 + column * 120, 40 + row * 68, 100, 48)
             for row in range(5) for column in range(5)]
    assert accessible._gap_rectangles(rects, 130, 98) == {(20, 40, 220, 116)}


@pytest.mark.parametrize('gap', [20, 60, 80, 100])
def test_central_grid_gap_selects_four_even_when_spacing_is_wide(gap):
    step = 100 + gap
    rects = [(column * step, row * step, 100, 100)
             for row in range(5) for column in range(5)]
    for point in [(100 + gap // 2, 100 + gap // 2),
                  (100 + gap - 1, 100 + gap // 2),
                  (100 + gap // 2, 100 + gap - 1),
                  (101, 101), (100 + gap - 1, 100 + gap - 1)]:
        assert accessible._gap_rectangles(rects, *point) == {(0, 0, 200 + gap, 200 + gap)}


def test_large_seed_does_not_expand_neighbourhood_across_small_controls():
    rects = [(0, 0, 1000, 100)] + [(1020 + 40 * index, 0, 20, 100) for index in range(20)]
    assert accessible._gap_rectangles(rects, 1010, 50) == {(0, 0, 1080, 100)}


def test_gap_excludes_distant_and_hidden_third_elements(atspi):
    desktop, _ = atspi
    panel = Node((0, 0, 500, 200), children=[
        Node((20, 40, 100, 90), role='button'),
        Node((140, 40, 100, 90), role='button'),
        Node((300, 40, 100, 90), role='button'),
        Node((250, 40, 40, 90), role='button', states={'visible'})])
    frame = Node((0, 0, 500, 300), role='frame', children=[panel], hit=panel)
    attach(desktop, frame)
    assert accessible.rectangles(100, 130, 85, (0, 0, 500, 300))[0] == [20, 40, 220, 90]


def test_multi_gap_is_default_candidate_without_retaining_smaller_pair(atspi):
    desktop, _ = atspi
    panel = Node((0, 0, 500, 200), children=[
        Node((20 + index * 120, 40, 100, 90), role='button') for index in range(3)])
    frame = Node((0, 0, 500, 300), role='frame', children=[panel], hit=panel)
    attach(desktop, frame)
    results = accessible.rectangles(100, 130, 85, (0, 0, 500, 300))
    assert results[0] == [20, 40, 340, 90]
    assert [20, 40, 220, 90] not in results


def test_deep_hit_restores_ancestors_and_clips_to_every_visible_parent(atspi):
    desktop, timeouts = atspi
    button = Node((30, 90, 360, 200), role='button')
    section = Node((40, 80, 300, 500), children=[button])
    document = Node((20, 30, 800, 1000), role='document', children=[section])
    window = Node((0, 0, 400, 300), role='frame', children=[document], hit=button)
    attach(desktop, window)
    assert accessible.rectangles(100, 100, 100, (0, 0, 400, 300)) == [
        [40, 90, 300, 200], [40, 80, 300, 220],
        [20, 30, 380, 270], [0, 0, 400, 300]]
    assert timeouts == [(100, 100)]
    assert 'child_count' not in document.calls and 'child_count' not in section.calls


@pytest.mark.parametrize('hit', ['self', 'unsupported', None])
def test_child_geometry_fallback_finds_control_when_toolkit_hit_is_unhelpful(atspi, hit):
    desktop, _ = atspi
    outside = Node((300, 200, 20, 20), role='button')
    button = Node((30, 40, 60, 30), role='button')
    panel = Node((10, 20, 300, 100), children=[outside, button], hit=hit)
    window = Node((0, 0, 400, 300), role='frame', children=[panel], hit=hit)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [
        [30, 40, 60, 30], [10, 20, 300, 100], [0, 0, 400, 300]]
    assert 'hit' not in outside.calls


def test_visible_noncomponent_wrapper_does_not_hide_its_children(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    wrapper = Node(children=[button], role='grouping')
    window = Node((0, 0, 400, 300), role='frame', children=[wrapper])
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]


def test_noncomponent_application_root_wrappers_reveal_matching_window(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button)
    wrapper = Node(role='grouping', children=[Node(role='panel', children=[frame])])
    attach(desktop, wrapper)
    assert accessible.rectangles(100, 40, 50, (0, 0, 400, 300)) == [
        [30, 40, 60, 30], [0, 0, 400, 300]]


def test_matching_window_is_probed_before_slow_unrelated_application_metadata(atspi, monkeypatch):
    desktop, _ = atspi
    clock = [0]
    monkeypatch.setattr(accessible.time, 'monotonic', lambda: clock[0])
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button)
    attach(desktop, frame)
    unrelated = []
    for _ in range(9):
        application = attach(desktop, pid=999)
        def slow_pid(application=application):
            application.call('pid')
            clock[0] += .101
            return 999
        application.get_process_id = slow_pid
        unrelated.append(application)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]
    assert clock[0] == 0 and all(not application.calls for application in unrelated)


def test_root_sibling_discovery_preserves_time_for_a_frame_already_found(atspi, monkeypatch):
    desktop, _ = atspi
    clock = [0]
    monkeypatch.setattr(accessible.time, 'monotonic', lambda: clock[0])
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button)
    application = attach(desktop, frame, *[
        Node((1000, 1000, 100, 100), role='frame') for _ in range(23)])
    original_child = application.getChildAtIndex
    def slow_child(index):
        clock[0] += .12
        return original_child(index)
    application.getChildAtIndex = slow_child
    assert accessible.rectangles(100, 40, 50, (0, 0, 400, 300)) == [
        [30, 40, 60, 30], [0, 0, 400, 300]]
    assert clock[0] < accessible.PROBE_SECONDS
    assert application.calls.count('child_index') < accessible.MAX_WINDOWS


def test_root_wrappers_do_not_exhaust_the_element_node_allowance(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button)
    wrappers = [Node(role='grouping', children=[
        Node(role='grouping') for _ in range(accessible.MAX_CHILDREN)]) for _ in range(3)]
    attach(desktop, frame, *wrappers)
    assert accessible.rectangles(100, 40, 50, (0, 0, 400, 300)) == [
        [30, 40, 60, 30], [0, 0, 400, 300]]
    assert sum(node.calls.count('state') for wrapper in wrappers
               for node in wrapper.children) < accessible.MAX_NODES - 4


def test_selected_frame_relation_query_reveals_a_late_browser_tree(atspi, monkeypatch):
    desktop, _ = atspi
    clock, sleeps = [0], []
    monkeypatch.setattr(accessible.time, 'monotonic', lambda: clock[0])
    def sleep(duration):
        sleeps.append(duration)
        clock[0] += duration
    monkeypatch.setattr(accessible.time, 'sleep', sleep)
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame')
    other = Node((1000, 1000, 400, 300), role='frame')
    other.getRelationSet = lambda: pytest.fail('Do not prepare an unselected window')
    class PrivateRelations:
        def __iter__(self):
            raise AssertionError('Do not traverse relation targets')
        def __str__(self):
            raise AssertionError('Do not stringify relation targets')
    def relations():
        frame.call('relations')
        return PrivateRelations()
    def refresh():
        frame.call('cache')
        if clock[0] >= .12:
            frame.children = [button]
            button.parent = frame
    frame.getRelationSet, frame.clearCache = relations, refresh
    attach(desktop, other, frame)
    assert accessible.rectangles(100, 40, 50, (0, 0, 400, 300)) == [
        [30, 40, 60, 30], [0, 0, 400, 300]]
    assert frame.calls.count('relations') == 1
    assert clock[0] == pytest.approx(.12)
    assert all(0 < duration <= accessible.PREPARE_INTERVAL for duration in sleeps)


@pytest.mark.parametrize('error', [RuntimeError, NotImplementedError])
def test_relation_query_failure_preserves_normal_hit_testing(atspi, monkeypatch, error):
    desktop, _ = atspi
    monkeypatch.setattr(accessible.time, 'sleep', lambda duration: pytest.fail('Do not retry an unsupported query'))
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button)
    def relations():
        frame.call('relations')
        raise error('Unsupported metadata')
    frame.getRelationSet = relations
    frame.clearCache = lambda: pytest.fail('Do not clear after a failed query')
    attach(desktop, frame)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]
    assert frame.calls.count('relations') == 1


def test_empty_browser_tree_wait_has_a_small_fixed_limit(atspi, monkeypatch):
    desktop, _ = atspi
    clock, sleeps = [0], []
    monkeypatch.setattr(accessible.time, 'monotonic', lambda: clock[0])
    def sleep(duration):
        sleeps.append(duration)
        clock[0] += duration
    monkeypatch.setattr(accessible.time, 'sleep', sleep)
    frame = Node((0, 0, 400, 300), role='frame')
    frame.getRelationSet = lambda: ()
    frame.clearCache = lambda: frame.call('cache')
    attach(desktop, frame)
    assert accessible.rectangles(100, 40, 50) == [[0, 0, 400, 300]]
    assert clock[0] == pytest.approx(accessible.PREPARE_SECONDS)
    assert len(sleeps) <= 7
    assert 'hit' in frame.calls


@pytest.mark.parametrize('query_time', [.7, .9])
def test_browser_preparation_respects_remaining_budget_and_retains_frame(atspi, monkeypatch, query_time):
    desktop, _ = atspi
    clock = [0]
    monkeypatch.setattr(accessible.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(accessible.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0] + duration))
    frame = Node((0, 0, 400, 300), role='frame')
    def relations():
        frame.call('relations')
        clock[0] += query_time
        return ()
    frame.getRelationSet = relations
    frame.clearCache = lambda: frame.call('cache')
    attach(desktop, frame)
    assert accessible.rectangles(100, 40, 50) == [[0, 0, 400, 300]]
    assert clock[0] == pytest.approx(max(query_time, accessible.PROBE_SECONDS))
    assert 'hit' not in frame.calls
    if query_time > accessible.PROBE_SECONDS:
        assert 'cache' not in frame.calls and 'child_count' not in frame.calls


def test_root_wrappers_preserve_best_native_window_match(atspi):
    desktop, _ = atspi
    wrong_button = Node((130, 140, 40, 30), role='button')
    wrong_frame = Node((0, 0, 700, 500), role='frame', children=[wrong_button], hit=wrong_button)
    button = Node((130, 140, 50, 30), role='button')
    frame = Node((100, 100, 300, 200), role='frame', children=[button], hit=button)
    wrapper = Node(role='grouping', children=[wrong_frame, frame])
    attach(desktop, wrapper)
    assert accessible.rectangles(100, 140, 150, (100, 100, 300, 200)) == [
        [130, 140, 50, 30], [100, 100, 300, 200]]
    assert not wrong_button.calls and 'hit' not in wrong_frame.calls


def test_stale_hidden_and_cyclic_root_wrappers_do_not_block_healthy_frame(atspi):
    desktop, _ = atspi
    cycle = Node(role='grouping')
    cycle.children = [cycle]
    hidden = Node(role='grouping', states={'visible'},
                  children=[Node((20, 20, 20, 20), role='frame')])
    stale = Node(role='grouping', failures=['state'])
    button = Node((30, 40, 60, 30), role='button')
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button)
    wrapper = Node(role='grouping', children=[stale, hidden, cycle, frame])
    attach(desktop, wrapper)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]
    assert not hidden.children[0].calls and cycle.calls.count('state') == 1


def test_renderer_root_is_used_when_exact_application_exposes_no_window(atspi, monkeypatch):
    desktop, _ = atspi
    attach(desktop)
    button = Node((30, 40, 60, 30), role='button', pid=120)
    frame = Node((0, 0, 400, 300), role='frame', children=[button], hit=button, pid=120)
    attach(desktop, Node(role='grouping', children=[frame]), pid=120)
    monkeypatch.setattr(accessible, '_owned_process', lambda candidate, target: candidate == 120)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]


@pytest.mark.parametrize('states', [
    {'visible'}, {'showing'}, VISIBLE | {'defunct'}, VISIBLE | {'iconified'}, set()])
def test_hidden_or_defunct_parent_blocks_even_visible_deep_hit(atspi, states):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    hidden = Node((10, 20, 300, 100), children=[button], states=states)
    window = Node((0, 0, 400, 300), role='frame', children=[hidden], hit=button)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[0, 0, 400, 300]]
    assert 'extents' not in hidden.calls and not button.calls


def test_clipped_out_child_cannot_escape_viewport(atspi):
    desktop, _ = atspi
    off_viewport = Node((20, 100, 200, 100), role='image')
    viewport = Node((20, 20, 200, 60), role='viewport', children=[off_viewport])
    window = Node((0, 0, 400, 300), role='frame', children=[viewport], hit=off_viewport)
    attach(desktop, window)
    assert accessible.rectangles(100, 50, 120) == [[0, 0, 400, 300]]


def test_exceptions_are_isolated_to_vanished_applications_and_children(atspi):
    desktop, _ = atspi
    attach(desktop, Node((0, 0, 400, 300))).failures.add('pid')
    missing_child = Node((20, 20, 100, 100))
    invalid_geometry = Node((20, 20, 100, 100), failures=['extents'])
    invalid_state = Node((20, 20, 100, 100), failures=['state'])
    button = Node((30, 40, 60, 30), role='button')
    window = Node((0, 0, 400, 300), role='frame',
                  children=[missing_child, invalid_geometry, invalid_state, button])
    window.bad_indices.add(0)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]


def test_virtual_managed_descendants_are_never_enumerated(atspi):
    desktop, _ = atspi
    virtual_table = Node((20, 20, 200, 200), role='table', states=VISIBLE | {'managed'},
                         children=[Node((30, 40, 60, 30)) for _ in range(1000)])
    window = Node((0, 0, 400, 300), role='frame', children=[virtual_table], hit=virtual_table)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[20, 20, 200, 200], [0, 0, 400, 300]]
    assert 'child_count' not in virtual_table.calls


def test_bad_hit_from_unrelated_tree_falls_back_without_inspecting_its_content(atspi, monkeypatch):
    desktop, _ = atspi
    foreign = Node((30, 40, 60, 30), pid=200, role='button')
    foreign_window = Node((0, 0, 400, 300), children=[foreign], pid=200)
    foreign_application = attach(desktop, foreign_window, pid=200)
    button = Node((40, 40, 60, 30), role='button')
    window = Node((0, 0, 400, 300), role='frame', children=[button], hit=foreign)
    attach(desktop, window)
    monkeypatch.setattr(accessible, '_owned_process', lambda candidate, target: candidate == target)
    assert accessible.rectangles(100, 50, 50) == [[40, 40, 60, 30], [0, 0, 400, 300]]
    assert foreign.calls == [] and foreign_window.calls == []
    assert foreign_application.calls == ['pid']


def test_cycles_in_hits_parent_chain_and_children_are_bounded(atspi):
    desktop, _ = atspi
    broken_hit = Node((40, 40, 60, 30), role='button')
    broken_hit.parent = broken_hit
    window = Node((0, 0, 400, 300), role='frame', hit=broken_hit)
    window.children.append(window)
    attach(desktop, window)
    assert accessible.rectangles(100, 50, 50) == [[0, 0, 400, 300]]
    assert not broken_hit.calls and window.calls.count('hit') == 1


def test_window_bounds_select_one_foreground_frame_within_same_application(atspi):
    desktop, _ = atspi
    other_button = Node((130, 140, 40, 30), role='button')
    other_window = Node((0, 0, 700, 500), role='frame', children=[other_button],
                        states=VISIBLE | {'active'}, hit=other_button)
    button = Node((130, 140, 50, 30), role='button')
    window = Node((100, 100, 300, 200), role='frame', children=[button], hit=button)
    attach(desktop, other_window, window)
    assert accessible.rectangles(100, 140, 150, (100, 100, 300, 200)) == [
        [130, 140, 50, 30], [100, 100, 300, 200]]
    assert 'hit' not in other_window.calls and not other_button.calls


def test_related_renderer_application_is_used_without_visiting_unrelated_app(atspi, monkeypatch):
    desktop, _ = atspi
    processes = {100: (1000, 1), 120: (1000, 110), 110: (1000, 100), 300: (1000, 1)}
    monkeypatch.setattr(accessible, '_process_parent', lambda pid: processes[pid])
    unrelated_window = Node((0, 0, 400, 300), pid=300)
    unrelated = attach(desktop, unrelated_window, pid=300)
    button = Node((30, 40, 60, 30), role='button', pid=120)
    window = Node((0, 0, 400, 300), role='frame', children=[button], hit=button, pid=120)
    attach(desktop, window, pid=120)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]
    assert unrelated.calls == ['pid'] and not unrelated_window.calls


@pytest.mark.parametrize('processes, expected', [
    ({100: (1000, 1), 120: (1000, 110), 110: (1000, 100)}, True),
    ({100: (1000, 1), 120: (2000, 100)}, False),
    ({100: (1000, 1), 120: (1000, 110), 110: (2000, 100)}, False),
    ({100: (1000, 1), 120: (1000, 1)}, False),
    ({100: (1000, 1), 120: (1000, 110), 110: (1000, 120)}, False),
])
def test_renderer_process_matching_is_same_uid_and_descendant_only(monkeypatch, processes, expected):
    monkeypatch.setattr(accessible, '_process_parent', lambda pid: processes[pid])
    assert accessible._owned_process(120, 100) is expected
    assert accessible._owned_process(100, 100)


def test_renderer_process_lookup_failure_is_not_geometrical_authorization(monkeypatch):
    def vanished(pid):
        raise OSError('Process exited')
    monkeypatch.setattr(accessible, '_process_parent', vanished)
    assert not accessible._owned_process(120, 100)
    assert not accessible._owned_process(0, 100)


def test_same_rectangles_are_deduplicated_and_sorted_smallest_first(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    wrapper = Node((30, 40, 60, 30), children=[button])
    window = Node((0, 0, 400, 300), role='frame', children=[wrapper], hit=button)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]


def test_fallback_child_enumeration_has_a_hard_limit(atspi):
    desktop, _ = atspi
    children = [Node((300, 200, 20, 20)) for _ in range(accessible.MAX_CHILDREN + 20)]
    children[accessible.MAX_CHILDREN - 1] = Node((30, 40, 60, 30), role='button')
    children[-1] = Node((30, 40, 70, 30), role='button')
    window = Node((0, 0, 400, 300), role='frame', children=children)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]
    assert window.calls.count('child_index') == accessible.MAX_CHILDREN
    assert not children[-1].calls


def test_time_budget_keeps_already_found_rectangles_without_further_tree_queries(atspi, monkeypatch):
    desktop, _ = atspi
    clock = [0]
    monkeypatch.setattr(accessible.time, 'monotonic', lambda: clock[0])
    def timed_out_hit(x, y):
        clock[0] = 1
        raise RuntimeError('D-Bus timeout')
    button = Node((30, 40, 60, 30), role='button')
    window = Node((0, 0, 400, 300), role='frame', children=[button], hit=timed_out_hit)
    attach(desktop, window)
    assert accessible.rectangles(100, 40, 50) == [[0, 0, 400, 300]]
    assert not button.calls


@pytest.mark.parametrize('pid, point, bounds', [
    (0, (40, 50), None), (100, (40, 50), (0, 0, -1, 10)),
    (100, (40, 50), (0, 0, 10, 10)), (100, (40, 50), (0, 0, 10)),
])
def test_invalid_or_outside_requests_do_not_query_applications(atspi, pid, point, bounds):
    desktop, _ = atspi
    attach(desktop, Node((0, 0, 400, 300)))
    assert accessible.rectangles(pid, *point, bounds) == []
    assert not desktop.calls


def test_scrolled_gtk_viewport_does_not_hide_visible_rows(atspi):
    desktop, _ = atspi
    row = Node((30, 40, 100, 26), role='list-item')
    listing = Node((20, -500, 200, 800), role='list', children=[row], hit=row)
    viewport = Node((-2147483648, -2147483648, 200, 100), role='viewport',
                    states={'visible'}, children=[listing], hit=listing)
    scroll = Node((20, 30, 200, 100), role='scroll-pane', children=[viewport], hit=None)
    frame = Node((0, 0, 400, 300), role='frame', children=[scroll], hit=scroll)
    attach(desktop, frame)
    rects = accessible.rectangles(100, 40, 50, (0, 0, 400, 300))
    assert [30, 40, 100, 26] in rects and [20, 30, 200, 100] in rects
    assert all(0 <= rect[0] and 0 <= rect[1] and rect[0]+rect[2] <= 400
               and rect[1]+rect[3] <= 300 for rect in rects)


@pytest.mark.parametrize('role, states, rect', [
    ('viewport', {'visible'}, (20, 30, 200, 100)),
    ('viewport', {'showing'}, (-2147483648, -2147483648, 200, 100)),
    ('viewport', {'visible', 'defunct'}, (-2147483648, -2147483648, 200, 100)),
    ('panel', {'visible'}, (0, 0, 0, 0)),
])
def test_transparent_wrapper_exception_does_not_accept_hidden_or_stale_controls(atspi, role, states, rect):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    wrapper = Node(rect, role=role, states=states, children=[button], hit=button)
    frame = Node((0, 0, 400, 300), role='frame', children=[wrapper])
    attach(desktop, frame)
    assert accessible.rectangles(100, 40, 50) == [[0, 0, 400, 300]]
    assert not button.calls


def test_zero_size_structural_group_preserves_valid_hit_descendant(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    group = Node((0, 0, 0, 0), role='grouping', children=[button], hit=button)
    frame = Node((0, 0, 400, 300), role='frame', children=[group], hit=button)
    attach(desktop, frame)
    assert accessible.rectangles(100, 40, 50) == [[30, 40, 60, 30], [0, 0, 400, 300]]


def test_fallback_siblings_do_not_starve_deeper_matching_branch(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    branch = button
    for _ in range(3):
        branch = Node((10, 20, 200, 100), children=[branch] +
                      [Node((300, 200, 10, 10)) for _ in range(63)])
    frame = Node((0, 0, 400, 300), role='frame', children=[branch])
    attach(desktop, frame)
    assert [30, 40, 60, 30] in accessible.rectangles(100, 40, 50)


def test_deep_visible_wrappers_reach_hit_within_node_budget(atspi):
    desktop, _ = atspi
    button = Node((30, 40, 60, 30), role='button')
    branch = button
    for _ in range(35):
        branch = Node((10, 20, 200, 100), role='grouping', children=[branch])
    frame = Node((0, 0, 400, 300), role='frame', children=[branch], hit=button)
    attach(desktop, frame)
    assert [30, 40, 60, 30] in accessible.rectangles(100, 40, 50)


def test_frame_only_main_pid_can_fall_back_to_verified_renderer(atspi, monkeypatch):
    desktop, _ = atspi
    attach(desktop, Node((0, 0, 400, 300), role='frame'))
    button = Node((30, 40, 60, 30), role='button', pid=120)
    frame = Node((0, 0, 400, 300), role='frame', pid=120, children=[button], hit=button)
    attach(desktop, frame, pid=120)
    monkeypatch.setattr(accessible, '_owned_process', lambda candidate, target: candidate == 120)
    assert [30, 40, 60, 30] in accessible.rectangles(100, 40, 50)

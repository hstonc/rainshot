"""Shared geometry for opt-in Chromium/Firefox multi-element gap checks."""

GAP_LABELS = {
    'three_a': 'Rainshot three element A',
    'three_b': 'Rainshot three element B',
    'three_c': 'Rainshot three element C',
    'four_a': 'Rainshot four element A',
    'four_b': 'Rainshot four element B',
    'four_c': 'Rainshot four element C',
    'four_d': 'Rainshot four element D',
    'mixed_a': 'Rainshot mixed element A',
    'mixed_b': 'Rainshot mixed element B',
    'mixed_c': 'Rainshot mixed element C',
    'mixed_d': 'Rainshot mixed element D',
}


def multi_gap_cases(expected):
    """Use visible native element extents, rather than hard-coded screen bounds."""
    from PyQt5.QtCore import QPoint

    cases = []
    for name, members, offset in (
        ('three_l_shape', ('three_a', 'three_b', 'three_c'), (110, 58)),
        ('four_grid', ('four_a', 'four_b', 'four_c', 'four_d'), (110, 58)),
        ('four_irregular', ('mixed_a', 'mixed_b', 'mixed_c', 'mixed_d'), (140, 100)),
    ):
        bounds = expected[members[0]]
        for member in members[1:]:
            bounds = bounds.united(expected[member])
        point = expected[members[0]].topLeft() + QPoint(*offset)
        assert not any(expected[member].contains(point) for member in members), (name, point)
        assert bounds.contains(point), (name, bounds, point)
        cases.append({'name': name, 'members': members, 'point': point, 'expected': bounds})
    return cases


def assert_overlay_default_union(overlay, expected, matches, wait_until):
    """The complete nearby group must be chosen before the user presses Tab."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    assert wait_until(lambda: matches(expected, overlay.snap_rects), 5), \
        'Frozen overlay did not expose the combined multi-element region.'
    selected = overlay.selection.translated(overlay.bounds.topLeft())
    assert matches(expected, [selected]), \
        ('Frozen overlay did not select the complete group by default.', expected, selected)
    QTest.keyClick(overlay, Qt.Key_Tab)
    parent = overlay.selection.translated(overlay.bounds.topLeft())
    assert parent != selected and parent.contains(selected), \
        ('Tab did not select an enclosing region after the combined group.', selected, parent)
    return {'exact_combined_region': True, 'default_selection': True, 'tab_parent': True}

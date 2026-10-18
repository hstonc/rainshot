"""Bounded AT-SPI hit testing; only visible component geometry leaves the process.

No names, text, URLs or actions are queried. The foreground X11 window's PID and
optional screen-pixel bounds constrain the probe, including related renderer
processes. A hung application is also contained by the caller's process timeout.
"""
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from collections import deque


MAX_APPLICATIONS = 48
MAX_WINDOWS = 24
MAX_NODES = 160
MAX_CHILDREN = 64
MAX_BRANCHES = 4
MAX_DEPTH = 64
MAX_RESULTS = 48
MAX_PROCESS_PARENTS = 8
PROBE_SECONDS = 0.8
PREPARE_SECONDS = 0.24
PREPARE_INTERVAL = 0.04


def _contains(rect, x, y):
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def _intersection(first, second):
    if second is None:
        return first
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    return (left, top, right - left, bottom - top) if right > left and bottom > top else None


def _union(rectangles):
    left = min(rect[0] for rect in rectangles)
    top = min(rect[1] for rect in rectangles)
    right = max(rect[0] + rect[2] for rect in rectangles)
    bottom = max(rect[1] + rect[3] for rect in rectangles)
    return left, top, right - left, bottom - top


def _separation(first, second):
    return tuple(max(0, first[axis] - second[axis] - second[axis + 2],
                     second[axis] - first[axis] - first[axis + 2]) for axis in (0, 1))


def _gap_rectangles(rectangles, x, y):
    """Combine a local cluster of visible siblings around an empty gap.

    The closest pair enclosing the pointer anchors a fixed neighbourhood.
    Nearby members may have unequal sizes or form a grid/L shape. A row or
    column can extend by one seed-element size at either end; its neighbourhood
    never grows as more members join, preventing a flood through an entire page.
    """
    rectangles = sorted(set(rectangles))
    if len(rectangles) < 2 or any(_contains(rect, x, y) for rect in rectangles):
        return set()
    point = (x, y, 0, 0)
    seeds = []
    for index, first in enumerate(rectangles):
        for second in rectangles[index + 1:]:
            bounds = _union((first, second))
            if not _contains(bounds, x, y):
                continue
            dx, dy = _separation(first, second)
            limits = [min(256, max(24, 2 * min(first[axis + 2], second[axis + 2])))
                      for axis in (0, 1)]
            if dx > limits[0] or dy > limits[1]:
                continue
            gap = math.hypot(dx, dy)
            distance = max(math.hypot(*_separation(rect, point)) for rect in (first, second))
            if distance > max(24, gap * 1.25):
                continue
            seeds.append((distance, gap, bounds[2] * bounds[3], first, second, bounds))
    if not seeds:
        return set()
    distance, gap, _, first, second, bounds = min(seeds)
    dx, dy = _separation(first, second)
    radius = min(256, max(24, max(dx, dy) * 2, distance * 1.25))
    # A junction can have neighbours above and beside the nearest pair. Include
    # a fixed small pointer neighbourhood, even when no pair shares one row.
    bounds = _union((bounds, (x - radius, y - radius, radius * 2, radius * 2)))
    margin_x = min(first[2], second[2]) + dx if dx and not dy else 0
    margin_y = min(first[3], second[3]) + dy if dy and not dx else 0
    neighbourhood = (bounds[0] - margin_x, bounds[1] - margin_y,
                     bounds[2] + 2 * margin_x, bounds[3] + 2 * margin_y)
    candidates = [rect for rect in rectangles
                  if _intersection(rect, neighbourhood)]
    members = {first, second}
    threshold = min(256, max(12, gap * 1.25))
    near_pointer = {rect: math.hypot(*_separation(rect, point)) <= radius for rect in candidates}
    pending = [first, second]
    while pending:
        member = pending.pop()
        for rect in candidates:
            limit = max(threshold, radius) if near_pointer[member] and near_pointer[rect] else threshold
            if rect not in members and math.hypot(*_separation(member, rect)) <= limit:
                members.add(rect)
                pending.append(rect)
    # Return the complete local group rather than a smaller pair: normal
    # selection ordering uses area, so a retained pair would still win by default.
    return {_union(members)}


def _rect(extents):
    values = tuple(int(getattr(extents, name)) for name in ('x', 'y', 'width', 'height'))
    if values[2] <= 0 or values[3] <= 0 or any(abs(value) > 2**31 - 1 for value in values):
        return None
    return values


def _key(node):
    # GI proxies have stable hash/equality for an accessible, including when a
    # fresh wrapper is returned. Do not stringify: pyatspi.__str__ reads names.
    try:
        hash(node)
        return node
    except TypeError:
        return id(node)


def _process_parent(pid):
    """Read just the UID and parent PID of one identified Linux process."""
    path = '/proc/' + str(pid)
    owner = os.stat(path).st_uid
    with open(path + '/stat', encoding='utf-8') as stream:
        stat = stream.read(4096)
    # A process's comm field may itself contain parentheses or spaces.
    fields = stat[stat.rfind(')') + 1:].split()
    return owner, int(fields[1])


def _owned_process(candidate, target):
    if candidate == target:
        return True
    if candidate <= 0 or target <= 0:
        return False
    try:
        target_uid, _ = _process_parent(target)
        seen = set()
        for _ in range(MAX_PROCESS_PARENTS):
            if candidate <= 1 or candidate in seen:
                return False
            seen.add(candidate)
            owner, parent = _process_parent(candidate)
            if owner != target_uid:
                return False
            if parent == target:
                return True
            candidate = parent
    except (OSError, ValueError, IndexError):
        return False
    return False


@dataclass
class _Info:
    component: object
    bounds: object
    role: object
    active: bool
    managed: bool


class _Probe:
    def __init__(self, pyatspi, pid, x, y, bounds):
        self.api, self.pid, self.x, self.y = pyatspi, pid, x, y
        self.bounds = bounds
        self.deadline = time.monotonic() + PROBE_SECONDS
        self.infos = {}
        self.visited = set()
        self.result = set()
        self.owners = {}
        self.structural_roles = {getattr(pyatspi, name, None) for name in (
            'ROLE_GROUPING', 'ROLE_PANEL', 'ROLE_FILLER', 'ROLE_SECTION', 'ROLE_VIEWPORT')}
        self.structural_roles.discard(None)
        self.omitted_roles = {getattr(pyatspi, name, None) for name in (
            'ROLE_INVALID', 'ROLE_APPLICATION', 'ROLE_DESKTOP_FRAME',
            'ROLE_REDUNDANT_OBJECT', 'ROLE_UNKNOWN')}

    def available(self):
        return time.monotonic() < self.deadline and len(self.infos) < MAX_NODES

    def children(self, node, limit):
        try:
            count = min(max(0, int(node.childCount)), limit)
        except Exception:
            return
        for index in range(count):
            if not self.available():
                return
            try:
                child = node.getChildAtIndex(index)
            except Exception:
                continue
            if child is not None:
                yield child

    def inspect(self, node):
        key = _key(node)
        if key in self.infos:
            return self.infos[key]
        if not self.available():
            return None
        self.infos[key] = None
        try:
            states = node.getState()
            role = node.getRole()
            if (not states.contains(self.api.STATE_VISIBLE)
                    or states.contains(self.api.STATE_DEFUNCT)
                    or states.contains(self.api.STATE_ICONIFIED)):
                return None
            showing = states.contains(self.api.STATE_SHOWING)
            viewport = role is not None and role == getattr(self.api, 'ROLE_VIEWPORT', None)
            if not showing and not viewport:
                return None
            active = states.contains(self.api.STATE_ACTIVE)
            managed = states.contains(self.api.STATE_MANAGES_DESCENDANTS)
            try:
                component = node.queryComponent()
            except NotImplementedError:
                component = None
            # Non-component grouping nodes can contain visible components.
            bounds = _rect(component.getExtents(self.api.DESKTOP_COORDS)) if component else None
            # GtkViewport can report an invalid origin and omit SHOWING after
            # scrolling, even though its visible children remain on screen.
            # Pass only that structural wrapper through the validated parent
            # clip; every emitted child still needs visible/showing geometry.
            if not showing and not (viewport and component and bounds is None):
                return None
            if component and bounds is None and role not in self.structural_roles:
                return None
            info = _Info(component, bounds, role, active, managed)
            self.infos[key] = info
            return info
        except Exception:
            # A single stale AT-SPI proxy or GLib D-Bus error must not discard
            # healthy siblings, or rectangles already found along the path.
            return None

    def clip(self, info, parent):
        rect = _intersection(info.bounds, parent) if info.bounds else parent
        return rect if rect and _contains(rect, self.x, self.y) else None

    def add(self, info, clipped):
        if (info.bounds and info.role not in self.omitted_roles
                and clipped[2] > 6 and clipped[3] > 6):
            self.result.add(clipped)

    def path(self, child, ancestor):
        """Recover ancestors skipped by a toolkit's deep hit-test result."""
        result, seen = [], set()
        ancestor_key = _key(ancestor)
        for _ in range(MAX_DEPTH):
            if not self.available():
                return None
            key = _key(child)
            if key == ancestor_key:
                return list(reversed(result))
            if key in seen:
                return None
            seen.add(key)
            result.append(child)
            try:
                child = child.parent
            except Exception:
                return None
            if child is None:
                return None
        return None

    def visit(self, node, parent, depth=0):
        key = _key(node)
        if not self.available() or depth >= MAX_DEPTH or key in self.visited:
            return
        self.visited.add(key)
        info = self.inspect(node)
        if info is None:
            return
        clipped = self.clip(info, parent)
        if clipped is None:
            return
        self.add(info, clipped)
        child = None
        if info.component:
            try:
                child = info.component.getAccessibleAtPoint(self.x, self.y, self.api.DESKTOP_COORDS)
            except Exception:
                pass
        if child is not None and _key(child) != key and _key(child) not in self.visited:
            path = self.path(child, node)
            if path and depth + len(path) < MAX_DEPTH:
                next_clip = clipped
                for ancestor in path:
                    ancestor_info = self.inspect(ancestor)
                    if ancestor_info is None:
                        break
                    next_clip = self.clip(ancestor_info, next_clip)
                    if next_clip is None:
                        break
                    self.add(ancestor_info, next_clip)
                else:
                    self.visit(child, next_clip, depth + len(path))
                    return
        if info.managed:
            # Virtual tables explicitly promise hit testing; do not enumerate
            # their potentially enormous, lazily materialized descendants.
            return
        branches, siblings = [], []
        search_deadline, search_limit = self.deadline, MAX_NODES
        for child in self.children(node, MAX_CHILDREN):
            if branches and (time.monotonic() >= search_deadline or len(self.infos) >= search_limit):
                break
            if _key(child) in self.visited:
                continue
            child_info = self.inspect(child)
            if child_info is None:
                continue
            if child_info.bounds and child_info.role not in self.omitted_roles:
                sibling = _intersection(child_info.bounds, clipped)
                if sibling and sibling[2] > 6 and sibling[3] > 6:
                    siblings.append(sibling)
            child_clip = self.clip(child_info, clipped)
            if child_clip is not None:
                # Retain geometry already validated even if sibling discovery
                # reaches the budget before its recursive visit can run.
                self.add(child_info, child_clip)
                branches.append((child_clip[2] * child_clip[3], child))
                if len(branches) == 1:
                    now = time.monotonic()
                    search_deadline = now + max(0, self.deadline - now) / 2
                    search_limit = len(self.infos) + max(1, (MAX_NODES - len(self.infos)) // 2)
        if not any(_contains(rect, self.x, self.y) for rect in siblings):
            self.result.update(_gap_rectangles(siblings, self.x, self.y))
        # Only point-containing branches are explored; keep some overlapping
        # wrappers but avoid an unrestricted browser DOM walk.
        for _, child in sorted(branches, key=lambda entry: entry[0])[:MAX_BRANCHES]:
            self.visit(child, clipped, depth + 1)

    def window_root(self, application):
        """Find a matching frame through bounded non-component root wrappers."""
        # Process each root as it arrives. Fetching all siblings up front can
        # exhaust the D-Bus budget before inspecting even the first frame.
        pending = deque([(iter(self.children(application, MAX_WINDOWS)), 0)])
        seen = set()
        windows = []
        search_deadline, search_limit = self.deadline, MAX_NODES
        while pending and self.available():
            if windows and (time.monotonic() >= search_deadline
                            or len(self.infos) >= search_limit):
                break
            siblings, depth = pending[0]
            try:
                window = next(siblings)
            except StopIteration:
                pending.popleft()
                continue
            key = _key(window)
            if key in seen or depth >= MAX_DEPTH:
                continue
            seen.add(key)
            info = self.inspect(window)
            if info is None:
                continue
            if info.bounds is None:
                if not info.managed and len(pending) < MAX_NODES:
                    pending.append((iter(self.children(window, MAX_CHILDREN)), depth + 1))
                continue
            clipped = self.clip(info, self.bounds)
            if clipped is None:
                continue
            area = info.bounds[2] * info.bounds[3]
            if self.bounds:
                overlap = clipped[2] * clipped[3]
                target_area = self.bounds[2] * self.bounds[3]
                score = overlap / (area + target_area - overlap)
            else:
                score = 0
            windows.append((-score, not info.active, area, window))
            if len(windows) == 1:
                # Once there is a usable frame, reserve half of the remaining
                # time and node allowance for finding elements inside it.
                # Root wrappers after that frame must not starve hit testing.
                now = time.monotonic()
                search_deadline = now + max(0, self.deadline - now) / 2
                search_limit = len(self.infos) + max(1, (MAX_NODES - len(self.infos)) // 2)
        return min(windows, key=lambda entry: entry[:3]) if windows else None

    def prepare_root(self, node, info):
        """Request Chromium's on-demand tree using ordinary AT-SPI metadata."""
        if not self.available():
            return
        try:
            # Chromium enables renderer accessibility for this AT-SPI query.
            # Its returned relation targets are deliberately not inspected.
            node.getRelationSet()
        except Exception:
            return
        if info.managed:
            return
        until = min(self.deadline, time.monotonic() + PREPARE_SECONDS)
        while self.available():
            try:
                node.clearCache()
            except Exception:
                pass
            if not self.available():
                return
            try:
                if int(node.childCount) > 0:
                    return
            except Exception:
                return
            # A cold browser renderer may publish its first child later. This
            # short wait stays inside the subprocess's existing probe budget.
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(PREPARE_INTERVAL, remaining))

    def probe_root(self, node):
        info = self.inspect(node)
        if info is None:
            return
        parent = self.bounds or info.bounds
        clipped = self.clip(info, parent)
        if clipped is None:
            return
        # Preserve known geometry even if an accessibility-demand call times
        # out before the renderer can expose any smaller elements.
        self.add(info, clipped)
        self.prepare_root(node, info)
        self.visit(node, parent)

    def run(self, desktop):
        renderers = []
        for application in self.children(desktop, MAX_APPLICATIONS):
            try:
                app_pid = int(application.get_process_id())
                if app_pid == self.pid:
                    root = self.window_root(application)
                    if root is not None:
                        # Prefer the foreground PID/frame before renderer
                        # discovery, so unrelated applications cannot delay it.
                        self.probe_root(root[3])
                        info = self.inspect(root[3])
                        known = self.clip(info, self.bounds or info.bounds)
                        if any(rect != known for rect in self.result):
                            return self.rectangles()
                        # Some toolkits register a frame in the main process
                        # and controls in a related renderer. Keep the frame as
                        # fallback while checking verified descendants only.
                elif app_pid not in self.owners:
                    self.owners[app_pid] = _owned_process(app_pid, self.pid)
                if self.owners.get(app_pid):
                    renderers.append(application)
            except Exception:
                continue
        roots = []
        for application in renderers:
            root = self.window_root(application)
            if root is not None:
                roots.append(root)
        if roots:
            root = min(roots, key=lambda entry: entry[:3])
            self.probe_root(root[3])
        return self.rectangles()

    def rectangles(self):
        return [list(rect) for rect in sorted(self.result, key=lambda rect: (rect[2] * rect[3], rect))[:MAX_RESULTS]]


def rectangles(pid, x, y, bounds=None):
    import pyatspi
    if pid <= 0:
        return []
    if bounds is not None:
        bounds = tuple(map(int, bounds))
        if len(bounds) != 4 or bounds[2] <= 0 or bounds[3] <= 0 or not _contains(bounds, x, y):
            return []
    # Only this short-lived subprocess's libatspi client is affected.
    atspi = getattr(pyatspi, 'Atspi', None)
    if atspi is not None:
        atspi.set_timeout(100, 100)
    return _Probe(pyatspi, pid, x, y, bounds).run(pyatspi.Registry.getDesktop(0))


if __name__ == '__main__':
    try:
        args = list(map(int, sys.argv[1:]))
        if len(args) not in (3, 7):
            raise ValueError('Expected PID, point and optional window bounds')
        print(json.dumps(rectangles(*args[:3], bounds=args[3:] or None)))
    except Exception:
        print('[]')

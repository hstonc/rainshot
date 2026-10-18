"""Small read-only EWMH adapter, plus explicitly requested mouse-wheel events."""
import ctypes as C
import ctypes.util
import os
from contextlib import contextmanager
from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QApplication


class X11:
    def __init__(self):
        self.display = None
        if QApplication.platformName() != 'xcb' or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            return
        self.lib = C.CDLL(ctypes.util.find_library('X11'))
        specs = {
            'XOpenDisplay': (C.c_void_p, [C.c_char_p]), 'XCloseDisplay': (C.c_int, [C.c_void_p]),
            'XDefaultRootWindow': (C.c_ulong, [C.c_void_p]),
            'XInternAtom': (C.c_ulong, [C.c_void_p, C.c_char_p, C.c_int]),
            'XGetWindowProperty': (C.c_int, [C.c_void_p, C.c_ulong, C.c_ulong, C.c_long, C.c_long, C.c_int, C.c_ulong,
                 C.POINTER(C.c_ulong), C.POINTER(C.c_int), C.POINTER(C.c_ulong), C.POINTER(C.c_ulong), C.POINTER(C.c_void_p)]),
            'XGetGeometry': (C.c_int, [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_int), C.POINTER(C.c_int),
                 C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)]),
            'XTranslateCoordinates': (C.c_int, [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                 C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_ulong)]),
            'XFree': (C.c_int, [C.c_void_p]), 'XSync': (C.c_int, [C.c_void_p, C.c_int]),
            'XChangeProperty': (C.c_int, [C.c_void_p, C.c_ulong, C.c_ulong, C.c_ulong,
                                          C.c_int, C.c_int, C.POINTER(C.c_ubyte), C.c_int]),
            'XSetErrorHandler': (C.c_void_p, [C.c_void_p]),
        }
        for name, (restype, args) in specs.items():
            fn = getattr(self.lib, name); fn.restype = restype; fn.argtypes = args
        self.display = self.lib.XOpenDisplay(None)
        if self.display:
            self.root = self.lib.XDefaultRootWindow(self.display)
        self.error_handler = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)(lambda *_: 0)

    @contextmanager
    def safe(self):
        old = self.lib.XSetErrorHandler(C.cast(self.error_handler, C.c_void_p))
        try:
            yield
            self.lib.XSync(self.display, 0)
        finally:
            self.lib.XSetErrorHandler(old)

    def property(self, window, name):
        atom = self.lib.XInternAtom(self.display, name.encode(), 1)
        if not atom:
            return []
        kind, fmt, count, remaining, data = C.c_ulong(), C.c_int(), C.c_ulong(), C.c_ulong(), C.c_void_p()
        code = self.lib.XGetWindowProperty(self.display, window, atom, 0, 4096, 0, 0,
                 C.byref(kind), C.byref(fmt), C.byref(count), C.byref(remaining), C.byref(data))
        try:
            if code or fmt.value != 32 or not data:
                return []
            return list(C.cast(data, C.POINTER(C.c_ulong))[:count.value])
        finally:
            if data:
                self.lib.XFree(data)

    def suppress_taskbar(self, window):
        """Keep a normal, workspace-movable shot out of the taskbar."""
        if not self.display:
            return
        with self.safe():
            state = self.lib.XInternAtom(self.display, b'_NET_WM_STATE', 0)
            skip = self.lib.XInternAtom(self.display, b'_NET_WM_STATE_SKIP_TASKBAR', 0)
            atoms = self.property(window, '_NET_WM_STATE')
            if skip not in atoms:
                atoms.append(skip)
            values = (C.c_ulong * len(atoms))(*atoms)
            self.lib.XChangeProperty(self.display, window, state, 4, 32, 0,
                                     C.cast(values, C.POINTER(C.c_ubyte)), len(atoms))

    def raw_geometry(self, window):
        """Return physical X root coordinates, as also used by AT-SPI."""
        root, child = C.c_ulong(), C.c_ulong()
        x, y, gx, gy = C.c_int(), C.c_int(), C.c_int(), C.c_int()
        w, h, border, depth = (C.c_uint() for _ in range(4))
        if not self.lib.XGetGeometry(self.display, window, C.byref(root), C.byref(x), C.byref(y), C.byref(w), C.byref(h), C.byref(border), C.byref(depth)):
            return QRect()
        self.lib.XTranslateCoordinates(self.display, window, self.root, 0, 0, C.byref(gx), C.byref(gy), C.byref(child))
        return QRect(gx.value, gy.value, w.value, h.value)

    @staticmethod
    def logical_geometry(rect):
        rect = QRect(rect)
        # X coordinates are physical. Qt uses per-screen logical coordinates.
        for screen in QApplication.screens():
            ratio = screen.devicePixelRatio()
            geo = screen.geometry()
            if QRect(geo.topLeft(), geo.size() * ratio).contains(rect.center()):
                rect = QRect(geo.x() + round((rect.x() - geo.x()) / ratio),
                             geo.y() + round((rect.y() - geo.y()) / ratio), round(rect.width() / ratio), round(rect.height() / ratio))
                break
        return rect

    def geometry(self, window):
        return self.logical_geometry(self.raw_geometry(window))

    def windows(self, include_own=False):
        if not self.display:
            return []
        result = []
        with self.safe():
            hidden = self.lib.XInternAtom(self.display, b'_NET_WM_STATE_HIDDEN', 1)
            desktop = self.property(self.root, '_NET_CURRENT_DESKTOP')
            for wid in reversed(self.property(self.root, '_NET_CLIENT_LIST_STACKING')):
                pid = self.property(wid, '_NET_WM_PID')
                if not include_own and pid and pid[0] == os.getpid():
                    continue
                if hidden in self.property(wid, '_NET_WM_STATE'):
                    continue
                desk = self.property(wid, '_NET_WM_DESKTOP')
                if desk and desktop and desk[0] not in (desktop[0], 0xffffffff):
                    continue
                native_rect = self.raw_geometry(wid)
                rect = self.logical_geometry(native_rect)
                if rect.width() > 8 and rect.height() > 8:
                    result.append({'id': wid, 'pid': pid[0] if pid else 0,
                                   'rect': rect, 'native_rect': native_rect})
        return result

    def wheel(self, down=True):
        if not self.display:
            return False
        lib = C.CDLL(ctypes.util.find_library('Xtst'))
        lib.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        for pressed in (1, 0):
            lib.XTestFakeButtonEvent(self.display, 5 if down else 4, pressed, 0)
        self.lib.XSync(self.display, 0)
        return True

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None

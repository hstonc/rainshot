"""Observe X11 pointer clicks without grabbing or consuming another app's input.

Active only while a transient screenshot is shown. No keyboard events, logging,
or persistent input data. Other platforms use normal window deactivation.
"""
import ctypes as C
import os
from PyQt5.QtCore import QObject, QSocketNotifier, QPoint, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication


class Cookie(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", C.c_void_p), ("extension", C.c_int), ("evtype", C.c_int),
                ("cookie", C.c_uint), ("data", C.c_void_p)]


class Event(C.Union):
    _fields_ = [("cookie", Cookie), ("pad", C.c_long * 24)]


class RawHeader(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", C.c_void_p), ("extension", C.c_int), ("evtype", C.c_int),
                ("time", C.c_ulong), ("deviceid", C.c_int), ("sourceid", C.c_int), ("detail", C.c_int)]


class Mask(C.Structure):
    _fields_ = [("deviceid", C.c_int), ("mask_len", C.c_int), ("mask", C.POINTER(C.c_ubyte))]


class OutsideClicks(QObject):
    pressed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.display = None
        self.notifier = None
        if QApplication.platformName() != "xcb" or os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            return
        try:
            self.x = C.CDLL("libX11.so.6")
            self.xi = C.CDLL("libXi.so.6")
        except OSError:
            return
        self.bind(self.x.XOpenDisplay, [C.c_char_p], C.c_void_p)
        self.bind(self.x.XCloseDisplay, [C.c_void_p], C.c_int)
        self.bind(self.x.XDefaultRootWindow, [C.c_void_p], C.c_ulong)
        self.bind(self.x.XConnectionNumber, [C.c_void_p], C.c_int)
        self.bind(self.x.XQueryExtension, [C.c_void_p, C.c_char_p, C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int)], C.c_int)
        self.bind(self.x.XPending, [C.c_void_p], C.c_int)
        self.bind(self.x.XNextEvent, [C.c_void_p, C.POINTER(Event)], C.c_int)
        self.bind(self.x.XGetEventData, [C.c_void_p, C.POINTER(Cookie)], C.c_int)
        self.bind(self.x.XFreeEventData, [C.c_void_p, C.POINTER(Cookie)], None)
        self.bind(self.x.XQueryPointer, [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                                       C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int),
                                       C.POINTER(C.c_int), C.POINTER(C.c_uint)], C.c_int)
        self.bind(self.x.XFlush, [C.c_void_p], C.c_int)
        self.bind(self.xi.XIQueryVersion, [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)], C.c_int)
        self.bind(self.xi.XISelectEvents, [C.c_void_p, C.c_ulong, C.POINTER(Mask), C.c_int], C.c_int)
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            return
        opcode, event, error = C.c_int(), C.c_int(), C.c_int()
        if not self.x.XQueryExtension(self.display, b"XInputExtension", C.byref(opcode), C.byref(event), C.byref(error)):
            self.stop()
            return
        major, minor = C.c_int(2), C.c_int(0)
        if self.xi.XIQueryVersion(self.display, C.byref(major), C.byref(minor)) != 0:
            self.stop()
            return
        self.opcode = opcode.value
        self.root = self.x.XDefaultRootWindow(self.display)
        mask_bytes = (C.c_ubyte * 2)(0, 128)  # XI_RawButtonPress = 15.
        mask = Mask(1, 2, mask_bytes)  # XIAllMasterDevices.
        if self.xi.XISelectEvents(self.display, self.root, C.byref(mask), 1) != 0:
            self.stop()
            return
        self.x.XFlush(self.display)
        self.notifier = QSocketNotifier(self.x.XConnectionNumber(self.display), QSocketNotifier.Read, self)
        self.notifier.activated.connect(self.drain)

    @staticmethod
    def bind(function, args, result):
        function.argtypes = args
        function.restype = result

    @pyqtSlot(int)
    def drain(self, descriptor):
        while self.display and self.x.XPending(self.display):
            event = Event()
            self.x.XNextEvent(self.display, C.byref(event))
            cookie = event.cookie
            if cookie.type != 35 or cookie.extension != self.opcode or cookie.evtype != 15:
                continue
            if not self.x.XGetEventData(self.display, C.byref(cookie)):
                continue
            point = None
            try:
                if cookie.data and C.cast(cookie.data, C.POINTER(RawHeader)).contents.detail in (1, 2, 3):
                    root, child = C.c_ulong(), C.c_ulong()
                    rx, ry, wx, wy = C.c_int(), C.c_int(), C.c_int(), C.c_int()
                    buttons = C.c_uint()
                    if self.x.XQueryPointer(self.display, self.root, C.byref(root), C.byref(child), C.byref(rx), C.byref(ry), C.byref(wx), C.byref(wy), C.byref(buttons)):
                        point = QPoint(rx.value, ry.value)
            finally:
                self.x.XFreeEventData(self.display, C.byref(cookie))
            if point is not None:
                # The receiver may stop this observer. No X calls after emission
                # until the loop has checked self.display again.
                self.pressed.emit(point)

    def stop(self):
        if self.notifier:
            self.notifier.setEnabled(False)
            self.notifier.deleteLater()
            self.notifier = None
        if self.display:
            self.x.XCloseDisplay(self.display)
            self.display = None

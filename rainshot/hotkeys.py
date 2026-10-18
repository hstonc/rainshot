"""X11 passive grabs with conflict detection; Wayland uses desktop shortcuts."""
import ctypes as C
import os
from PyQt5.QtCore import Qt, QObject, QSocketNotifier, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication

ACTIONS = [('region', '區域截圖', '--capture'), ('full', '全螢幕截圖', '--fullscreen'),
           ('scroll', '滾動長截圖', '--scroll'), ('record', '錄製 GIF / WebP', '--record'), ('show', '開啟設定', '--settings'),
           ('close-all', '關閉所有貼圖', '--close-all')]


class KeyEvent(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int), ('display', C.c_void_p),
                ('window', C.c_ulong), ('root', C.c_ulong), ('subwindow', C.c_ulong), ('time', C.c_ulong),
                ('x', C.c_int), ('y', C.c_int), ('x_root', C.c_int), ('y_root', C.c_int),
                ('state', C.c_uint), ('keycode', C.c_uint), ('same_screen', C.c_int)]


class Event(C.Union):
    _fields_ = [('key', KeyEvent), ('pad', C.c_long * 24)]


class ModifierMap(C.Structure):
    _fields_ = [('max_keypermod', C.c_int), ('modifiermap', C.POINTER(C.c_ubyte))]


ERROR_HANDLER = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)


def key_parts(sequence):
    seq = QKeySequence(sequence)
    if seq.isEmpty() or seq.count() != 1:
        raise ValueError('請使用一組按鍵組合，不能使用連續多組快捷鍵。')
    value = seq[0]
    key = value & ~int(Qt.KeyboardModifierMask)
    modifiers = 0
    for qt, x in [(Qt.ShiftModifier, 1), (Qt.ControlModifier, 4), (Qt.AltModifier, 8), (Qt.MetaModifier, 64)]:
        if value & int(qt):
            modifiers |= x
    names = {Qt.Key_Print: 'Print', Qt.Key_Pause: 'Pause', Qt.Key_Space: 'space',
             Qt.Key_Escape: 'Escape', Qt.Key_Return: 'Return', Qt.Key_Tab: 'Tab'}
    if Qt.Key_F1 <= key <= Qt.Key_F35:
        name = f'F{key - Qt.Key_F1 + 1}'
    elif key in names:
        name = names[key]
    elif 33 <= key <= 126:
        name = chr(key).lower()
    else:
        raise ValueError('此按鍵不支援；請選擇字母、數字、功能鍵或 Print。')
    if not modifiers and key != Qt.Key_Print and not Qt.Key_F1 <= key <= Qt.Key_F35:
        raise ValueError('字母等一般按鍵需要搭配 Ctrl、Alt 或 Super，避免影響輸入。')
    if modifiers == 1 and 32 <= key <= 126:
        raise ValueError('請加入 Ctrl、Alt 或 Super，避免影響正常輸入。')
    return name, modifiers


class Hotkeys(QObject):
    activated = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.display = None
        self.notifier = None
        self.bindings = {}
        self.configured = {}
        self.paused = False
        self.pressed = set()
        self.ignored = [0, 2]
        self.supported = QApplication.platformName() == 'xcb' and os.environ.get('XDG_SESSION_TYPE') != 'wayland'
        if not self.supported:
            return
        try:
            self.x = C.CDLL('libX11.so.6')
            def bind(name, args, result=C.c_int):
                fn = getattr(self.x, name)
                fn.argtypes, fn.restype = args, result
            bind('XOpenDisplay', [C.c_char_p], C.c_void_p)
            bind('XCloseDisplay', [C.c_void_p])
            bind('XDefaultRootWindow', [C.c_void_p], C.c_ulong)
            bind('XConnectionNumber', [C.c_void_p])
            bind('XStringToKeysym', [C.c_char_p], C.c_ulong)
            bind('XKeysymToKeycode', [C.c_void_p, C.c_ulong], C.c_ubyte)
            bind('XGrabKey', [C.c_void_p, C.c_int, C.c_uint, C.c_ulong, C.c_int, C.c_int, C.c_int])
            bind('XUngrabKey', [C.c_void_p, C.c_int, C.c_uint, C.c_ulong])
            bind('XSync', [C.c_void_p, C.c_int])
            bind('XPending', [C.c_void_p])
            bind('XNextEvent', [C.c_void_p, C.POINTER(Event)])
            bind('XSetErrorHandler', [C.c_void_p], C.c_void_p)
            bind('XGetModifierMapping', [C.c_void_p], C.POINTER(ModifierMap))
            bind('XFreeModifiermap', [C.POINTER(ModifierMap)])
            bind('XkbSetDetectableAutoRepeat', [C.c_void_p, C.c_int, C.POINTER(C.c_int)])
            self.display = self.x.XOpenDisplay(None)
        except OSError:
            self.supported = False
            return
        self.supported = bool(self.display)
        if not self.display:
            return
        self.root = self.x.XDefaultRootWindow(self.display)
        repeat_supported = C.c_int()
        self.x.XkbSetDetectableAutoRepeat(self.display, True, C.byref(repeat_supported))
        mapping = self.x.XGetModifierMapping(self.display)
        num_code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(b'Num_Lock'))
        if mapping:
            try:
                size = mapping.contents.max_keypermod
                for mod in range(8):
                    if num_code and num_code in [mapping.contents.modifiermap[mod * size + k] for k in range(size)]:
                        self.ignored = sorted(set([0, 2, 1 << mod, 2 | (1 << mod)]))
            finally:
                self.x.XFreeModifiermap(mapping)
        self.ignore_mask = 0
        for mask in self.ignored:
            self.ignore_mask |= mask
        self.notifier = QSocketNotifier(self.x.XConnectionNumber(self.display), QSocketNotifier.Read, self)
        self.notifier.activated.connect(self.drain)
        QApplication.instance().aboutToQuit.connect(self.close)

    def apply(self, configured):
        if not self.supported:
            return '目前桌面請使用下方命令，在系統鍵盤設定中綁定快捷鍵。'
        self.paused = False
        desired = {}
        try:
            for action, sequence in configured.items():
                if not sequence:
                    continue
                name, modifiers = key_parts(sequence)
                code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(name.encode('ascii')))
                if not code:
                    raise ValueError('鍵盤上找不到指定按鍵。')
                key = (code, modifiers)
                if key in desired:
                    raise ValueError('不同功能不能使用相同快捷鍵。')
                desired[key] = action
        except ValueError as exc:
            return str(exc)
        additions = desired.keys() - self.bindings.keys()
        errors = []
        previous = None
        @ERROR_HANDLER
        def handler(display, event):
            if display == self.display:
                errors.append(True)
                return 0
            return ERROR_HANDLER(previous)(display, event) if previous else 0
        self.x.XSync(self.display, False)
        previous = self.x.XSetErrorHandler(C.cast(handler, C.c_void_p))
        try:
            for code, modifiers in additions:
                for ignored in self.ignored:
                    self.x.XGrabKey(self.display, code, modifiers | ignored, self.root, False, 1, 1)
            self.x.XSync(self.display, False)
        finally:
            self.x.XSetErrorHandler(previous)
        if errors:
            self.ungrab(additions)
            return '快捷鍵已被其他程式使用，這次變更未套用。請換一組按鍵或先修改系統綁定。'
        self.ungrab(self.bindings.keys() - desired.keys())
        self.bindings = desired
        self.configured = dict(configured)
        return ''

    def pause(self):
        if self.display and not self.paused:
            self.ungrab(self.bindings.keys())
            self.bindings = {}
            self.pressed.clear()
            self.paused = True

    def resume(self):
        if self.paused and self.display:
            error = self.apply(self.configured)
            if error:
                self.failed.emit(error)

    def ungrab(self, keys):
        for code, modifiers in keys:
            for ignored in self.ignored:
                self.x.XUngrabKey(self.display, code, modifiers | ignored, self.root)
        self.x.XSync(self.display, False)

    def drain(self, descriptor):
        while self.display and self.x.XPending(self.display):
            event = Event()
            self.x.XNextEvent(self.display, C.byref(event))
            if event.key.type == 2:
                if event.key.keycode in self.pressed:
                    continue
                self.pressed.add(event.key.keycode)
                action = self.bindings.get((event.key.keycode, event.key.state & (255 & ~self.ignore_mask)))
                if action:
                    self.activated.emit(action)
            elif event.key.type == 3:
                self.pressed.discard(event.key.keycode)

    def close(self):
        if self.notifier:
            self.notifier.setEnabled(False)
            self.notifier.deleteLater()
            self.notifier = None
        if self.display:
            self.x.XCloseDisplay(self.display)
            self.display = None
        self.bindings = {}
        self.pressed.clear()
        self.supported = False

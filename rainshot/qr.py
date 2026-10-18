"""Local QR decoding via libzbar; images and decoded payloads never leave the host."""
import ctypes as C
import ctypes.util
import json
import sys
import tempfile
from pathlib import Path
from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt5.QtGui import QImage


def decode(image):
    library = ctypes.util.find_library('zbar')
    if not library:
        raise ValueError('找不到二維碼引擎，請安裝 libzbar0。')
    lib = C.CDLL(library)
    signatures = {
        'zbar_image_scanner_create': (C.c_void_p, []),
        'zbar_image_scanner_destroy': (None, [C.c_void_p]),
        'zbar_image_scanner_set_config': (C.c_int, [C.c_void_p, C.c_int, C.c_int, C.c_int]),
        'zbar_image_create': (C.c_void_p, []), 'zbar_image_destroy': (None, [C.c_void_p]),
        'zbar_image_set_format': (None, [C.c_void_p, C.c_ulong]),
        'zbar_image_set_size': (None, [C.c_void_p, C.c_uint, C.c_uint]),
        'zbar_image_set_data': (None, [C.c_void_p, C.c_void_p, C.c_ulong, C.c_void_p]),
        'zbar_scan_image': (C.c_int, [C.c_void_p, C.c_void_p]),
        'zbar_image_first_symbol': (C.c_void_p, [C.c_void_p]),
        'zbar_symbol_next': (C.c_void_p, [C.c_void_p]),
        'zbar_symbol_get_data': (C.c_void_p, [C.c_void_p]),
        'zbar_symbol_get_data_length': (C.c_uint, [C.c_void_p]),
        'zbar_symbol_get_loc_size': (C.c_uint, [C.c_void_p]),
        'zbar_symbol_get_loc_x': (C.c_int, [C.c_void_p, C.c_uint]),
        'zbar_symbol_get_loc_y': (C.c_int, [C.c_void_p, C.c_uint]),
    }
    for name, (restype, args) in signatures.items():
        fn = getattr(lib, name); fn.restype = restype; fn.argtypes = args
    if image.isNull() or image.width() * image.height() > 80_000_000:
        raise ValueError('圖片無效或超過 8,000 萬像素。')
    gray = image.convertToFormat(QImage.Format_Grayscale8)
    bits = gray.constBits(); bits.setsize(gray.sizeInBytes())
    raw = bytes(bits)
    data = b''.join(raw[y * gray.bytesPerLine():y * gray.bytesPerLine() + gray.width()] for y in range(gray.height()))
    buffer = C.create_string_buffer(data)
    scanner, frame = lib.zbar_image_scanner_create(), lib.zbar_image_create()
    try:
        lib.zbar_image_scanner_set_config(scanner, 0, 0, 0)
        lib.zbar_image_scanner_set_config(scanner, 64, 0, 1)  # QR only
        # Preserve UTF-8 bytes. ZBar's heuristic conversion can otherwise mistake
        # valid Chinese UTF-8 for a legacy encoding and return different text.
        lib.zbar_image_scanner_set_config(scanner, 64, 4, 1)  # ZBAR_CFG_BINARY
        lib.zbar_image_set_format(frame, int.from_bytes(b'Y800', 'little'))
        lib.zbar_image_set_size(frame, gray.width(), gray.height())
        lib.zbar_image_set_data(frame, buffer, len(data), None)
        if lib.zbar_scan_image(scanner, frame) < 0:
            raise ValueError('二維碼引擎無法讀取圖片。')
        symbol = lib.zbar_image_first_symbol(frame)
        results = []
        while symbol and len(results) < 100:
            size = lib.zbar_symbol_get_data_length(symbol)
            payload = C.string_at(lib.zbar_symbol_get_data(symbol), size)
            points = [[lib.zbar_symbol_get_loc_x(symbol, i), lib.zbar_symbol_get_loc_y(symbol, i)]
                      for i in range(min(32, lib.zbar_symbol_get_loc_size(symbol))) ]
            try:
                text = payload.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text = payload.decode('shift_jis')
                except UnicodeDecodeError:
                    text = '二進位內容（十六進位）：' + payload.hex()
            results.append({'text': text, 'points': points})
            symbol = lib.zbar_symbol_next(symbol)
        return results
    finally:
        lib.zbar_image_destroy(frame)
        lib.zbar_image_scanner_destroy(scanner)


class QrJob(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.temp = None
        self.done = False
        self.process = QProcess(self)
        self.process.finished.connect(self.complete)
        self.process.errorOccurred.connect(lambda _: self.fail('無法啟動二維碼引擎。'))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(20000)
        self.timer.timeout.connect(lambda: self.fail('二維碼識別逾時，請縮小區域重試。'))

    def start(self):
        try:
            self.temp = tempfile.TemporaryDirectory(prefix='rainshot-qr-')
            path = str(Path(self.temp.name) / 'image.png')
            if not self.image.save(path, 'PNG'):
                raise OSError('無法儲存暫存圖片。')
            self.image = None
            self.timer.start()
            self.process.start(sys.executable, ['-m', 'rainshot.qr', path])
        except OSError as exc:
            self.fail(str(exc))

    def complete(self, code, status):
        if self.done:
            return
        raw = bytes(self.process.readAllStandardOutput())
        self.cleanup()
        try:
            result = json.loads(raw)
            if code or status != QProcess.NormalExit or 'error' in result:
                raise ValueError(result.get('error', '二維碼識別失敗。'))
            self.finished.emit(result['codes'])
        except (ValueError, KeyError) as exc:
            self.failed.emit(str(exc) if not isinstance(exc, json.JSONDecodeError) else '二維碼引擎回應無效。')

    def fail(self, message):
        if not self.done:
            self.cleanup()
            self.failed.emit(message)

    def cleanup(self):
        self.done = True
        self.timer.stop()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill(); self.process.waitForFinished(1000)
        if self.temp:
            self.temp.cleanup(); self.temp = None


if __name__ == '__main__':
    try:
        print(json.dumps({'codes': decode(QImage(sys.argv[1]))}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)

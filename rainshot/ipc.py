"""Single-instance IPC with QObject-owned deadlines and idempotent disconnects."""
import json
import os
import tempfile
from pathlib import Path
from PyQt5.QtCore import QObject, QTimer, QLockFile, QEventLoop, pyqtSignal, pyqtSlot
from PyQt5.QtNetwork import QLocalServer, QLocalSocket


class Peer(QObject):
    message = pyqtSignal(object)
    closed = pyqtSignal(object)

    def __init__(self, socket, parent=None, timeout_ms=2000):
        super().__init__(parent)
        self.socket = socket
        socket.setParent(self)
        socket.setReadBufferSize(65536)
        self.done = False
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.close)
        socket.readyRead.connect(self.read)
        socket.disconnected.connect(self.disconnected)
        self.deadline.start(timeout_ms)

    @pyqtSlot()
    def read(self):
        if self.done:
            return
        if self.socket.canReadLine():
            payload = bytes(self.socket.readLine(65536))
            try:
                message = json.loads(payload)
            except (ValueError, TypeError):
                self.close()
                return
            # Close transport BEFORE dispatch: a callback may enter a nested event
            # loop and destroy the peer. Never access its C++ socket afterward.
            self.close()
            if isinstance(message, dict) and message.get("mode") in ("show", "region", "full", "scroll", "record", "open", "tray", "quit", "close-all", "history"):
                self.message.emit(message)
        elif self.socket.bytesAvailable() >= 65536:
            self.close()

    @pyqtSlot()
    def disconnected(self):
        # A short-lived sender may disconnect with a complete message still buffered.
        self.read()
        if not self.done:
            self.close()

    @pyqtSlot()
    def close(self):
        if self.done:
            return
        self.done = True
        self.deadline.stop()
        self.socket.abort()
        self.closed.emit(self)


class Instance(QObject):
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / ("rainshot-" + str(os.getuid()))
        runtime.mkdir(mode=0o700, exist_ok=True)
        stat = runtime.lstat()
        if runtime.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise RuntimeError("rainshot執行目錄權限異常：" + str(runtime))
        self.path = str(runtime / "socket")
        self.lock = QLockFile(str(runtime / "instance.lock"))
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self.accept)
        self.clients = set()

    def start(self, message):
        if not self.lock.tryLock(0):
            for _ in range(8):
                socket = QLocalSocket()
                socket.connectToServer(self.path)
                if socket.waitForConnected(150):
                    socket.write(json.dumps(message).encode("utf-8") + b"\n")
                    socket.waitForBytesWritten(1000)
                    socket.disconnectFromServer()
                    return False
                loop = QEventLoop()
                QTimer.singleShot(100, loop.quit)
                loop.exec_()
            raise RuntimeError("另一個rainshot實例尚未回應，請先从系統匣退出舊版再重試。")
        QLocalServer.removeServer(self.path)
        if not self.server.listen(self.path):
            self.lock.unlock()
            raise RuntimeError(self.server.errorString())
        return True

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            peer = Peer(socket, self)
            self.clients.add(peer)
            peer.message.connect(self.callback)
            peer.closed.connect(self.drop)
            peer.read()
            if not peer.done and socket.state() == QLocalSocket.UnconnectedState:
                peer.close()

    def drop(self, peer):
        self.clients.discard(peer)
        peer.deleteLater()

    def close(self):
        for peer in list(self.clients):
            peer.close()
        self.server.close()
        self.lock.unlock()

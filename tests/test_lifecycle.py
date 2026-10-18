import sys
from PyQt5.QtCore import QRect, QCoreApplication, QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtNetwork import QLocalSocket
from rainshot.app import Controller, Instance
from rainshot.imaging import ScreenTile


def test_ipc_repeated_disconnect_survives_deadline(app, monkeypatch):
    errors, seen = [], []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    primary = Instance(seen.append)
    assert primary.start({"mode": "tray"})
    for _ in range(20):
        secondary = Instance(lambda _: None)
        assert not secondary.start({"mode": "region", "delay": 2})
        app.processEvents()
    QTest.qWait(2200)
    assert len(seen) == 20
    assert not primary.clients and not errors
    primary.close()


def test_ipc_partial_message_timeout_and_shutdown(app, monkeypatch):
    errors, seen = [], []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    primary = Instance(seen.append)
    assert primary.start({"mode": "tray"})
    client = QLocalSocket()
    client.connectToServer(primary.path)
    assert client.waitForConnected(500)
    client.write(b'{"mode":')
    client.waitForBytesWritten(500)
    QTest.qWait(2200)
    assert not primary.clients and not seen
    client.connectToServer(primary.path)
    assert client.waitForConnected(500)
    app.processEvents()
    primary.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(2100)
    assert not errors


def test_controller_capture_has_only_floating_result(app, image, monkeypatch):
    import rainshot.app as module
    from rainshot.floating import FloatingShot
    monkeypatch.setattr(module, "is_wayland", lambda: False)
    monkeypatch.setattr(module, "grab_tiles", lambda: [ScreenTile(QRect(0, 0, 640, 400), image)])
    controller = Controller(app)
    assert not hasattr(controller, "home")
    controller.dispatch({"mode": "tray"})
    assert not controller.windows
    controller.capture("full", 0)
    QTest.qWait(500)
    assert not controller.busy and len(controller.windows) == 1
    shot = controller.windows[0]
    assert isinstance(shot, FloatingShot) and not shot.pinned
    shot.close()
    app.processEvents()
    assert not any(w.isVisible() for w in controller.windows)
    controller.tray.hide()
    controller.deleteLater()


def test_cancel_error_never_opens_home(app, monkeypatch):
    import rainshot.app as module
    monkeypatch.setattr(module, "is_wayland", lambda: False)
    errors = []
    controller = Controller(app)
    monkeypatch.setattr(controller, "notify", errors.append)
    controller.capture("region", 10)
    controller.cancel_capture()
    assert not controller.busy and not controller.windows
    def fail():
        raise RuntimeError("capture failed")
    monkeypatch.setattr(module, "grab_tiles", fail)
    controller.capture("full", 0)
    QTest.qWait(500)
    assert errors == ["capture failed"]
    assert not controller.busy and not controller.windows
    controller.tray.hide()
    controller.deleteLater()


def test_capture_temporarily_hides_pinned_only(app, image):
    controller = Controller(app)
    pinned = controller.pin(image)
    transient = controller.edit(image)
    controller.capture("region", 10)
    assert transient.closing
    assert pinned.suspended and not pinned.isVisible()
    controller.cancel_capture()
    assert pinned.isVisible() and not pinned.suspended
    pinned.close()
    controller.tray.hide()
    controller.deleteLater()

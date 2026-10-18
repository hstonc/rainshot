import os
from pathlib import Path
import subprocess
import uuid
import pytest
from PyQt5.QtCore import QTimer
from PyQt5.QtDBus import QDBusConnection
from PyQt5.QtTest import QSignalSpy, QTest
from rainshot.capture import PortalCapture


@pytest.fixture
def portal_factory(tmp_path, app, image):
    peers = []
    connections = []
    bus_process = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1", "--address=unix:path=" + str(tmp_path / "bus")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    address = bus_process.stdout.readline().strip()
    if not address:
        bus_process.terminate()
        pytest.fail("Cannot create isolated D-Bus: " + bus_process.stderr.read())
    image_path = tmp_path / "portal result.png"
    assert image.save(str(image_path), "PNG")

    def factory(code=0, mode="", uri=None, timeout_ms=1500):
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, FAKE_CODE=str(code), FAKE_MODE=mode,
                   FAKE_URI=uri if uri is not None else image_path.as_uri(), CLOSE_MARKER=str(tmp_path / "closed"))
        peer = subprocess.Popen(["/usr/bin/python3", str(Path(__file__).with_name("fake_portal.py"))], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        peers.append(peer)
        assert peer.stdout.readline().strip() == "READY"
        connection_name = "test-" + uuid.uuid4().hex
        bus = QDBusConnection.connectToBus(address, connection_name)
        connections.append(connection_name)
        assert bus.isConnected()
        return PortalCapture(bus=bus, timeout_ms=timeout_ms), image_path, tmp_path / "closed"

    yield factory
    for peer in peers:
        peer.terminate()
        peer.wait(timeout=3)
    for connection in connections:
        QDBusConnection.disconnectFromBus(connection)
    bus_process.terminate()
    bus_process.wait(timeout=3)


@pytest.mark.parametrize("mode", ["", "delayed"])
def test_portal_fast_response_and_uri(app, portal_factory, mode):
    portal, path, _ = portal_factory(mode=mode)
    ready = QSignalSpy(portal.ready)
    error = QSignalSpy(portal.failed)
    portal.start()
    assert ready.wait(3000), list(error)
    assert ready[0][0].width() == 640
    assert not portal.timer.isActive()
    assert path.exists(), "Portal-owned file must not be deleted"
    QTest.qWait(20)
    assert len(ready) == 1
    assert len(error) == 0


@pytest.mark.parametrize("code,mode,uri,signal", [(1, "", None, "canceled"), (2, "", None, "failed"),
    (0, "error", None, "failed"), (0, "", "https://example.com/image.png", "failed"),
    (0, "timeout", None, "failed")])
def test_portal_failures(app, portal_factory, code, mode, uri, signal):
    portal, _, closed = portal_factory(code, mode, uri, timeout_ms=100)
    result = QSignalSpy(getattr(portal, signal))
    portal.start()
    assert result.wait(2500)
    assert portal.path is None
    assert not portal.timer.isActive()
    if mode == "error":
        assert "No backend" in result[0][0]
    if mode == "timeout":
        QTest.qWait(50)
        assert closed.exists()


def test_portal_user_cancel(app, portal_factory):
    portal, _, closed = portal_factory(mode="timeout")
    canceled = QSignalSpy(portal.canceled)
    portal.start()
    QTimer.singleShot(100, portal.cancel)
    assert canceled.wait(2000)
    QTest.qWait(50)
    assert closed.exists()
    assert portal.path is None

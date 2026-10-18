import os
import tempfile
from pathlib import Path
import pytest

TEST_DIR = tempfile.TemporaryDirectory(prefix="rainshot-tests-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CACHE_HOME"] = TEST_DIR.name + "/cache"
os.environ["XDG_CONFIG_HOME"] = TEST_DIR.name + "/config"
os.environ["XDG_RUNTIME_DIR"] = TEST_DIR.name + "/runtime"
Path(os.environ["XDG_RUNTIME_DIR"]).mkdir(mode=0o700)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    yield application


@pytest.fixture
def image(app):
    from PyQt5.QtGui import QImage, QColor
    result = QImage(640, 400, QImage.Format_ARGB32)
    result.fill(QColor("white"))
    return result

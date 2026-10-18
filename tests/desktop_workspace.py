"""Opt-in Cinnamon/X11 check of the pinned shot's window-manager hints."""
import subprocess
import re

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

from rainshot.floating import FloatingShot


app = QApplication([])
assert app.platformName() == "xcb"
image = QImage(240, 120, QImage.Format_ARGB32)
image.fill(Qt.white)
settings = QSettings("rainshot-workspace-test", "rainshot-workspace-test")
shot = FloatingShot(image, pinned=True, settings=settings)
try:
    shot.show_active()
    QTest.qWait(250)
    wid = str(int(shot.winId()))
    result = subprocess.check_output(
        ["xprop", "-id", wid,
         "_NET_WM_WINDOW_TYPE", "_NET_WM_DESKTOP", "_NET_WM_STATE"],
        text=True,
    )
    assert "_NET_WM_WINDOW_TYPE_NORMAL" in result, result
    assert "_NET_WM_DESKTOP(CARDINAL) = 4294967295" not in result, result
    assert "_NET_WM_STATE_STICKY" not in result, result
    assert "_NET_WM_STATE_SKIP_TASKBAR" in result, result
    workspace = int(re.search(r"_NET_WM_DESKTOP\(CARDINAL\) = (\d+)", result).group(1))
    count = int(re.search(r"_NET_NUMBER_OF_DESKTOPS\(CARDINAL\) = (\d+)",
                          subprocess.check_output(["xprop", "-root", "_NET_NUMBER_OF_DESKTOPS"], text=True)).group(1))
    if count > 1:
        target = (workspace + 1) % count
        subprocess.run(["wmctrl", "-i", "-r", wid, "-t", str(target)], check=True)
        QTest.qWait(150)
        moved = subprocess.check_output(["xprop", "-id", wid, "_NET_WM_DESKTOP"], text=True)
        assert moved.endswith(f"= {target}\n"), moved
    print(result)
finally:
    shot.close()

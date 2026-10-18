import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from PyQt5.QtCore import Qt, QObject, QTimer, QSettings, QCoreApplication, QProcess
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileDialog
from . import __version__
from .ipc import Instance
from .capture import PortalCapture, SelectionOverlay, grab_tiles, desktop_rect, is_wayland
from .imaging import compose_tiles, load_image
from .floating import FloatingShot
from .hints import saved_notice_manager
from .history import History
from .hotkeys import Hotkeys, ACTIONS
from .settings_window import SettingsWindow
from .config import load_settings, save_directory
from .scroll_capture import ScrollSession
from .recording import RecordingSession


class Controller(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.settings = load_settings()
        self.control_center = None
        self.history = History(self.settings)
        self.hotkeys = Hotkeys(self)
        self.hotkeys.activated.connect(lambda mode: self.dispatch({"mode": mode}))
        self.hotkeys.failed.connect(self.notify)
        self.windows = []
        self.hidden = []
        self.busy = False
        self.overlay = None
        self.portal = None
        self.live_session = None
        self.live_target = None
        self.quitting = False
        self.mode = "region"
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.perform_capture)
        self.quit_timer = QTimer(self)
        self.quit_timer.setInterval(50)
        self.quit_timer.timeout.connect(self.finish_quit)
        icon = QIcon(str(Path(__file__).resolve().parent / "icon.svg"))
        app.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("rainshot · 點擊截圖")
        self.menu = QMenu()
        self.menu.addAction("區域截圖", lambda: self.capture("region", 0))
        self.menu.addAction("錄製 GIF / WebP 區域", lambda: self.capture("record", 0))
        self.menu.addAction("全螢幕截圖", lambda: self.capture("full", 0))
        self.menu.addAction("延時 3 秒截圖", lambda: self.capture("region", 3))
        self.menu.addAction("完成進行中的長截 / 錄製", lambda: self.live_session.finish() if self.live_session else None)
        self.cancel_action = self.menu.addAction("取消等待中的截圖", self.cancel_capture)
        self.cancel_action.setEnabled(False)
        self.menu.addSeparator()
        self.menu.addAction("開啟圖片…", self.import_image)
        self.menu.addAction("設定…", lambda: self.show_settings(0))
        self.menu.addAction("截圖記錄…", lambda: self.show_settings(1))
        self.menu.addAction("快捷鍵設定…", lambda: self.show_settings(2))
        self.menu.addAction("OCR 與常用指令…", lambda: self.show_settings(3))
        self.menu.addAction("翻譯 API…", lambda: self.show_settings(4))
        self.menu.addSeparator()
        self.menu.addAction("關閉所有貼圖", self.close_shots)
        self.menu.addAction("退出rainshot", self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda reason: self.capture("region", 0) if reason == QSystemTrayIcon.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        configured = {action: self.settings.value('hotkeys/' + action, '') for action, _, _ in ACTIONS}
        if self.hotkeys.supported:
            error = self.hotkeys.apply(configured)
            if error:
                self.notify(error)

    def show_settings(self, page=0):
        if self.control_center is None:
            self.control_center = SettingsWindow(self.settings, self.history, self.hotkeys)
            self.control_center.captureRequested.connect(self.capture)
            self.control_center.fileRequested.connect(self.open_file)
            self.control_center.importRequested.connect(self.import_image)
            self.control_center.changed.connect(self.settings_changed)
        self.control_center.select_page(page)
        self.control_center.showNormal()
        self.control_center.raise_()
        self.control_center.activateWindow()

    def settings_changed(self):
        for shot in self.windows:
            if not shot.closing:
                shot.refresh_translation_settings()
                shot.refresh_shortcuts()
                if shot.corner_message.isVisible():
                    if shot.corner_message.tutorial and not self.settings.value('hints_enabled', True, type=bool):
                        shot.dismiss_hint()
                    else:
                        shot.corner_message.reposition()

    def notify(self, message):
        print("rainshot：" + message, file=sys.stderr)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage("rainshot", message, QSystemTrayIcon.Information, 6000)
        elif shutil.which("notify-send"):
            QProcess.startDetached("notify-send", ["--app-name=rainshot", "--", "rainshot", message])

    def copy_command(self):
        import shlex
        command = "rainshot --capture" if shutil.which("rainshot") else shlex.quote(str(Path(__file__).resolve().parents[1] / "run.sh")) + " --capture"
        QApplication.clipboard().setText(command)
        self.notify("已複製命令。請在系統設定 → 鍵盤 → 自訂快捷鍵中貼上並綁定按鍵。")

    def track(self, window):
        self.windows.append(window)
        window.destroyed.connect(lambda: self.windows.remove(window) if window in self.windows else None)
        return window

    def dispatch(self, message):
        mode = message.get("mode", "tray")
        if mode == "tray":
            return
        if mode == "show":
            self.show_settings(0)
            return
        if mode == "history":
            self.show_settings(1)
            return
        if mode == "quit":
            self.quit()
            return
        if mode == "close-all":
            self.close_shots()
            return
        if mode == "open":
            path = message.get("path")
            if isinstance(path, str):
                self.open_file(path)
        else:
            delay = message.get("delay", 0)
            self.capture(mode, delay if isinstance(delay, int) else 0)

    def capture(self, mode="region", delay=0):
        if self.busy:
            return
        if mode == "scroll" and is_wayland():
            self.notify("Wayland 請逐張擷取圖片，再使用貼圖上的「更多 → 拼接圖片」。")
            return
        self.busy = True
        self.mode = mode
        self.cancel_action.setEnabled(True)
        self.hide_windows()
        self.timer.start(max(350, min(15, max(0, delay)) * 1000))

    def hide_windows(self):
        # Save notices outlive their shots; hide them before grabbing pixels.
        saved_notice_manager().clear()
        if self.control_center:
            self.control_center.hide()
        self.hidden = []
        for window in list(self.windows):
            if window.closing or not window.isVisible():
                continue
            if window.pinned:
                window.suspended = True
                window.hide()
                self.hidden.append(window)
            else:
                window.close()

    def restore(self):
        for window in self.hidden:
            if window in self.windows and not window.closing:
                window.show()
                window.suspended = False
        self.hidden.clear()
        self.busy = False
        self.cancel_action.setEnabled(False)

    def perform_capture(self):
        if is_wayland():
            self.portal = PortalCapture(self)
            self.portal.ready.connect(lambda image: self.captured(image, None))
            self.portal.failed.connect(self.capture_failed)
            self.portal.canceled.connect(self.capture_canceled)
            self.portal.start()
            return
        try:
            tiles = grab_tiles()
            if self.mode == "full":
                self.captured(compose_tiles(tiles, desktop_rect(tiles)), None)
            else:
                self.overlay = SelectionOverlay(tiles, self.settings)
                self.overlay.selected.connect(self.captured)
                self.overlay.canceled.connect(self.capture_canceled)
                self.overlay.failed.connect(self.capture_failed)
        except (RuntimeError, ValueError) as exc:
            self.capture_failed(str(exc))

    def clear_capture(self):
        self.overlay = None
        if self.portal:
            self.portal.deleteLater()
            self.portal = None

    def captured(self, image, region):
        self.clear_capture()
        self.restore()
        shot = self.edit(image, region)
        try:
            self.history.record(image)
        except (OSError, ValueError) as exc:
            shot.set_status("截圖已完成，但記錄儲存失敗：" + str(exc))
        if self.control_center:
            self.control_center.refresh_history()
        if self.mode == "scroll":
            shot.request_scroll()
        elif self.mode == "record":
            shot.toggle_record()

    def capture_failed(self, message):
        self.clear_capture()
        self.restore()
        self.notify(message)

    def capture_canceled(self):
        self.clear_capture()
        self.restore()

    def cancel_capture(self):
        if self.live_session:
            self.live_session.cancel()
        elif self.timer.isActive():
            self.timer.stop()
            self.restore()
        elif self.portal:
            self.portal.cancel()
        elif self.overlay:
            self.overlay.cancel()

    def edit(self, image, region=None, pinned=False):
        for window in list(self.windows):
            if not window.pinned and not window.closing:
                window.close()
        shot = self.track(FloatingShot(image, region, pinned=pinned, settings=self.settings))
        shot.saved.connect(self.remember)
        shot.settingsRequested.connect(lambda: self.show_settings(4))
        shot.captureRequested.connect(lambda: self.capture("region", 0))
        shot.scrollRequested.connect(self.append_scroll)
        shot.recordRequested.connect(self.start_recording)
        shot.show_active()
        return shot

    def pin(self, image):
        return self.edit(image, pinned=True)

    def remember(self, path):
        if self.settings.value("history_enabled", True, type=bool):
            paths = self.settings.value("history", [], type=list)
            self.settings.setValue("history", ([path] + [p for p in paths if p != path])[:24])

    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(None, "開啟圖片", "", "圖片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.open_file(path)

    def open_file(self, path):
        if self.control_center:
            self.control_center.hide()
        try:
            self.edit(load_image(path))
        except (ValueError, OSError) as exc:
            self.notify(str(exc))

    def append_scroll(self, shot):
        if self.busy or shot.closing:
            return
        if is_wayland() or shot.region is None:
            shot.set_status('連續捲動截圖目前使用 X11；Wayland 可從「更多 → 拼接圖片」加入已截取的圖片。')
            return
        session = ScrollSession(shot.region, shot.document.render(), self)
        self.begin_session(session, shot)
        session.completed.connect(lambda image: self.end_session(session, image=image))

    def start_recording(self, shot, options):
        if self.busy or shot.closing or shot.region is None:
            return
        session = RecordingSession(shot.region, options, self, output_dir=save_directory(self.settings))
        self.begin_session(session, shot)
        session.completed.connect(lambda path: self.end_session(session, path=path))

    def begin_session(self, session, shot):
        if not shot.pinned:
            shot.toggle_pin()
        self.live_session, self.live_target = session, shot
        self.busy = shot.busy = True
        shot.update_state()
        self.hide_windows()
        self.cancel_action.setEnabled(True)
        session.failed.connect(lambda message: self.end_session(session, error=message))
        session.canceled.connect(lambda: self.end_session(session))
        QTimer.singleShot(350, lambda: session.start() if self.live_session is session and not session.done else None)

    def end_session(self, session, image=None, path=None, error=None):
        if self.live_session is not session:
            return
        shot = self.live_target
        self.live_session = self.live_target = None
        session.deleteLater()
        if path and not error and shot in self.hidden:
            # A finished recording has already been saved. Do not briefly
            # restore and activate the screenshot that the save will close.
            self.hidden.remove(shot)
        self.restore()
        if self.quitting or shot.closing:
            return
        shot.busy = False
        if image is not None:
            shot.clear_ocr()
            shot.document.replace(image)
            shot.region = None
            shot.scale = min(shot.scale, (shot.screen_geometry.height() - 170) / image.height())
            try:
                self.history.record(image)
            except (OSError, ValueError):
                pass
        shot.update_state()
        if path and not error:
            self.remember(path)
            shot.show_saved_status(path)
            return
        shot.show_active()
        shot.dismiss_hint()
        if error:
            shot.set_status(error)
        elif image is not None:
            shot.set_status(f'長截圖完成 · {image.width()} × {image.height()} px')

    def close_shots(self):
        for window in list(self.windows):
            window.close()

    def quit(self):
        self.quitting = True
        self.cancel_capture()
        self.close_shots()
        self.tray.hide()
        self.hotkeys.close()
        if self.control_center:
            self.control_center.close()
        self.finish_quit()

    def finish_quit(self):
        if self.live_session or any(w.stitch_job and w.stitch_job.isRunning() for w in self.windows):
            self.quit_timer.start()
            return
        self.quit_timer.stop()
        self.settings.sync()
        self.app.quit()


def diagnostics():
    from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
    from PyQt5.QtDBus import QDBusConnection
    core = QCoreApplication.instance() or QCoreApplication([])
    print(json.dumps({"rainshot": __version__, "python": sys.version.split()[0],
        "qt": QT_VERSION_STR, "pyqt": PYQT_VERSION_STR,
        "session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
        "display_configured": bool(os.environ.get("DISPLAY")),
        "wayland_display_configured": bool(os.environ.get("WAYLAND_DISPLAY")),
        "session_bus_connected": QDBusConnection.sessionBus().isConnected(),
        "tesseract": bool(shutil.which("tesseract")),
        "capture": "requires a desktop session; --diagnose does not capture"}, ensure_ascii=False, indent=2))


def startup_mode(args):
    for flag, mode in [('quit', 'quit'), ('close_all', 'close-all'), ('fullscreen', 'full'),
                       ('scroll', 'scroll'), ('record', 'record'), ('open', 'open'), ('settings', 'show'),
                       ('history', 'history'), ('capture', 'region')]:
        if getattr(args, flag, False):
            return mode
    return 'tray'


def main(argv=None):
    parser = argparse.ArgumentParser(description="rainshot rainshot — Linux 截图与标注")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--capture", action="store_true", help="开始区域截图（适用于系统快捷键）")
    group.add_argument("--fullscreen", action="store_true", help="截取完整桌面；Wayland 由系统面板选择")
    group.add_argument("--record", action="store_true", help="選擇螢幕區域錄製 GIF / WebP（X11）")
    group.add_argument("--scroll", action="store_true", help="X11 固定选区滚动长截图")
    group.add_argument("--tray", action="store_true", help="僅在系統匣待命，不開啟畫面")
    group.add_argument("--settings", action="store_true", help="開啟設定視窗")
    group.add_argument("--history", action="store_true", help="開啟截圖記錄")
    group.add_argument("--quit", action="store_true", help="退出執行中的rainshot")
    group.add_argument("--close-all", action="store_true", help="關閉全部貼圖，保留背景程式")
    group.add_argument("--open", metavar="IMAGE", help="打开图片进行编辑")
    parser.add_argument("--delay", type=int, choices=range(0, 16), default=0, metavar="0..15")
    parser.add_argument("--diagnose", action="store_true", help="输出环境诊断（不截图）")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if args.diagnose:
        diagnostics()
        return 0
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("QT_QPA_PLATFORM") == "offscreen"):
        print("请在 Ubuntu 或 Linux Mint 的图形桌面会话中运行rainshot。", file=sys.stderr)
        return 1
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    # Select the native platform before QApplication initializes. Never capture Wayland via XWayland.
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    app = QApplication([sys.argv[0]])
    app.setApplicationName("rainshot")
    app.setOrganizationName("rainshot")
    app.setDesktopFileName("io.github.rainshot.rainshot")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    # Queue incoming requests until the primary controller is ready.
    pending = []
    controller = None

    def dispatch(message):
        if controller is None:
            pending.append(message)
        else:
            controller.dispatch(message)
    try:
        instance = Instance(dispatch, app)
        mode = startup_mode(args)
        message = {"mode": mode, "delay": args.delay}
        if args.open:
            message["path"] = str(Path(args.open).resolve())
        if not instance.start(message):
            return 0
        controller = Controller(app)
        if mode == "tray" and not args.tray and not QSystemTrayIcon.isSystemTrayAvailable():
            message["mode"] = "show"
        app.aboutToQuit.connect(instance.close)
        QTimer.singleShot(0, lambda: controller.dispatch(message))
        for item in pending:
            QTimer.singleShot(0, lambda m=item: controller.dispatch(m))
        return app.exec_()
    except RuntimeError as exc:
        print("rainshot啟動失敗：" + str(exc), file=sys.stderr)
        return 1

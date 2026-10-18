"""X11 region recording with FFmpeg, bounded disk spooling and atomic exports."""
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import QObject, QProcess, QTimer, QElapsedTimer, QStandardPaths, pyqtSignal
from PyQt5.QtWidgets import QApplication
from .capture import is_wayland
from .scroll_capture import RegionFrame, SessionControls, SessionKeys


class RecordingSession(QObject):
    completed = pyqtSignal(str)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, region, options, parent=None, output_dir=None):
        super().__init__(parent)
        self.region, self.options = region, dict(options)
        self.output_dir = Path(output_dir) if output_dir else Path(QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)) / 'rainshot'
        self.process = QProcess(self)
        self.process.started.connect(self.started)
        self.process.finished.connect(self.exited)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.errorOccurred.connect(lambda error: self.fail('無法啟動 FFmpeg，請確認已安裝。') if error == QProcess.FailedToStart else None)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(lambda: self.fail('影片處理逾時，已停止。請降低解析度或錄製時間。'))
        self.clock = QElapsedTimer()
        self.stage = 'idle'
        self.done = False
        self.stopping = False
        self.temp = None
        self.keys = SessionKeys(self)
        self.staged_output = None
        self.frame = RegionFrame(region)
        self.controls = SessionControls(region, '準備錄製…')
        self.controls.stop_button.setText('停止錄製')
        self.controls.finishRequested.connect(self.finish)
        self.controls.cancelRequested.connect(self.cancel)

    def start(self):
        if is_wayland() or QApplication.platformName() != 'xcb':
            self.fail('GIF / WebP 區域錄製目前支援 X11 工作階段。Wayland 截圖仍可使用系統授權服務。')
            return
        if not shutil.which('ffmpeg'):
            self.fail('請先安裝錄製引擎：sudo apt install ffmpeg')
            return
        screen = QApplication.screenAt(self.region.center())
        if not screen or not screen.geometry().contains(self.region):
            self.fail('請將錄製區域框選在單一螢幕內。')
            return
        if self.region.width() < 16 or self.region.height() < 16:
            self.fail('錄製區域至少需要 16 × 16 像素。')
            return
        key_error = self.keys.start(self.finish, self.cancel)
        controls_fit = self.controls.reposition()
        if not controls_fit and key_error:
            self.fail('停止快捷鍵 Ctrl+Enter 已被占用；請縮小選區，在旁邊留出停止按鈕的位置。')
            return
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.temp = tempfile.TemporaryDirectory(prefix='rainshot-record-')
            self.video = str(Path(self.temp.name) / 'capture.mkv')
            self.format = 'webp' if self.options.get('format') == 'webp' else 'gif'
            self.fps = max(5, min(20, int(self.options.get('fps', 12))))
            self.duration = max(1, min(120, int(self.options.get('duration', 60))))
            self.width = max(160, min(1920, int(self.options.get('width', 1280))))
            self.path = self.output_dir / ('rainshot_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.' + self.format)
            fd, target = tempfile.mkstemp(prefix='.rainshot-', suffix='.' + self.format, dir=self.output_dir)
            os.fchmod(fd, 0o600); os.close(fd)
            self.staged_output = Path(target)
            ratio = screen.devicePixelRatio()
            geo = screen.geometry()
            x = geo.x() + round((self.region.x() - geo.x()) * ratio)
            y = geo.y() + round((self.region.y() - geo.y()) * ratio)
            w, h = round(self.region.width() * ratio), round(self.region.height() * ratio)
            if w * h > 16_000_000:
                raise ValueError('錄製區域過大，請縮小至 1,600 萬像素內。')
            self.stage = 'record'
            self.frame.show()
            if controls_fit:
                self.controls.show()
            if not key_error:
                self.controls.stop_button.setText('停止 · Ctrl+Enter')
            self.run(['-f', 'x11grab', '-draw_mouse', '1' if self.options.get('cursor', False) else '0',
                      '-framerate', str(self.fps), '-video_size', f'{w}x{h}',
                      '-i', f'{os.environ.get("DISPLAY", ":0")}+{x},{y}', '-t', str(self.duration),
                      '-an', '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-fs', '536870912', self.video])
        except (OSError, ValueError) as exc:
            self.fail(str(exc))

    def run(self, args):
        self.process.start('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-filter_threads', '1', '-filter_complex_threads', '1'] + args)

    def started(self):
        if self.stage == 'record':
            self.clock.start(); self.timer.start()
            self.deadline.start((self.duration + 15) * 1000)
        else:
            self.deadline.start(180000)

    def tick(self):
        if self.stage == 'record':
            elapsed = self.clock.elapsed() / 1000
            self.controls.info.setText(f'● 錄製 {elapsed:.1f} / {self.duration} 秒 · {self.fps} FPS\n輸出 {self.format.upper()}，按停止後自動儲存。')

    def finish(self):
        if self.done or self.stage != 'record' or self.stopping:
            return
        self.stopping = True
        self.controls.stop_button.setEnabled(False)
        self.controls.info.setText('正在結束錄製…')
        self.process.write(b'q\n')
        self.deadline.start(15000)

    def exited(self, code, status):
        if self.done:
            return
        self.deadline.stop()
        if code or status != QProcess.NormalExit:
            self.fail('FFmpeg 未能完成錄製或編碼。請檢查剩餘磁碟空間、螢幕配置，或縮短錄製時間。')
            return
        if self.stage == 'record':
            self.timer.stop(); self.frame.hide()
            self.controls.stop_button.setEnabled(False)
            self.controls.info.setText('正在產生動態圖片…可按取消')
            self.stage = 'palette' if self.format == 'gif' else 'encode'
            scale = f"fps={self.fps},scale=w='min({self.width},iw)':h=-1:flags=lanczos"
            self.filter = scale
            if self.format == 'gif':
                self.palette = str(Path(self.temp.name) / 'palette.png')
                self.run(['-i', self.video, '-vf', scale + ',palettegen=stats_mode=diff', '-frames:v', '1', self.palette])
            else:
                self.run(['-i', self.video, '-vf', scale, '-c:v', 'libwebp_anim', '-quality', '85', '-loop', '0', '-an', str(self.staged_output)])
        elif self.stage == 'palette':
            self.stage = 'encode'
            self.run(['-i', self.video, '-i', self.palette, '-filter_complex', f'[0:v]{self.filter}[v];[v][1:v]paletteuse=dither=sierra2_4a',
                      '-loop', '0', str(self.staged_output)])
        elif self.stage == 'encode':
            try:
                if self.staged_output.stat().st_size < 20:
                    raise ValueError('編碼結果無效。')
                os.replace(self.staged_output, self.path)
                self.staged_output = None
                path = str(self.path)
                self.cleanup()
                self.completed.emit(path)
            except (OSError, ValueError) as exc:
                self.fail(str(exc))

    def fail(self, message):
        if not self.done:
            self.cleanup()
            self.failed.emit(message)

    def cancel(self):
        if not self.done:
            self.cleanup()
            self.canceled.emit()

    def cleanup(self):
        self.done = True
        self.keys.close()
        self.timer.stop(); self.deadline.stop()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill(); self.process.waitForFinished(1000)
        self.controls.hide(); self.frame.hide()
        self.controls.deleteLater(); self.frame.deleteLater()
        if self.staged_output:
            self.staged_output.unlink(missing_ok=True); self.staged_output = None
        if self.temp:
            self.temp.cleanup(); self.temp = None

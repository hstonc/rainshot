"""Optional local OCR, with bounded subprocess lifetime and private temp files."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal, QProcessEnvironment, QRectF
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QApplication
from .ocr_layout import parse_tsv, TextSelection, Word


class OcrJob(QObject):
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str)
    layoutReady = pyqtSignal(object, str)

    def __init__(self, image, parent=None, executable=None, positioned=False, settings=None):
        super().__init__(parent)
        self.image = image
        self.image_size = image.size()
        self.positioned = positioned
        self.executable = executable or shutil.which("tesseract")
        self.rapid_python = str(Path.home() / '.local/share/rainshot/ocr/bin/python')
        engine = 'tesseract'
        if settings is not None:
            self.rapid_python = os.path.expanduser(settings.value('ocr/python', self.rapid_python))
            engine = settings.value('ocr/engine', 'auto')
        self.rapid = engine == 'rapid' or (engine == 'auto' and Path(self.rapid_python).is_file())
        self.temp = None
        self.done = False
        self.stage = "languages"
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60000)
        self.timer.timeout.connect(self._timeout)

    def start(self):
        if self.rapid:
            self.start_rapid()
            return
        if not self.executable:
            self.fail("尚未安裝離線 OCR。請執行：\nsudo apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra tesseract-ocr-eng")
            return
        self.timer.start()
        self.process.start(self.executable, ["--list-langs"])

    def start_rapid(self):
        if not Path(self.rapid_python).is_file():
            self.fail('尚未安裝 RapidOCR；請到「設定 → OCR 與指令」複製安裝指令。')
            return
        try:
            self.temp = tempfile.TemporaryDirectory(prefix='rainshot-ocr-')
            path = str(Path(self.temp.name) / 'input.png')
            if not self.image.save(path, 'PNG'):
                raise OSError('無法建立 OCR 暫存圖片。')
            self.image = None
            self.stage = 'rapid'
            env = QProcessEnvironment.systemEnvironment()
            env.remove('PYTHONPATH')
            env.insert('OMP_NUM_THREADS', '2')
            self.process.setProcessEnvironment(env)
            self.timer.start()
            self.process.start(self.rapid_python, [str(Path(__file__).with_name('rapid_worker.py')), path])
        except OSError as exc:
            self.fail(str(exc))

    def _finished(self, code, status):
        if self.done:
            return
        output = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        error = bytes(self.process.readAllStandardError()).decode("utf-8", "replace")
        if self.stage == 'rapid':
            self.cleanup()
            try:
                data = json.loads(output)
                if code or status != QProcess.NormalExit or 'error' in data:
                    raise ValueError(data.get('error', 'RapidOCR 未能完成識別。'))
                words = []
                bounds = QRectF(0, 0, self.image_size.width(), self.image_size.height())
                for index, (points, text, score) in enumerate(data['lines'][:10000]):
                    xs, ys = [p[0] for p in points], [p[1] for p in points]
                    rect = QRectF(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)).intersected(bounds)
                    if text.strip() and score >= .35 and not rect.isEmpty():
                        words.append(Word(text, rect, (1, 1, 1, index + 1), score * 100))
                self.layoutReady.emit(words, 'RapidOCR / PP-OCRv4')
                self.finished.emit(TextSelection(words).all_text, 'RapidOCR / PP-OCRv4')
            except (ValueError, TypeError, KeyError):
                self.failed.emit('RapidOCR 識別失敗；請檢查安裝套件與 Python 路徑。')
            return
        if code != 0 or status != QProcess.NormalExit:
            self.fail("OCR 执行失败：" + error[-1500:])
            return
        if self.stage == "languages":
            available = set(output.splitlines())
            languages = [lang for lang in ("chi_tra", "chi_sim", "eng") if lang in available]
            if not languages:
                self.fail("没有可用的中文或英文语言包，请安装 tesseract-ocr-chi-sim / tesseract-ocr-eng。")
                return
            self.languages = "+".join(languages)
            try:
                self.temp = tempfile.TemporaryDirectory(prefix="rainshot-ocr-")
            except OSError as exc:
                self.fail("無法建立 OCR 暫存資料夾：" + str(exc))
                return
            path = str(Path(self.temp.name) / "input.png")
            if not self.image.save(path, "PNG"):
                self.fail("无法创建 OCR 临时图片。")
                return
            self.image = None
            self.stage = "recognize"
            arguments = [path, "stdout", "-l", self.languages, "--psm", "3"]
            if self.positioned:
                # Set the engine option directly, so minimal installations do not
                # depend on a separately packaged tessdata/configs/tsv file.
                arguments.extend(["-c", "tessedit_create_tsv=1"])
            self.process.start(self.executable, arguments)
        else:
            self.cleanup()
            if self.positioned:
                if not output.startswith("level\tpage_num\t"):
                    self.failed.emit("OCR 未回傳文字座標，請確認 Tesseract 支援 TSV 輸出。")
                    return
                words = parse_tsv(output, self.image_size.width(), self.image_size.height())
                self.layoutReady.emit(words, self.languages)
                self.finished.emit(TextSelection(words).all_text, self.languages)
            else:
                self.finished.emit(output.strip(), self.languages)

    def _error(self, error):
        if not self.done:
            self.fail("无法启动 OCR：" + self.process.errorString())

    def _timeout(self):
        self.fail("OCR 超时，请缩小识别区域后重试。")

    def fail(self, message):
        self.cleanup()
        self.failed.emit(message)

    def cleanup(self):
        self.done = True
        self.timer.stop()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        if self.temp:
            self.temp.cleanup()
            self.temp = None


class OcrDialog(QDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("rainshot · 离线文字识别")
        self.resize(660, 500)
        layout = QVBoxLayout(self)
        self.status = QLabel("正在本机识别文字…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.text = QTextEdit()
        self.text.setPlaceholderText("识别结果将显示在这里，可直接修改。")
        layout.addWidget(self.text)
        row = QHBoxLayout()
        row.addWidget(QLabel("图片与文字仅在本机处理"))
        row.addStretch()
        self.copy = QPushButton("复制文字")
        self.copy.setObjectName("primary")
        self.copy.setEnabled(False)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        row.addWidget(self.copy)
        layout.addLayout(row)
        self.job = OcrJob(image, self)
        self.job.finished.connect(self.complete)
        self.job.failed.connect(lambda error: self.status.setText(error))
        QTimer.singleShot(0, self.job.start)

    def complete(self, text, languages):
        self.status.setText("识别完成 · " + languages if text else "未识别到文字。请提高图片清晰度或调整截图区域。")
        self.text.setPlainText(text)
        self.copy.setEnabled(bool(text))

    def closeEvent(self, event):
        self.job.cleanup()
        super().closeEvent(event)

    def reject(self):
        self.job.cleanup()
        super().reject()

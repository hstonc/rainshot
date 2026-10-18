from pathlib import Path
import shutil
import shlex
import sys
from PyQt5.QtCore import Qt, pyqtSignal, QSettings
from PyQt5.QtWidgets import (QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QButtonGroup, QStackedWidget, QSpinBox, QListWidget,
    QListWidgetItem, QCheckBox, QPlainTextEdit, QSystemTrayIcon)
from .capture import is_wayland


class Home(QMainWindow):
    captureRequested = pyqtSignal(str, int)
    importRequested = pyqtSignal()
    fileRequested = pyqtSignal(str)
    stitchRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("rainshot rainshot")
        self.resize(1080, 760)
        self.setMinimumSize(880, 660)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(18, 32, 18, 24)
        brand = QLabel("▣  rainshot")
        brand.setStyleSheet("font-size:27px;font-weight:700;color:#216b56")
        nav.addWidget(brand)
        sub = QLabel("RAINSHOT   /   LINUX")
        sub.setObjectName("eyebrow")
        nav.addWidget(sub)
        nav.addSpacing(42)
        self.pages = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        for index, name in enumerate(["开始截图", "最近保存", "使用与设置"]):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _, i=index: self.pages.setCurrentIndex(i))
            self.nav_group.addButton(button)
            nav.addWidget(button)
        nav.addStretch()
        offline = QLabel("本地截图 · 离线处理\nv0.1.0  /  预览版")
        offline.setObjectName("muted")
        offline.setStyleSheet("line-height:1.8")
        nav.addWidget(offline)
        quit_button = QPushButton("退出rainshot")
        quit_button.clicked.connect(self.quitRequested)
        nav.addWidget(quit_button)
        row.addWidget(sidebar)
        row.addWidget(self.pages, 1)
        self.pages.addWidget(self.start_page())
        self.pages.addWidget(self.history_page())
        self.pages.addWidget(self.settings_page())
        self.setCentralWidget(root)
        self.refresh_history()

    def page(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(40, 38, 40, 30)
        layout.setSpacing(20)
        eyebrow = QLabel("YOUR SCREEN, CLEARLY.")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        heading = QLabel(title)
        heading.setObjectName("hero")
        layout.addWidget(heading)
        description = QLabel(subtitle)
        description.setWordWrap(True)
        description.setObjectName("muted")
        layout.addWidget(description)
        return widget, layout

    def start_page(self):
        page, layout = self.page("让想法，清晰可见。", "截取屏幕、标注重点，把需要的内容留在手边。")
        capture = QFrame()
        capture.setObjectName("captureCard")
        card = QVBoxLayout(capture)
        card.setContentsMargins(28, 26, 28, 26)
        card.setSpacing(16)
        title = QLabel("从一次截图开始")
        title.setObjectName("sectionTitle")
        card.addWidget(title)
        card.addWidget(QLabel("框选一个区域，或保存完整桌面。" if not is_wayland() else "通过系统截图面板选择区域、窗口或屏幕。"))
        buttons = QHBoxLayout()
        self.capture_buttons = []
        for label, mode, primary in [("＋  区域截图", "region", True), ("全屏截图", "full", False), ("滚动长截图", "scroll", False)]:
            button = QPushButton(label)
            button.setObjectName("primary" if primary else "secondary")
            button.clicked.connect(lambda _, m=mode: self.captureRequested.emit(m, self.delay.value()))
            if mode == "scroll" and is_wayland():
                button.setEnabled(False)
                button.setToolTip("Wayland 请使用下方「长图拼接」，逐张导入系统截图。")
            buttons.addWidget(button)
            self.capture_buttons.append(button)
        buttons.addStretch()
        card.addLayout(buttons)
        timing = QHBoxLayout()
        timing.addWidget(QLabel("延时"))
        self.delay = QSpinBox()
        self.delay.setRange(0, 15)
        self.delay.setSuffix(" 秒")
        self.delay.setValue(int(self.settings.value("delay", 0)))
        self.delay.valueChanged.connect(lambda value: self.settings.setValue("delay", value))
        timing.addWidget(self.delay)
        timing.addStretch()
        timing.addWidget(QLabel("截图时自动隐藏rainshot窗口"))
        card.addLayout(timing)
        layout.addWidget(capture)
        row = QHBoxLayout()
        row.setSpacing(18)
        for title, text, action, label in [("打开图片", "为已有图片添加标注、遮盖敏感内容，\n也可以识别文字或贴到屏幕。", self.importRequested.emit, "选择图片 →"),
                                           ("长图拼接", "将多张重叠截图按顺序合为一张。\n自动检查接缝，保留完整内容。", self.stitchRequested.emit, "开始拼接 →")]:
            frame = QFrame()
            frame.setObjectName("card")
            content = QVBoxLayout(frame)
            content.setContentsMargins(24, 22, 24, 22)
            content.setSpacing(12)
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            content.addWidget(heading)
            desc = QLabel(text)
            desc.setObjectName("muted")
            desc.setWordWrap(True)
            content.addWidget(desc)
            button = QPushButton(label)
            button.clicked.connect(action)
            content.addWidget(button, alignment=Qt.AlignLeft)
            row.addWidget(frame, 1)
        layout.addLayout(row)
        layout.addStretch()
        session = "Wayland · 系统授权截图" if is_wayland() else "X11 · 原生区域截图"
        self.session_label = QLabel("●  " + session + "    /    OCR " + ("可用" if shutil.which("tesseract") else "需安装语言引擎"))
        self.session_label.setObjectName("muted")
        layout.addWidget(self.session_label)
        return page

    def history_page(self):
        page, layout = self.page("最近保存", "这里仅记录你主动保存的文件；双击可重新编辑。")
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(lambda item: self.fileRequested.emit(item.data(Qt.UserRole)) if item.data(Qt.UserRole) else None)
        layout.addWidget(self.history_list, 1)
        clear = QPushButton("清空记录（保留图片文件）")
        clear.clicked.connect(self.clear_history)
        layout.addWidget(clear, alignment=Qt.AlignLeft)
        return page

    def settings_page(self):
        page, layout = self.page("顺手，也安心。", "把截图快捷键交给桌面系统管理，在 Ubuntu 和 Linux Mint 中都能调用。")
        title = QLabel("设置全局截图快捷键")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        help_label = QLabel("Ubuntu：设置 → 键盘 → 查看及自定义快捷键 → 自定义快捷键\nLinux Mint：系统设置 → 键盘 → 快捷键 → 自定义快捷键\n\n名称填写「rainshot」，命令填写下面的内容，再绑定 Ctrl+Alt+A 或 Print。")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        executable = shutil.which("rainshot")
        command = "rainshot --capture" if executable else shlex.quote(str(Path(__file__).resolve().parents[1] / "run.sh")) + " --capture"
        field = QPlainTextEdit(command)
        field.setReadOnly(True)
        field.setMaximumHeight(65)
        layout.addWidget(field)
        copy = QPushButton("复制快捷键命令")
        from PyQt5.QtWidgets import QApplication
        copy.clicked.connect(lambda: QApplication.clipboard().setText(command))
        layout.addWidget(copy, alignment=Qt.AlignLeft)
        self.history_check = QCheckBox("记录最近主动保存的文件（最多 24 条）")
        self.history_check.setChecked(self.settings.value("history_enabled", True, type=bool))
        self.history_check.toggled.connect(lambda value: self.settings.setValue("history_enabled", value))
        layout.addWidget(self.history_check)
        info = QLabel("离线 OCR 可选依赖：\nsudo apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra tesseract-ocr-eng\n\n贴图：滚轮缩放，拖动移动，Ctrl+滚轮调整透明度，Esc 关闭。\nWayland 的窗口定位和置顶由桌面管理器决定。")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)
        layout.addStretch()
        return page

    def refresh_history(self):
        self.history_list.clear()
        paths = self.settings.value("history", [], type=list)
        for path in paths:
            if not isinstance(path, str):
                continue
            item = QListWidgetItem(Path(path).name + "\n" + path)
            item.setData(Qt.UserRole, path)
            self.history_list.addItem(item)
        if not paths:
            item = QListWidgetItem("还没有保存记录。完成一张截图后，在编辑器中选择「保存」。")
            item.setFlags(Qt.NoItemFlags)
            self.history_list.addItem(item)

    def remember(self, path):
        if self.settings.value("history_enabled", True, type=bool):
            paths = self.settings.value("history", [], type=list)
            self.settings.setValue("history", ([path] + [p for p in paths if p != path])[:24])
            self.refresh_history()

    def clear_history(self):
        self.settings.setValue("history", [])
        self.refresh_history()

    def closeEvent(self, event):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            self.quitRequested.emit()
            event.ignore()

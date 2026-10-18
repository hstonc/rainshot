"""Explicitly opened control center; screenshot operations stay on the shot."""
import shutil
import shlex
from pathlib import Path
from PyQt5.QtCore import Qt, QSize, QProcess, QUrl, pyqtSignal
from PyQt5.QtGui import QIcon, QImageReader, QPixmap, QKeySequence, QDesktopServices
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFormLayout, QListWidget, QListWidgetItem, QStackedWidget,
    QScrollArea, QCheckBox, QComboBox, QLineEdit, QKeySequenceEdit, QSpinBox, QPlainTextEdit, QFileDialog, QMenu)
from . import __version__
from .config import save_directory, default_save_directory, validate_save_directory, copy_original
from .style import STYLE
from .hints import CORNERS
from .shortcuts import ACTIONS as LOCAL_ACTIONS, bindings, hint as local_hint, validate as validate_local_keys
from .hotkeys import ACTIONS
from .translation import PROVIDERS, LANGUAGES, get_config, build_request, TranslationJob
from .desktop_accessibility import DesktopAccessibility

OCR_COMMAND = 'sudo apt install tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim tesseract-ocr-eng'


def launch_command(argument):
    executable = 'rainshot' if shutil.which('rainshot') else shlex.quote(str(Path(__file__).resolve().parents[1] / 'run.sh'))
    return executable + ' ' + argument


class ShortcutEdit(QKeySequenceEdit):
    def __init__(self, sequence, hotkeys):
        super().__init__(sequence)
        self.hotkeys = hotkeys

    def focusInEvent(self, event):
        self.hotkeys.pause()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.hotkeys.resume()


class SettingsWindow(QMainWindow):
    captureRequested = pyqtSignal(str, int)
    fileRequested = pyqtSignal(str)
    importRequested = pyqtSignal()
    changed = pyqtSignal()

    def __init__(self, settings, history, hotkeys):
        super().__init__()
        self.settings, self.history, self.hotkeys = settings, history, hotkeys
        self.test_job = None
        self.provider_drafts = {}
        self.loaded_provider = None
        self.setWindowTitle('rainshot · 設定與記錄')
        self.setStyleSheet(STYLE + 'QLabel#hero {font-size:26px;} QPlainTextEdit {background:#1b2338;border:1px solid #39455e;border-radius:6px;}')
        self.resize(960, 720)
        self.setMinimumSize(800, 560)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(185)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(18, 30, 18, 22)
        brand = QLabel('rainshot')
        brand.setStyleSheet('font-size:30px;font-weight:700;color:#737fea')
        nav.addWidget(brand)
        nav.addWidget(QLabel('RAINSHOT  /  ' + __version__))
        nav.addSpacing(30)
        self.nav_buttons = []
        self.pages = QStackedWidget()
        for index, title in enumerate(['一般設定', '截圖記錄', '快捷鍵', 'OCR 與指令', '翻譯 API', '截圖後按鍵']):
            button = QPushButton(title)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.clicked.connect(lambda _, i=index: self.select_page(i))
            self.nav_buttons.append(button)
            nav.addWidget(button)
        nav.addStretch()
        capture = QPushButton('開始截圖')
        capture.setObjectName('primary')
        capture.clicked.connect(lambda: self.captureRequested.emit('region', 0))
        nav.addWidget(capture)
        import_button = QPushButton('開啟圖片')
        import_button.clicked.connect(self.importRequested)
        nav.addWidget(import_button)
        row.addWidget(sidebar)
        row.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self.general_page()
        self.history_page()
        self.shortcuts_page()
        self.ocr_page()
        self.translation_page()
        self.local_shortcuts_page()
        self.select_page(0)

    def page(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 25)
        layout.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName('hero')
        layout.addWidget(heading)
        description = QLabel(subtitle)
        description.setObjectName('muted')
        description.setWordWrap(True)
        layout.addWidget(description)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.pages.addWidget(scroll)
        return layout

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 1:
            self.refresh_history()
        elif index == 0:
            self.desktop_accessibility.refresh()

    def update_setting(self, name, value):
        self.settings.setValue(name, value)
        self.changed.emit()

    def general_page(self):
        layout = self.page('貼在螢幕上，操作在手邊。', '啟動rainshot後只在系統匣待命。右鍵點擊系統匣圖示，可隨時回到這裡。')
        help_text = QLabel('截圖完成後直接顯示貼圖；點擊其他地方會關閉。\n按 P 釘住後保留，滑鼠離開時收起工具列，移回貼圖即可顯示。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.hints_check = QCheckBox('顯示截圖操作提示（進行下一步後自動消失）')
        self.hints_check.setChecked(self.settings.value('hints_enabled', True, type=bool))
        self.hints_check.toggled.connect(lambda value: self.update_setting('hints_enabled', value))
        layout.addWidget(self.hints_check)
        form = QFormLayout()
        self.corner = QComboBox()
        for label, code in CORNERS:
            self.corner.addItem(label, code)
        self.corner.setCurrentIndex(max(0, self.corner.findData(self.settings.value('hint_corner', 'bottom-right'))))
        self.corner.currentIndexChanged.connect(lambda: self.update_setting('hint_corner', self.corner.currentData()))
        form.addRow('螢幕提示位置', self.corner)
        layout.addLayout(form)
        for key, label in [('smart_selection', '滑鼠指向視窗時自動選區（Tab 切換，Shift 暫停）'),
                           ('element_selection', '嘗試辨識網頁與控件（需應用程式提供 AT-SPI 輔助功能）')]:
            check = QCheckBox(label)
            check.setChecked(self.settings.value(key, True, type=bool))
            check.toggled.connect(lambda value, k=key: self.update_setting(k, value))
            layout.addWidget(check)
        self.desktop_accessibility = DesktopAccessibility(self)
        self.desktop_accessibility_status = QLabel('桌面輔助功能：讀取中…')
        self.desktop_accessibility_status.setWordWrap(True)
        self.desktop_accessibility_status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.desktop_accessibility_status)
        self.enable_accessibility_button = QPushButton('啟用更多軟體的元素識別')
        self.enable_accessibility_button.clicked.connect(self.desktop_accessibility.enable)
        layout.addWidget(self.enable_accessibility_button, alignment=Qt.AlignLeft)
        accessibility_note = QLabel('允許 Firefox、Qt 等軟體提供元素範圍；會啟用桌面的輔助功能，不會啟動朗讀。部分軟體需要重啟。')
        accessibility_note.setWordWrap(True)
        accessibility_note.setTextFormat(Qt.PlainText)
        accessibility_note.setObjectName('muted')
        layout.addWidget(accessibility_note)
        self.desktop_accessibility.changed.connect(self.update_desktop_accessibility)
        layout.addWidget(QLabel('預設儲存資料夾（截圖與 GIF / WebP）'))
        folder_row = QHBoxLayout()
        self.save_folder = QLineEdit(str(save_directory(self.settings)))
        self.save_folder.setPlaceholderText(str(default_save_directory()))
        self.save_folder.setCursorPosition(0)
        folder_row.addWidget(self.save_folder, 1)
        browse = QPushButton('瀏覽…')
        browse.clicked.connect(self.browse_save_folder)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)
        folder_actions = QHBoxLayout()
        apply_folder = QPushButton('套用路徑')
        apply_folder.clicked.connect(self.apply_save_folder)
        folder_actions.addWidget(apply_folder)
        reset_folder = QPushButton('恢復預設')
        reset_folder.clicked.connect(self.reset_save_folder)
        folder_actions.addWidget(reset_folder)
        folder_actions.addStretch()
        layout.addLayout(folder_actions)
        self.ask_save_path_check = QCheckBox('每次保存圖片時選擇路徑（保存按鈕 / 保存快捷鍵）')
        self.ask_save_path_check.setChecked(self.settings.value('ask_save_path', False, type=bool))
        self.ask_save_path_check.toggled.connect(lambda value: self.update_setting('ask_save_path', value))
        layout.addWidget(self.ask_save_path_check)
        self.save_folder_note = QLabel('開啟上述選項後可每次選擇位置與格式；關閉時直接保存到預設資料夾。另存圖片與記錄保存也會從這個資料夾開始。')
        self.save_folder_note.setWordWrap(True)
        self.save_folder_note.setTextFormat(Qt.PlainText)
        layout.addWidget(self.save_folder_note)
        self.history_check = QCheckBox('自動記錄截圖（僅儲存在這台電腦）')
        self.history_check.setChecked(self.settings.value('capture_history_enabled', self.settings.value('history_enabled', True, type=bool), type=bool))
        self.history_check.toggled.connect(lambda value: self.update_setting('capture_history_enabled', value))
        layout.addWidget(self.history_check)
        retention = QHBoxLayout()
        retention.addWidget(QLabel('最多保留'))
        self.limit = QSpinBox()
        self.limit.setRange(1, 100)
        self.limit.setSuffix(' 張')
        self.limit.setValue(self.settings.value('history_limit', 30, type=int))
        self.limit.valueChanged.connect(self.update_retention)
        retention.addWidget(self.limit)
        retention.addWidget(QLabel('，快取容量上限 256 MB'))
        retention.addStretch()
        layout.addLayout(retention)
        note = QLabel('截圖記錄保留截圖原始內容；你另行儲存的圖片不受快取清理影響。\n關閉此設定後停止新增，已有記錄可在「截圖記錄」頁清除。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        layout.addWidget(note)
        layout.addStretch()

    def update_desktop_accessibility(self):
        status = self.desktop_accessibility
        if status.pending:
            text = '正在啟用…' if status.enabling else '讀取中…'
        elif status.error:
            text = status.error
        elif status.enabled is None:
            text = '尚未確認'
        else:
            text = '已啟用' if status.enabled else '未啟用'
            if status.screen_reader_enabled:
                text += ' · 朗讀已啟用，保留目前設定'
        self.desktop_accessibility_status.setText('桌面輔助功能：' + text)
        self.enable_accessibility_button.setEnabled(not status.pending and status.enabled is not True)

    def browse_save_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '選擇預設儲存資料夾', self.save_folder.text())
        if folder:
            self.save_folder.setText(folder)
            self.apply_save_folder()

    def apply_save_folder(self):
        try:
            folder = validate_save_directory(self.save_folder.text().strip())
            self.save_folder.setText(str(folder))
            self.update_setting('save_directory', str(folder))
            self.save_folder_note.setText('已套用：' + str(folder))
        except (OSError, ValueError) as exc:
            self.save_folder_note.setText('無法使用此資料夾：' + str(exc))

    def reset_save_folder(self):
        self.save_folder.setText(str(default_save_directory()))
        self.apply_save_folder()

    def update_retention(self, value):
        self.update_setting('history_limit', value)
        try:
            self.history.prune()
        except OSError:
            pass

    def history_page(self):
        layout = self.page('截圖記錄', '雙擊縮圖即可重新開啟貼圖。此處也列出你主動儲存的圖片。')
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(270)
        self.history_list.setIconSize(QSize(128, 80))
        self.history_list.itemDoubleClicked.connect(lambda item: self.fileRequested.emit(item.data(Qt.UserRole)) if item.data(Qt.UserRole) else None)
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.history_menu)
        layout.addWidget(self.history_list, 1)
        row = QHBoxLayout()
        refresh = QPushButton('重新整理')
        refresh.clicked.connect(self.refresh_history)
        row.addWidget(refresh)
        clear = QPushButton('清除記錄與截圖快取')
        clear.clicked.connect(self.clear_history)
        row.addWidget(clear)
        row.addStretch()
        layout.addLayout(row)
        self.history_note = QLabel('清除只會刪除rainshot快取，保留你另行儲存的圖片。')
        self.history_note.setWordWrap(True)
        self.history_note.setTextFormat(Qt.PlainText)
        layout.addWidget(self.history_note)

    def history_menu(self, position):
        item = self.history_list.itemAt(position)
        if item is None or not item.data(Qt.UserRole):
            return
        path = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction('開啟（系統預設程式）', lambda: self.open_history(path))
        menu.addAction('保存副本…', lambda: self.save_history(path))
        menu.exec_(self.history_list.viewport().mapToGlobal(position))
        menu.deleteLater()

    def open_history(self, path):
        if not Path(path).is_file():
            self.history_note.setText('原始檔案已不存在，請重新整理記錄。')
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).absolute()))):
            self.history_note.setText('無法開啟，請檢查系統的預設圖片檢視器。')

    def save_history(self, path):
        source = Path(path)
        if not source.is_file():
            self.history_note.setText('原始檔案已不存在，請重新整理記錄。')
            return
        extension = source.suffix.lower()
        destination, _ = QFileDialog.getSaveFileName(self, '保存原始檔案',
            str(save_directory(self.settings) / source.name), f'{extension[1:].upper()} 原檔 (*{extension})')
        if not destination:
            return
        if not Path(destination).suffix:
            destination += extension
        try:
            copy_original(source, destination)
            self.history_note.setText('已保存：' + destination)
        except (OSError, ValueError) as exc:
            self.history_note.setText('保存失敗：' + str(exc))

    def refresh_history(self):
        self.history_list.clear()
        for path in self.history.entries():
            file = Path(path)
            item = QListWidgetItem(file.name + '\n' + ('截圖快取' if file.parent == self.history.directory else '已儲存的圖片'))
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(128, 80, Qt.KeepAspectRatio))
                item.setIcon(QIcon(QPixmap.fromImage(reader.read())))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.history_list.addItem(item)
        if self.history_list.count() == 0:
            item = QListWidgetItem('尚無截圖記錄。可在一般設定啟用自動記錄。')
            item.setFlags(Qt.NoItemFlags)
            self.history_list.addItem(item)

    def clear_history(self):
        try:
            self.history.clear()
            self.history_note.setText('已清除。你另行儲存的圖片仍然保留。')
        except OSError:
            self.history_note.setText('部分快取無法清除，請檢查檔案權限。')
        self.refresh_history()

    def command_row(self, layout, command):
        row = QHBoxLayout()
        field = QLineEdit(command)
        field.setReadOnly(True)
        field.setCursorPosition(0)
        row.addWidget(field, 1)
        copy = QPushButton('複製')
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(command), copy.setText('已複製')))
        row.addWidget(copy)
        layout.addLayout(row)
        return field, copy

    def shortcuts_page(self):
        native = self.hotkeys.supported
        layout = self.page('快捷鍵', '點擊按鍵欄錄入組合，按「套用」後生效。留空可解除。' if native else '這個桌面由系統管理全域快捷鍵。複製命令後，到系統键盤設定中綁定。')
        local_button = QPushButton('設定截圖後快捷鍵…')
        local_button.clicked.connect(lambda:self.select_page(5))
        layout.addWidget(local_button)
        form = QFormLayout()
        self.key_fields = {}
        for action, label, argument in ACTIONS:
            field = ShortcutEdit(QKeySequence(self.settings.value('hotkeys/' + action, '')), self.hotkeys)
            field.setEnabled(native)
            self.key_fields[action] = field
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(field, 1)
            clear = QPushButton('清除')
            clear.setEnabled(native)
            clear.clicked.connect(field.clear)
            row.addWidget(clear)
            form.addRow(label, container)
        layout.addLayout(form)
        apply_button = QPushButton('套用快捷鍵')
        apply_button.setEnabled(native)
        apply_button.clicked.connect(self.apply_hotkeys)
        layout.addWidget(apply_button, alignment=Qt.AlignLeft)
        self.hotkey_status = QLabel('建議區域截圖使用 Ctrl+Alt+A。Print 可能已被系統占用。')
        self.hotkey_status.setWordWrap(True)
        layout.addWidget(self.hotkey_status)
        for _, label, argument in ACTIONS:
            layout.addWidget(QLabel(label))
            self.command_row(layout, launch_command(argument))
        system_button = QPushButton('開啟系統鍵盤設定')
        system_button.clicked.connect(self.open_keyboard)
        layout.addWidget(system_button, alignment=Qt.AlignLeft)
        layout.addStretch()

    def local_shortcuts_page(self):
        layout = self.page('截圖後快捷鍵', '翻譯預設 T、複製色碼 C、文字標註 X。套用前會檢查按鍵衝突。')
        self.local_shortcuts_form(layout)
        layout.addStretch()

    def local_shortcuts_form(self, layout):
        description = QLabel('截圖後快捷鍵：只在貼圖取得焦點時生效。可清空解除；文字編輯期間不觸發這些功能鍵。')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.local_key_fields = {}
        form = QFormLayout()
        values = bindings(self.settings)
        for action,default,label in LOCAL_ACTIONS:
            field = ShortcutEdit(QKeySequence(values[action]), self.hotkeys)
            self.local_key_fields[action] = field
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0,0,0,0)
            row.addWidget(field,1)
            clear = QPushButton('清除')
            clear.clicked.connect(field.clear)
            row.addWidget(clear)
            form.addRow(label, container)
        layout.addLayout(form)
        actions = QHBoxLayout()
        apply = QPushButton('套用截圖後快捷鍵')
        apply.clicked.connect(self.apply_local_shortcuts)
        actions.addWidget(apply)
        reset = QPushButton('恢復預設按鍵')
        reset.clicked.connect(self.reset_local_shortcuts)
        actions.addWidget(reset)
        actions.addStretch()
        layout.insertLayout(3, actions)
        self.local_key_status = QLabel('方向鍵與 Enter 保留給取色和文字編輯。')
        self.local_key_status.setWordWrap(True)
        self.local_key_status.setTextFormat(Qt.PlainText)
        layout.insertWidget(4, self.local_key_status)


    def apply_local_shortcuts(self):
        try:
            values = validate_local_keys({action:field.keySequence().toString(QKeySequence.PortableText)
                for action,field in self.local_key_fields.items()})
            global_keys = {QKeySequence(self.settings.value('hotkeys/'+action,'')).toString(QKeySequence.PortableText)
                for action,_,_ in ACTIONS}
            if any(key and key in global_keys for key in values.values()):
                raise ValueError('按鍵與全域截圖快捷鍵重複，請使用不同組合。')
        except ValueError as exc:
            self.local_key_status.setText(str(exc))
            return
        for action,key in values.items():
            self.settings.setValue('local_shortcuts/'+action,key)
        self.changed.emit()
        self.local_key_status.setText('已套用到目前開啟的貼圖，提示也已更新。')

    def reset_local_shortcuts(self):
        for action,key,label in LOCAL_ACTIONS:
            self.local_key_fields[action].setKeySequence(QKeySequence(key))
        self.apply_local_shortcuts()

    def apply_hotkeys(self):
        values = {action: field.keySequence().toString(QKeySequence.PortableText) for action, field in self.key_fields.items()}
        local_keys = set(bindings(self.settings).values())
        if any(key and key in local_keys for key in values.values()):
            self.hotkey_status.setText('按鍵與截圖後快捷鍵重複，請先修改其中一項。')
            return
        error = self.hotkeys.apply(values)
        self.hotkey_status.setText(error or '快捷鍵已套用。rainshot執行時可在其他程式中使用。')
        if not error:
            for action, value in values.items():
                self.settings.setValue('hotkeys/' + action, value)

    def open_keyboard(self):
        for program, args in [('cinnamon-settings', ['keyboard']), ('gnome-control-center', ['keyboard'])]:
            if shutil.which(program):
                ok, _ = QProcess.startDetached(program, args)
                if ok:
                    return
        self.hotkey_status.setText('無法自動開啟，請從桌面的系統設定進入鍵盤 → 自訂快捷鍵。')

    def ocr_page(self):
        layout = self.page('OCR 與常用指令', 'OCR 在本機處理。安裝引擎與語言包後，按貼圖上的文字識別圖示即可拖曳選取文字。')
        form = QFormLayout()
        self.ocr_engine = QComboBox()
        for label, value in [('自動（已安裝時優先 RapidOCR）', 'auto'), ('RapidOCR / PP-OCRv4', 'rapid'), ('Tesseract', 'tesseract')]:
            self.ocr_engine.addItem(label, value)
        self.ocr_engine.setCurrentIndex(max(0, self.ocr_engine.findData(self.settings.value('ocr/engine', 'auto'))))
        self.ocr_engine.currentIndexChanged.connect(lambda: self.update_setting('ocr/engine', self.ocr_engine.currentData()))
        form.addRow('本機 OCR 引擎', self.ocr_engine)
        self.ocr_python = QLineEdit(self.settings.value('ocr/python', str(Path.home() / '.local/share/rainshot/ocr/bin/python')))
        self.ocr_python.editingFinished.connect(lambda: self.update_setting('ocr/python', self.ocr_python.text().strip()))
        form.addRow('RapidOCR Python 路徑', self.ocr_python)
        layout.addLayout(form)
        rapid_note = QLabel('Snow Shot 使用本機 Paddle / RapidOCR 模型。這裡可選 PP-OCRv4；安裝包含模型，不需 API 金鑰，識別時不連網。')
        rapid_note.setWordWrap(True)
        layout.addWidget(rapid_note)
        self.command_row(layout, 'sudo apt install python3-venv')
        self.command_row(layout, 'python3 -m venv "$HOME/.local/share/rainshot/ocr"')
        self.command_row(layout, '\"$HOME/.local/share/rainshot/ocr/bin/pip\" install rapidocr-onnxruntime==1.4.4 \"numpy<2\" \"opencv-python<4.11\" onnxruntime==1.20.1')
        status = QLabel('Tesseract：'  + ('已找到引擎' if shutil.which('tesseract') else '尚未安裝'))
        layout.addWidget(status)
        layout.addWidget(QLabel('Ubuntu / Linux Mint：安裝繁體、簡體中文與英文 OCR'))
        self.ocr_command, self.ocr_copy = self.command_row(layout, OCR_COMMAND)
        layout.addWidget(QLabel('檢查已安裝的 OCR 語言包'))
        self.command_row(layout, 'tesseract --list-langs')
        layout.addWidget(QLabel('環境診斷（不觸發截圖）'))
        self.command_row(layout, launch_command('--diagnose'))
        layout.addWidget(QLabel('只啟動背景程式'))
        self.command_row(layout, launch_command('--tray'))
        layout.addWidget(QLabel('二維碼、捲動拼接與 GIF / WebP 錄製所需套件'))
        self.command_row(layout, 'sudo apt install libzbar0 python3-opencv python3-pyatspi ffmpeg')
        note = QLabel('複製後貼到終端執行；rainshot不會自動執行安裝指令。\n識別完成後，直接在原圖片上選字；Ctrl+A 全選、Ctrl+C 複製。')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def translation_page(self):
        layout = self.page('翻譯 API', '按貼圖上的翻譯圖示，翻譯選取的 OCR 文字；未選取時翻譯全部。')
        form = QFormLayout()
        self.translation_form = form
        self.provider = QComboBox()
        for code, (label, _, _) in PROVIDERS.items():
            self.provider.addItem(label, code)
        form.addRow('服務', self.provider)
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText('完整請求地址，例如 https://…/chat/completions')
        form.addRow('API 地址', self.endpoint)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText('本次執行期間使用，不寫入設定檔')
        form.addRow('API 金鑰 / 應用密鑰', self.api_key)
        self.appid = QLineEdit()
        form.addRow('應用 ID（有道）', self.appid)
        self.model = QLineEdit()
        form.addRow('模型名稱（AI）', self.model)
        self.source_language, self.target_language = QComboBox(), QComboBox()
        self.source_language.addItem('自動識別', 'auto')
        for label, code in LANGUAGES:
            self.source_language.addItem(label, code)
            self.target_language.addItem(label, code)
        self.source_language.setCurrentIndex(max(0, self.source_language.findData(self.settings.value('translation/source', 'auto'))))
        self.target_language.setCurrentIndex(max(0, self.target_language.findData(self.settings.value('translation/target', 'zh-TW'))))
        form.addRow('來源語言', self.source_language)
        form.addRow('目標語言', self.target_language)
        layout.addLayout(form)
        note = QLabel('使用線上服務時，按下翻譯才會傳送文字到上面的 API 地址，圖片不會傳送。\n金鑰可在此輸入，或使用環境變數；各服務分別保留設定。')
        note.setWordWrap(True)
        note.setObjectName('muted')
        layout.addWidget(note)
        self.key_env = QLabel()
        self.key_env.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.key_env.setWordWrap(True)
        layout.addWidget(self.key_env)
        row = QHBoxLayout()
        apply_button = QPushButton('儲存翻譯設定')
        apply_button.setObjectName('primary')
        apply_button.clicked.connect(self.save_translation)
        row.addWidget(apply_button)
        test_button = QPushButton('測試翻譯 Hello')
        test_button.clicked.connect(self.test_translation)
        row.addWidget(test_button)
        row.addStretch()
        layout.addLayout(row)
        self.translation_status = QLabel('Google、Microsoft 不需金鑰，使用與 Snow Shot 相同的網頁翻譯入口；可用性受網路與服務端限制。其他 API 仍需自行開通。')
        self.translation_status.setWordWrap(True)
        self.translation_status.setTextFormat(Qt.PlainText)
        self.translation_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.translation_status)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.settings.value('translation/provider', 'google'))))
        self.provider.currentIndexChanged.connect(self.load_provider)
        self.load_provider()
        layout.addStretch()

    def draft(self):
        return {'provider': self.provider.currentData(), 'endpoint': self.endpoint.text().strip(),
                'key': self.api_key.text().strip(), 'appid': self.appid.text().strip(), 'model': self.model.text().strip(),
                'source': self.source_language.currentData(), 'target': self.target_language.currentData()}

    def load_provider(self):
        if self.loaded_provider:
            self.provider_drafts[self.loaded_provider] = self.draft()
        code = self.provider.currentData()
        config = self.provider_drafts.get(code, get_config(self.settings, code))
        self.loaded_provider = code
        self.endpoint.setText(config['endpoint'])
        self.api_key.setText(config['key'])
        self.appid.setText(config['appid'])
        self.model.setText(config['model'])
        self.appid.setEnabled(code == 'youdao')
        self.model.setEnabled((code in ('deepseek', 'compatible') or code.startswith('qwen-')))
        self.api_key.setEnabled(code not in ('google', 'microsoft'))
        for field, visible in [(self.api_key, code not in ('google', 'microsoft')), (self.appid, code == 'youdao'), (self.model, (code in ('deepseek', 'compatible') or code.startswith('qwen-')))]:
            field.setVisible(visible)
            self.translation_form.labelForField(field).setVisible(visible)
        self.endpoint.setReadOnly(code in ('google', 'microsoft'))
        self.key_env.setText('此服務不需要 API 金鑰。' if code in ('google', 'microsoft') else '此服務的金鑰環境變數：RAINSHOT_KEY_' + code.upper().replace('-', '_'))
        if code.startswith('qwen-'):
            self.key_env.setText(self.key_env.text() + '\n通義千問需要阿里雲百煉金鑰。預設北京地址；國際區可改為 https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions，或填入控制台提供的完整地址。金鑰地域須與地址一致。')

    def save_translation(self):
        config = self.draft()
        # Saving incomplete credentials is allowed; validation occurs before requests.
        self.provider_drafts[self.provider.currentData()] = config
        secrets = getattr(self.settings, 'translation_keys', {})
        for code, draft in self.provider_drafts.items():
            for key in ('endpoint', 'appid', 'model'):
                self.settings.setValue('translation/' + code + '/' + key, draft[key])
            secrets[code] = draft['key']
        self.settings.translation_keys = secrets
        for key in ('provider', 'source', 'target'):
            self.settings.setValue('translation/' + key, config[key])
        self.translation_status.setText('設定已儲存，金鑰僅保留至本次退出rainshot。')
        self.changed.emit()

    def test_translation(self):
        if self.test_job:
            self.test_job.cancel()
            self.test_job.deleteLater()
        self.test_job = TranslationJob(self.draft(), 'Hello', self)
        self.test_job.finished.connect(lambda text: self.translation_status.setText('測試成功：' + text))
        self.test_job.failed.connect(self.translation_status.setText)
        self.translation_status.setText('正在翻譯測試文字 Hello…')
        self.test_job.start()

    def closeEvent(self, event):
        if self.test_job:
            self.test_job.cancel()
        self.hide()
        event.ignore()

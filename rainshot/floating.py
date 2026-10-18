"""One frameless screenshot surface, attached controls and in-place OCR selection."""
import math
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QSize, QEvent, QTimer, pyqtSignal, QStandardPaths, QSettings, QUrl
from PyQt5.QtGui import QPainter, QColor, QPen, QRegion, QKeySequence, QCursor, QDesktopServices, QFont, QFontMetricsF
from PyQt5.QtWidgets import (QApplication, QWidget, QFrame, QToolButton, QLabel,
    QHBoxLayout, QVBoxLayout, QButtonGroup, QShortcut, QFileDialog, QPlainTextEdit, QComboBox, QSpinBox, QCheckBox, QSlider)
from .imaging import Document, Mark, draw_mark, save_image, load_image
from .capture import is_wayland
from .config import save_directory
from .magnifier import PixelMagnifier
from .image_search import SEARCH_PROVIDERS, ImageDragButton, prepare_image, web_url
from .ocr import OcrJob
from .qr import QrJob
from .shortcuts import ACTIONS as LOCAL_ACTIONS, bindings, hint as local_hint, validate as validate_keys
from .translated_overlay import PositionedTranslationJob, selected_lines, overlay as translated_overlay
from .ocr_layout import TextSelection
from .stitch import StitchJob
from .outside_click import OutsideClicks
from .icons import icon, PATHS
from .hints import CornerMessage, create_save_notice
from .translation import TranslationJob, get_config, PROVIDERS, LANGUAGES
from .x11 import X11


ANNOTATIONS = [("rect", "□", "矩形 R"), ("ellipse", "○", "橢圓 E"),
               ("arrow", "↗", "箭頭 A"), ("line", "╱", "直線 L"), ("pen", "✎", "畫筆 B"),
               ("highlight", "▰", "螢光 H"), ("text", "T", "文字 X"), ("number", "①", "序號 N"),
               ("mosaic", "▦", "馬賽克 M"), ("redact", "■", "遮蓋 D")]

FLOAT_STYLE = """
QFrame#shotTools { background: #1b2338; border: 1px solid #4c597d; border-radius: 10px; }
QFrame#shotTools QLabel { color: #d6dcf2; font-family: 'Noto Sans CJK TC'; font-size: 11px; border: none; }
QToolButton { background: transparent; color: #edf0ff; border: 1px solid transparent; border-radius: 5px;
 padding: 3px; font-family: 'Noto Sans CJK TC'; font-size: 13px; }
QToolButton:hover { background: #374367; border-color: #6e7cab; }
QToolButton:checked { color: #111629; background: #a6b0ff; }
QToolButton:disabled { color: #73809c; }
QComboBox, QSpinBox { background:#26314c; color:#edf0ff; border:1px solid #516089; border-radius:5px; padding:5px; }
QComboBox QAbstractItemView { background:#202a42; color:#edf0ff; selection-background-color:#5667a2; }
QSlider::groove:horizontal {height:5px;background:#4c597d;border-radius:2px;}
QSlider::handle:horizontal {background:#a6b0ff;width:14px;margin:-5px 0;border-radius:7px;}
QCheckBox { color:#edf0ff; background:transparent; }
QPlainTextEdit { color: #edf0ff; background: #151c2e; border: 2px solid #8797ff; border-radius: 3px; }
"""


class InlineText(QPlainTextEdit):
    commitRequested = pyqtSignal()
    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preedit = ''
        self.setFrameShape(QFrame.NoFrame)
        self.document().setDocumentMargin(0)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)

    def inputMethodEvent(self, event):
        self.preedit = event.preeditString()
        super().inputMethodEvent(event)
        self.parent().shot.resize_text_input()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelRequested.emit()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.preedit:
                QApplication.inputMethod().commit()
            elif event.modifiers() & Qt.ShiftModifier:
                self.insertPlainText('\n')
            else:
                self.commitRequested.emit()
        else:
            super().keyPressEvent(event)


class ShotSurface(QWidget):
    def __init__(self, shot):
        super().__init__(shot)
        self.shot = shot
        self.points = []
        self.preview = None
        self.drag = None
        self.selecting = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def source_point(self, pos):
        image = self.shot.document.base
        return QPointF(max(0, min(image.width() - 1, pos.x() * image.width() / self.width())),
                       max(0, min(image.height() - 1, pos.y() * image.height() / self.height())))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self.shot.render_image())
        painter.save()
        image = self.shot.document.base
        painter.scale(self.width() / image.width(), self.height() / image.height())
        if self.preview:
            if self.preview.kind in ("crop", "mosaic"):
                painter.setPen(QPen(QColor("#92a4ff"), 2, Qt.DashLine))
                painter.setBrush(QColor(27, 167, 143, 30))
                painter.drawRect(QRectF(QPointF(*self.preview.points[0]), QPointF(*self.preview.points[-1])).normalized())
            else:
                draw_mark(painter, self.preview)
        if self.shot.mode == "ocr" and self.shot.selection:
            for rect in self.shot.selection.highlight_rects:
                painter.fillRect(rect, QColor(45, 131, 245, 85))
        painter.restore()
        painter.setPen(QPen(QColor("#a59aff" if self.shot.pinned else "#819aff"), 2))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def wheelEvent(self, event):
        if self.shot.text_input.isVisible():
            return
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.shot.setWindowOpacity(min(1, max(.2, self.shot.windowOpacity() + (.05 if delta > 0 else -.05))))
            return
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            self.shot.zoom_at(event.globalPos(), math.pow(1.0015, max(-480, min(480, delta))))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.setFocus()
        shot = self.shot
        shot.dismiss_hint()
        if shot.busy:
            return
        p = self.source_point(event.pos())
        if shot.color_mode:
            shot.sample_color(event.pos())
            shot.copy_color()
            return
        if shot.mode == "ocr" and shot.selection:
            shot.selection.begin(p)
            self.selecting = shot.selection.anchor is not None
            self.update()
        elif shot.mode == "pan":
            self.drag = event.globalPos() - shot.pos()
            # Hand the drag to the compositor/window manager. Cinnamon can
            # carry a managed window to another workspace while it is moving.
            # Keep the old geometry drag for platforms that decline the request.
            if shot.begin_window_move():
                self.drag = None
        elif shot.mode == "text":
            shot.begin_text(p)
        elif shot.mode == "number":
            number = 1 + sum(mark.kind == "number" for mark in shot.document.marks)
            shot.add_mark(Mark("number", ((p.x(), p.y()),), shot.color, shot.stroke, str(number)))
        else:
            self.points = [(p.x(), p.y())]

    def leaveEvent(self, event):
        self.shot.magnifier.hide()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.shot.sample_color(event.pos())
        p = self.source_point(event.pos())
        if self.shot.mode == "ocr" and self.shot.selection:
            self.setCursor(Qt.IBeamCursor if self.shot.selection.hit(p) is not None or self.selecting else Qt.ArrowCursor)
            if self.selecting and event.buttons() & Qt.LeftButton:
                self.shot.selection.extend(p)
                self.update()
        elif self.drag is not None and event.buttons() & Qt.LeftButton:
            self.shot.move(event.globalPos() - self.drag)
        elif self.points and event.buttons() & Qt.LeftButton:
            if self.shot.mode in ("pen", "highlight") and len(self.points) < 15000:
                self.points.append((p.x(), p.y()))
            else:
                self.points = [self.points[0], (p.x(), p.y())]
            self.preview = Mark(self.shot.mode, tuple(self.points), self.shot.color, self.shot.stroke)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        p = self.source_point(event.pos())
        if self.selecting:
            self.shot.selection.extend(p)
        elif self.points:
            self.points.append((p.x(), p.y()))
            mark = Mark(self.shot.mode, tuple(self.points), self.shot.color, self.shot.stroke)
            if mark.kind == "crop":
                self.shot.crop(QRectF(QPointF(*mark.points[0]), p).normalized())
            else:
                self.shot.add_mark(mark)
        self.selecting = False
        self.points = []
        self.preview = None
        self.drag = None
        self.update()

    def keyPressEvent(self, event):
        if self.shot.color_mode:
            step = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                    Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(event.key())
            if step:
                self.shot.nudge_color(*step)
                event.accept()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.shot.copy_color()
                event.accept()
                return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.shot.color_mode:
            return
        if event.button() != Qt.LeftButton:
            return
        if self.shot.mode == "ocr" and self.shot.selection:
            self.shot.selection.select_word(self.source_point(event.pos()))
            self.selecting = False
            self.update()
        elif self.shot.mode == "pan":
            self.shot.zoom_at(event.globalPos(), 1 / self.shot.scale)


class FloatingShot(QWidget):
    closed = pyqtSignal(object)
    saved = pyqtSignal(str)
    captureRequested = pyqtSignal()
    scrollRequested = pyqtSignal(object)
    settingsRequested = pyqtSignal()
    recordRequested = pyqtSignal(object, object)

    def __init__(self, image, region=None, pinned=False, parent=None, settings=None):
        # Qt.Tool is treated as a utility window by X11 window managers and may
        # be sticky across workspaces. A normal, frameless managed window can
        # participate in Cinnamon's native move-to-workspace gesture.
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("rainshot · 貼圖")
        self.setFocusPolicy(Qt.StrongFocus)
        self.settings = settings if settings is not None else QSettings("rainshot", "rainshot")
        self.qr_job = None
        self.result_path = None
        self.pixel_hex = None
        self.pixel_point = None
        self.color_mode = False
        self.translation_job = None
        self.translation_image = None
        self.original_selection = None
        self.translation_lines = []
        self.translate_after_ocr = False
        self.toolbar_visible = True
        self.document = Document(image)
        self.region = QRect(region) if region is not None else None
        self.pinned = pinned
        self.closing = False
        self.suspended = False
        self.hold = 0
        self.busy = False
        self.ocr_job = None
        self.stitch_job = None
        self.outside_clicks = None
        self.selection = None
        self.mode = "pan"
        self.color = "#ef5b5b"
        self.stroke = 4
        self.above = False
        self.last_save = None
        self.scale = 1.0
        self.setStyleSheet(FLOAT_STYLE)
        self.surface = ShotSurface(self)
        self.magnifier = PixelMagnifier(self)
        self.text_input = InlineText(self.surface)
        self.text_input.hide()
        self.text_input.setPlaceholderText("Enter 確認 · Shift+Enter 換行")
        self.text_input.commitRequested.connect(self.commit_text)
        self.text_input.cancelRequested.connect(self.cancel_text)
        self.text_input.textChanged.connect(self.resize_text_input)
        self.buttons = {}
        self.tools = QFrame(self)
        self.tools.setObjectName("shotTools")
        layout = QVBoxLayout(self.tools)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(5)
        main = QHBoxLayout()
        main.setSpacing(4)
        self.dimensions = QLabel()
        self.dimensions.setMinimumWidth(82)
        main.addWidget(self.dimensions)
        main.addStretch()
        self.make_button(main, "annotate", "✎", "標註工具", self.toggle_annotations, True)
        self.make_button(main, "ocr", "OCR", "原位文字識別 O", self.run_ocr, True, 43)
        self.make_button(main, "translate", "", "翻譯選取文字或全部文字 T", self.run_translation, True)
        self.make_button(main, "pin", "釘住", "P：釘住後，點擊其他地方仍保留", self.toggle_pin, True, 49)
        self.make_button(main, "scroll", "↧", "S：捲動原頁面，連續拼接長截圖", self.request_scroll)
        self.make_button(main, "qr", "", "Q：識別二維碼", self.run_qr, True)
        self.make_button(main, "color", "", "I：像素放大取色；方向鍵微調，點擊或 Enter 複製", self.toggle_color, True)
        self.make_button(main, "image_search", "", "以圖搜圖：開啟搜尋網頁並拖曳截圖", self.toggle_image_search, True)
        self.make_button(main, "record", "", "G：錄製原區域 GIF / 動態 WebP", self.toggle_record, True)
        self.make_button(main, "save", "↓", "儲存圖片 Ctrl+S（存入設定的資料夾）", self.quick_save)
        self.make_button(main, "copy", "▣", "複製圖片 Ctrl+C（有選取文字時複製文字）", self.copy)
        self.make_button(main, "undo", "↶", "復原 Ctrl+Z", self.undo)
        self.make_button(main, "redo", "↷", "重做 Ctrl+Shift+Z", self.redo)
        self.make_button(main, "more", "···", "更多操作", self.toggle_more)
        self.make_button(main, "close", "×", "關閉 Esc", self.close)
        layout.addLayout(main)
        self.annotation_row = QWidget()
        annotation_layout = QVBoxLayout(self.annotation_row)
        annotation_layout.setContentsMargins(0, 0, 0, 0)
        annotation_layout.setSpacing(3)
        palette = QHBoxLayout()
        palette.setSpacing(3)
        self.group = QButtonGroup(self)
        for key, symbol, tip in ANNOTATIONS:
            button = self.make_button(palette, key, symbol, tip, lambda _, k=key: self.set_mode(k), True)
            self.group.addButton(button)
        annotation_layout.addLayout(palette)
        options = QHBoxLayout()
        options.addWidget(QLabel("顏色"))
        self.color_buttons = {}
        self.color_group = QButtonGroup(self)
        for color in ["#ef5b5b", "#f1ac35", "#1ba78f", "#4e80df", "#161d25", "#ffffff"]:
            button = QToolButton()
            button.setFixedSize(25, 25)
            button.setCheckable(True)
            button.setToolTip(color)
            button.setAccessibleName('標註顏色 '+color)
            button.setStyleSheet(f"QToolButton {{background:{color};color:{'white' if color in ('#161d25','#4e80df') else '#111629'};border:1px solid #68738e;border-radius:12px;}} "
                'QToolButton:checked {border:3px solid #bac4ff;}')
            button.setChecked(color == self.color)
            button.setText('✓' if color == self.color else '')
            button.clicked.connect(lambda _, c=color: self.choose_annotation_color(c))
            self.color_buttons[color] = button
            self.color_group.addButton(button)
            options.addWidget(button)
        options.addSpacing(10)
        self.width_label = QLabel('大小 4')
        options.addWidget(self.width_label)
        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(1, 32)
        self.width_slider.setValue(self.stroke)
        self.width_slider.setMinimumWidth(90)
        self.width_slider.setMaximumWidth(160)
        self.width_slider.setAccessibleName('標註大小')
        self.width_slider.valueChanged.connect(self.set_annotation_width)
        options.addWidget(self.width_slider, 1)
        self.annotation_undo = self.make_button(options, 'annotation_undo', '↶', '上一步', self.undo)
        self.annotation_undo.setIcon(icon('undo'))
        self.annotation_redo = self.make_button(options, 'annotation_redo', '↷', '下一步', self.redo)
        self.annotation_redo.setIcon(icon('redo'))
        annotation_layout.addLayout(options)
        layout.addWidget(self.annotation_row)
        self.annotation_row.hide()
        self.ocr_row = QWidget()
        ocr_layout = QHBoxLayout(self.ocr_row)
        ocr_layout.setContentsMargins(0, 0, 0, 0)
        self.make_button(ocr_layout, "select_all", "全選文字", "Ctrl+A", self.select_all, width=80)
        self.make_button(ocr_layout, "copy_text", "複製文字", "複製選取文字，未選取則複製全部", self.copy_text, width=80)
        self.make_button(ocr_layout, "retry_ocr", "重新識別", "重新讀取目前圖片中的文字", self.retry_ocr, width=80)
        self.make_button(ocr_layout, "exit_ocr", "返回圖片", "保留識別結果，返回移動貼圖", lambda: self.set_mode("pan"), width=80)
        ocr_layout.addStretch()
        layout.addWidget(self.ocr_row)
        self.ocr_row.hide()
        self.more_row = QWidget()
        more = QHBoxLayout(self.more_row)
        more.setContentsMargins(0, 0, 0, 0)
        for key, label, tip, callback in [
            ("save_as", "另存…", "選擇路徑與圖片格式", self.save_as),
            ("stitch_file", "拼接圖片…", "加入下一張有重疊的圖片", self.append_file),
            ("new", "重新截圖", "開始新的區域截圖", self.captureRequested.emit),
            ("text_apply", "套用文字", "套用目前輸入的文字", self.commit_text)]:
            self.make_button(more, key, label, tip, callback, width=92)
        more.addStretch()
        layout.addWidget(self.more_row)
        self.more_row.hide()
        self.translation_row = QWidget()
        translation_layout = QVBoxLayout(self.translation_row)
        translation_layout.setContentsMargins(0, 2, 0, 0)
        options = QHBoxLayout()
        self.translation_provider = QComboBox()
        self.translation_provider.setMaximumWidth(165)
        self.translation_provider.setToolTip("翻譯服務")
        for key, (label, _, _) in PROVIDERS.items():
            self.translation_provider.addItem(label, key)
        self.translation_target = QComboBox()
        self.translation_target.setMaximumWidth(110)
        self.translation_target.setToolTip("目標語言")
        for label, code in LANGUAGES:
            self.translation_target.addItem(label, code)
        self.refresh_translation_settings()
        options.addWidget(self.translation_provider)
        options.addWidget(self.translation_target)
        self.make_button(options, "translate_again", "翻譯", "翻譯目前選取的文字；再次按下可取消", self.translate_selection, width=48)
        self.make_button(options, "copy_translation", "複製", "複製譯文", self.copy_translation, width=48)
        self.make_button(options, "translation_settings", "設定", "設定翻譯 API", self.open_translation_settings, width=48)
        translation_layout.addLayout(options)
        self.translation_output = QPlainTextEdit(self.tools)
        self.translation_output.setReadOnly(True)
        self.translation_output.setPlaceholderText("翻譯結果會出現在這裡，可選取或複製。")
        self.translation_output.hide()
        self.make_button(options, "original_text", "原文", "恢復原始 OCR 文字與圖片", self.restore_original_translation, width=48)
        layout.addWidget(self.translation_row)
        self.translation_row.hide()
        self.result_row = QWidget()
        result_layout = QVBoxLayout(self.result_row)
        result_layout.setContentsMargins(0, 2, 0, 0)
        result_actions = QHBoxLayout()
        self.result_title = QLabel()
        result_actions.addWidget(self.result_title, 1)
        self.result_links = QComboBox()
        self.result_links.setMaximumWidth(250)
        self.result_links.setToolTip('選擇要開啟的二維碼網址')
        result_actions.addWidget(self.result_links)
        self.result_links.hide()
        self.open_result_button = self.make_button(result_actions, 'open_result', '開啟', '以系統檢視器開啟錄製檔案', self.open_result, width=52)
        self.open_result_button.hide()
        self.make_button(result_actions, 'copy_result', '複製', '複製此處的識別結果或檔案路徑', self.copy_result, width=52)
        self.make_button(result_actions, 'hide_result', '收起', '收起結果', self.hide_result, width=52)
        result_layout.addLayout(result_actions)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFixedHeight(100)
        result_layout.addWidget(self.result_text)
        layout.addWidget(self.result_row)
        self.result_row.hide()
        self.search_row = QWidget()
        search_layout = QVBoxLayout(self.search_row)
        search_layout.setContentsMargins(0, 2, 0, 0)
        search_actions = QHBoxLayout()
        self.search_provider = QComboBox()
        for label, url in SEARCH_PROVIDERS:
            self.search_provider.addItem(label, url)
        search_actions.addWidget(self.search_provider)
        self.make_button(search_actions, 'open_search', '開啟搜尋', '以預設瀏覽器開啟搜尋頁面', self.open_image_search, width=80)
        self.search_drag = ImageDragButton(self)
        search_actions.addWidget(self.search_drag)
        self.make_button(search_actions, 'search_path', '複製路徑', '網頁選擇上傳檔案時，可貼上此路徑', self.copy_search_path, width=80)
        search_actions.addStretch()
        search_layout.addLayout(search_actions)
        search_note = QLabel('開啟網頁的相機按鈕，將上方「拖曳截圖到網頁」拖入上傳區。圖片會送往所選搜尋服務。')
        search_note.setWordWrap(True)
        search_layout.addWidget(search_note)
        layout.addWidget(self.search_row)
        self.search_row.hide()
        self.record_row = QWidget()
        record_layout = QVBoxLayout(self.record_row)
        record_layout.setContentsMargins(0, 2, 0, 0)
        record_options = QHBoxLayout()
        self.record_format = QComboBox()
        self.record_format.addItem('GIF', 'gif')
        self.record_format.addItem('動態 WebP', 'webp')
        self.record_format.setCurrentIndex(max(0, self.record_format.findData(self.settings.value('record/format', 'gif'))))
        record_options.addWidget(self.record_format)
        self.record_fps = QSpinBox(); self.record_fps.setRange(5, 20); self.record_fps.setSuffix(' FPS')
        self.record_fps.setValue(self.settings.value('record/fps', 12, type=int))
        record_options.addWidget(self.record_fps)
        self.record_duration = QSpinBox(); self.record_duration.setRange(1, 120); self.record_duration.setSuffix(' 秒上限')
        self.record_duration.setValue(self.settings.value('record/duration', 60, type=int))
        record_options.addWidget(self.record_duration)
        self.record_width = QSpinBox(); self.record_width.setRange(160, 1920); self.record_width.setSingleStep(160); self.record_width.setSuffix(' px 寬上限')
        self.record_width.setValue(self.settings.value('record/width', 1280, type=int))
        record_options.addWidget(self.record_width)
        self.make_button(record_options, 'start_record', '開始', '隱藏貼圖並錄製原螢幕區域', self.start_record, width=54)
        record_layout.addLayout(record_options)
        self.record_cursor = QCheckBox('錄下滑鼠游標')
        self.record_cursor.setChecked(self.settings.value('record/cursor', False, type=bool))
        record_layout.addWidget(self.record_cursor)
        record_layout.addWidget(QLabel("Ctrl+Enter 停止 · Ctrl+Esc 取消 · 完成後存入圖片/rainshot"))
        layout.addWidget(self.record_row)
        self.record_row.hide()
        self.corner_message = CornerMessage(self, self.settings)
        self.status = self.corner_message.label
        self.toolbar_timer = QTimer(self)
        self.toolbar_timer.setSingleShot(True)
        self.toolbar_timer.setInterval(280)
        self.toolbar_timer.timeout.connect(self.check_toolbar)
        self.popup_rect = QRect()
        self.popup_timer = QTimer(self)
        self.popup_timer.setSingleShot(True)
        self.popup_timer.setInterval(180)
        self.deactivate_timer = QTimer(self)
        self.deactivate_timer.setSingleShot(True)
        self.deactivate_timer.setInterval(90)
        self.deactivate_timer.timeout.connect(self.dismiss_if_inactive)
        QApplication.instance().installEventFilter(self)
        self.buttons["pin"].setChecked(pinned)
        screen = QApplication.screenAt(region.center()) if region is not None else QApplication.screenAt(QCursor.pos())
        self.screen_geometry = (screen or QApplication.primaryScreen()).availableGeometry()
        width, height = image.width(), image.height()
        initial = region.width() / width if region is not None else 1.0
        self.scale = min(initial, (self.screen_geometry.width() - 16) / width,
                         (self.screen_geometry.height() - 110) / height)
        self.scale = max(.001, self.scale)
        origin = region.topLeft() if region is not None else self.screen_geometry.center() - QPoint(round(width * self.scale / 2), round(height * self.scale / 2))
        if origin.y() + round(height * self.scale) + 100 > self.screen_geometry.bottom():
            self.above = origin.y() - 100 >= self.screen_geometry.top()
        self.layout_at(origin)
        self.update_state()
        self.shortcuts = []
        self.refresh_shortcuts()

    def refresh_shortcuts(self):
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts = []
        try:
            keys = validate_keys(bindings(self.settings))
        except ValueError:
            keys = bindings()
        callbacks = {'pin': self.toggle_pin, 'scroll': self.request_scroll, 'ocr': self.run_ocr,
            'translate': self.run_translation, 'qr': self.run_qr, 'color': self.toggle_color,
            'record': self.toggle_record, 'copy_color': self.copy_color, 'copy': self.copy,
            'save': self.quick_save, 'select_all': self.select_all, 'undo': self.undo,
            'redo': self.redo, 'redo_alt': self.redo, 'close': self.escape}
        for action, default, label in LOCAL_ACTIONS:
            callback = callbacks.get(action, lambda a=action: self.set_mode(a))
            key = keys[action]
            if key:
                shortcut = QShortcut(QKeySequence(key), self, activated=callback)
                shortcut.setEnabled(not self.text_input.isVisible())
                self.shortcuts.append(shortcut)
            button = self.buttons.get(action)
            if button:
                tip = label + (' · '+key if key else ' · 未設定快捷鍵')
                if action == 'save':
                    tip += ' · ' + ('選擇保存位置' if self.settings.value('ask_save_path', False, type=bool) else '存入預設資料夾')
                button.setToolTip(tip)
                button.setAccessibleName(tip)
        for button,action in [(self.annotation_undo,'undo'),(self.annotation_redo,'redo')]:
            button.setToolTip(('上一步' if action=='undo' else '下一步')+' · '+(keys[action] or '未綁定'))
        self.magnifier.copy_hint = keys['copy_color']
        if hasattr(self,'corner_message') and self.corner_message.tutorial:
            self.corner_message.present(self.default_hint()+'\n'+local_hint(self.settings), tutorial=True, duration=0)

    def render_image(self):
        return self.translation_image if self.translation_image is not None else self.document.render()

    def make_button(self, layout, key, text, tip, callback, checkable=False, width=31):
        button = QToolButton()
        button.setText(text)
        if key in PATHS:
            button.setIcon(icon(key))
            button.setIconSize(QSize(20, 20))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            width = 31
        button.setAccessibleName(tip)
        button.setToolTip(tip)
        button.setFixedSize(width, 29)
        button.setCheckable(checkable)
        button.clicked.connect(self.dismiss_hint)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.buttons[key] = button
        return button

    def default_hint(self):
        return "已釘住 · 拖曳移動，滾輪縮放" if self.pinned else "點擊其他地方即關閉 · 按「釘住」保留 · 滾輪縮放"

    def image_origin(self):
        return self.surface.mapToGlobal(QPoint())

    def layout_at(self, origin):
        image = self.document.base
        iw, ih = max(1, round(image.width() * self.scale)), max(1, round(image.height() * self.scale))
        tw = max(480, self.tools.layout().minimumSize().width())
        self.tools.setFixedWidth(tw)
        self.tools.layout().activate()
        th = self.tools.layout().totalHeightForWidth(tw)
        if th < 0:
            th = self.tools.sizeHint().height()
        # Qt can report a small height-for-width for layouts containing fixed
        # height text editors. Always include the visible children's size hints.
        th = max(45, th, self.tools.layout().minimumSize().height(), self.tools.sizeHint().height())
        self.tools.setFixedHeight(th)
        screen = QApplication.screenAt(origin + QPoint(iw // 2, ih // 2))
        if screen:
            self.screen_geometry = screen.availableGeometry()
        available = self.screen_geometry
        tx = max(available.left(), min(available.right() - tw + 1, origin.x() + (iw - tw) // 2))
        ty = origin.y() - th - 7 if self.above else origin.y() + ih + 7
        if ty + th - 1 > available.bottom() and origin.y() - th - 7 >= available.top():
            ty = origin.y() - th - 7
        ty = max(available.top(), min(available.bottom() - th + 1, ty))
        image_rect = QRect(origin, QSize(iw, ih))
        tools_rect = QRect(QPoint(tx, ty), QSize(tw, th))
        geometry = image_rect.united(tools_rect) if self.toolbar_visible else image_rect
        # A single native geometry change preserves the original pin zoom behavior.
        self.setGeometry(geometry)
        self.surface.setGeometry(image_rect.translated(-geometry.topLeft()))
        self.tools.setGeometry(tools_rect.translated(-geometry.topLeft()))
        mask = QRegion(self.surface.geometry())
        if self.toolbar_visible:
            mask = mask.united(QRegion(self.tools.geometry()))
        self.setMask(mask)
        self.dimensions.setText(f"{image.width()} × {image.height()}")
        self.surface.update()
        if hasattr(self,"text_input"):
            self.resize_text_input()

    def reflow(self):
        self.layout_at(self.image_origin())

    def zoom_at(self, cursor, factor):
        origin = self.image_origin()
        rx = (cursor.x() - origin.x()) / self.surface.width()
        ry = (cursor.y() - origin.y()) / self.surface.height()
        image = self.document.base
        longest = max(image.width(), image.height())
        self.scale = min(8, 16384 / longest, max(24 / longest, self.scale * factor))
        nw, nh = max(1, round(image.width() * self.scale)), max(1, round(image.height() * self.scale))
        self.layout_at(QPoint(round(cursor.x() - rx * nw), round(cursor.y() - ry * nh)))

    def show_active(self):
        self.suspended = False
        if QApplication.platformName() == 'xcb':
            x11 = X11()
            try:
                x11.suppress_taskbar(int(self.winId()))
            finally:
                x11.close()
        self.show()
        self.raise_()
        self.activateWindow()
        self.surface.setFocus()
        self.update_click_observer()
        self.corner_message.present(self.default_hint() + "\n" + local_hint(self.settings), tutorial=True, duration=0)
        if self.pinned:
            self.toolbar_timer.start()

    def begin_window_move(self):
        handle = self.windowHandle()
        return bool(handle and handle.startSystemMove())

    def update_click_observer(self):
        if self.outside_clicks:
            self.outside_clicks.stop()
            self.outside_clicks.deleteLater()
            self.outside_clicks = None
        if not self.pinned and not self.closing and not self.suspended:
            self.outside_clicks = OutsideClicks(self)
            self.outside_clicks.pressed.connect(self.outside_pressed)

    def outside_pressed(self, position):
        if not (self.closing or self.suspended or self.pinned or self.hold) and self.isVisible():
            if not self.contains_interaction(position):
                self.close()

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget) and watched.windowType() == Qt.Popup and event.type() in (QEvent.Show, QEvent.Hide):
            owner = watched
            while owner is not None and owner is not self:
                owner = owner.parent()
            if owner is self:
                self.popup_rect = QRect(watched.mapToGlobal(QPoint()), watched.size())
                self.popup_timer.start()
        if not self.closing and self.pinned and isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
            if event.type() == QEvent.Enter and watched is not self.corner_message and not self.corner_message.isAncestorOf(watched):
                self.toolbar_timer.stop()
                self.set_toolbar_visible(True)
            elif event.type() == QEvent.Leave:
                self.toolbar_timer.start()
        if self.closing or self.suspended or self.pinned or self.hold or not self.isVisible():
            return False
        if event.type() == QEvent.MouseButtonPress and hasattr(event, "globalPos"):
            local = self.mapFromGlobal(event.globalPos())
            if not self.contains_interaction(event.globalPos()):
                self.close()
        return False

    def event(self, event):
        if event.type() == QEvent.WindowDeactivate and hasattr(self, "deactivate_timer") and not self.closing:
            self.deactivate_timer.start()
        return super().event(event)

    def dismiss_if_inactive(self):
        # Some backends still report our nonactivating Tool as active. A
        # transition to an owned window is not a click into another app.
        owner = QApplication.activeWindow()
        while owner is not None:
            if owner is self:
                return
            owner = owner.parent()
        if self.popup_timer.isActive():
            self.deactivate_timer.start()
            return
        if not (self.pinned or self.closing or self.suspended or self.hold) and self.isVisible() and not self.isActiveWindow() and not self.owned_popup():
            self.close()

    def toggle_pin(self, checked=None):
        self.dismiss_hint()
        self.pinned = not self.pinned
        self.buttons["pin"].setChecked(self.pinned)
        self.update_click_observer()
        self.dismiss_hint()
        if self.pinned:
            self.toolbar_timer.start()
        else:
            self.toolbar_timer.stop()
            self.set_toolbar_visible(True)
        self.surface.update()

    def toggle_annotations(self):
        enabled = self.buttons['annotate'].isChecked()
        if not enabled:
            self.commit_text()
            self.set_mode('pan')
            self.annotation_row.hide()
            self.buttons['annotate'].setChecked(False)
        else:
            self.set_mode('arrow')
        self.reflow()

    def toggle_more(self):
        self.more_row.setVisible(not self.more_row.isVisible())
        self.reflow()

    def set_status(self, text, action=None):
        self.status.setText(text)
        self.corner_message.present(text, action=action)

    def show_saved_status(self, path):
        anchor = self.surface.mapToGlobal(self.surface.rect().center())
        notice = create_save_notice(path, self.settings, anchor)
        self.close()
        return notice

    def open_save_folder(self, folder):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(folder).absolute()))):
            self.set_status("無法開啟儲存資料夾，請檢查系統的預設檔案管理器。")

    def dismiss_hint(self):
        self.corner_message.dismiss()

    def owned_popup(self):
        popup = QApplication.activePopupWidget()
        # QWidget.isAncestorOf stops at native window boundaries. Combo-box
        # popup containers are top-level windows but retain their QObject parent.
        owner = popup
        while owner is not None:
            if owner is self:
                return popup
            owner = owner.parent()
        return None

    def contains_interaction(self, position):
        popup = self.owned_popup()
        return (self.mask().contains(self.mapFromGlobal(position))
                or bool(popup and popup.rect().contains(popup.mapFromGlobal(position)))
                or bool(self.corner_message.isVisible() and self.corner_message.action
                        and self.corner_message.geometry().contains(position))
                or (self.popup_timer.isActive() and self.popup_rect.contains(position)))

    def set_toolbar_visible(self, visible):
        if visible == self.toolbar_visible or self.closing:
            return
        origin = self.image_origin()
        self.toolbar_visible = visible
        self.tools.setVisible(visible)
        self.layout_at(origin)

    def check_toolbar(self):
        if self.closing or self.suspended or not self.isVisible():
            return
        if not self.pinned:
            self.set_toolbar_visible(True)
            return
        if self.hold or self.owned_popup() or QApplication.mouseButtons() or self.text_input.isVisible():
            self.toolbar_timer.start()
            return
        position = self.mapFromGlobal(QCursor.pos())
        inside = self.surface.geometry().contains(position) or (self.toolbar_visible and self.tools.geometry().contains(position))
        self.set_toolbar_visible(inside)

    def hideEvent(self, event):
        if hasattr(self, 'magnifier'):
            self.magnifier.hide()
        if hasattr(self, 'corner_message'):
            self.corner_message.dismiss()
        super().hideEvent(event)

    def choose_annotation_color(self, color):
        self.color = color
        for value, button in self.color_buttons.items():
            button.setChecked(value == color)
            button.setText('✓' if value == color else '')
            button.setProperty('selected', value == color)
        self.resize_text_input()

    def set_annotation_width(self, value):
        self.stroke = value
        self.width_label.setText('大小 '+str(value))
        self.resize_text_input()

    def set_mode(self, mode):
        self.dismiss_hint()
        if self.busy:
            return
        if mode != "ocr":
            self.cancel_translation()
        if mode != "ocr" and self.ocr_job and not self.ocr_job.done:
            self.clear_ocr()
        self.cancel_text()
        self.color_mode = False
        self.pixel_hex = None
        self.pixel_point = None
        self.magnifier.hide()
        self.buttons['color'].setChecked(False)
        self.mode = mode
        self.group.setExclusive(False)
        for button in self.group.buttons():
            button.setChecked(False)
        self.group.setExclusive(True)
        self.buttons["ocr"].setChecked(mode == "ocr")
        self.ocr_row.setVisible(mode == "ocr" and self.selection is not None)
        if mode == "ocr":
            self.annotation_row.hide()
            self.buttons["annotate"].setChecked(False)
        elif mode != "pan":
            self.annotation_row.show()
            self.buttons["annotate"].setChecked(True)
        if mode in self.buttons:
            self.buttons[mode].setChecked(True)
        self.surface.setCursor(Qt.OpenHandCursor if mode == "pan" else Qt.IBeamCursor if mode == "ocr" else Qt.CrossCursor)
        self.surface.points = []
        self.surface.preview = None
        self.reflow()
        self.surface.update()

    def clear_ocr(self):
        if self.qr_job:
            self.qr_job.cleanup()
            self.qr_job.deleteLater()
            self.qr_job = None
        self.hide_result()
        self.translation_image = None
        self.original_selection = None
        self.translation_lines = []
        self.translate_after_ocr = False
        self.cancel_translation()
        self.translation_row.hide()
        self.translation_output.clear()
        self.buttons["translate"].setChecked(False)
        if self.ocr_job:
            self.ocr_job.cleanup()
            self.ocr_job.deleteLater()
            self.ocr_job = None
        self.selection = None
        self.ocr_row.hide()
        self.buttons["ocr"].setChecked(False)

    def add_mark(self, mark):
        if self.translation_image is not None:
            self.document.replace(self.translation_image)
        self.clear_ocr()
        self.document.add(mark)
        self.update_state()

    def crop(self, rect):
        self.clear_ocr()
        origin = self.image_origin()
        crop_rect = rect.toAlignedRect().intersected(self.document.base.rect())
        origin += QPoint(round(crop_rect.x() * self.surface.width() / self.document.base.width()),
                         round(crop_rect.y() * self.surface.height() / self.document.base.height()))
        if self.document.crop(rect):
            self.region = None
            self.layout_at(origin)
            self.update_state()

    def update_state(self):
        self.buttons["undo"].setEnabled(bool(self.document.past) and not self.busy)
        self.buttons["redo"].setEnabled(bool(self.document.future) and not self.busy)
        self.annotation_undo.setEnabled(bool(self.document.past) and not self.busy)
        self.annotation_redo.setEnabled(bool(self.document.future) and not self.busy)
        self.buttons["scroll"].setEnabled(self.region is not None and not self.busy)
        self.buttons["ocr"].setEnabled(not self.busy)
        self.buttons["translate"].setEnabled(not self.busy)
        self.buttons["qr"].setEnabled(not self.busy)
        self.buttons["record"].setEnabled(self.region is not None and not self.busy)
        self.surface.update()
        self.reflow()

    def undo(self):
        if not self.busy and self.document.undo():
            self.clear_ocr()
            self.set_mode("pan")
            self.update_state()

    def redo(self):
        if not self.busy and self.document.redo():
            self.clear_ocr()
            self.set_mode("pan")
            self.update_state()

    def begin_text(self, point):
        self.text_point = QPointF(point)
        self.text_input.clear()
        self.text_input.show()
        self.resize_text_input()
        self.text_input.setFocus()
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
        self.set_status('直接輸入文字 · Enter 確認 · Shift+Enter 換行 · Esc 取消')

    def resize_text_input(self):
        if not self.text_input.isVisible() or not hasattr(self,'text_point'):
            return
        sx = self.surface.width() / self.document.base.width()
        sy = self.surface.height() / self.document.base.height()
        font = QFont('Noto Sans CJK TC')
        font.setPixelSize(max(1, round(max(16, self.stroke * 6) * sy)))
        self.text_input.setFont(font)
        self.text_input.setStyleSheet(f'QPlainTextEdit {{background:transparent;color:{self.color};border:0;padding:0;selection-background-color:#5364b8;}}')
        metrics = QFontMetricsF(font)
        lines = self.text_input.toPlainText().split('\n')
        lines[-1] += self.text_input.preedit
        width = max([metrics.horizontalAdvance(line) for line in lines]+[120]) + 6
        height = metrics.lineSpacing() * (len(lines)+1) + 4
        x,y = round(self.text_point.x()*sx),round(self.text_point.y()*sy)
        self.text_input.setGeometry(x,y,max(1,min(round(width),self.surface.width()-x)),
            max(1,min(round(height),self.surface.height()-y)))
        self.text_input.horizontalScrollBar().setValue(0)
        self.text_input.verticalScrollBar().setValue(0)

    def commit_text(self):
        if not self.text_input.isVisible():
            return
        text = self.text_input.toPlainText()
        if text.strip():
            p = self.text_point
            self.add_mark(Mark("text", ((p.x(), p.y()),), self.color, self.stroke, text))
        self.cancel_text()
        self.dismiss_hint()

    def cancel_text(self):
        editing = self.text_input.isVisible()
        self.text_input.hide()
        self.text_input.preedit = ""
        if editing and not self.closing:
            self.surface.setFocus()
        for shortcut in getattr(self, "shortcuts", []):
            shortcut.setEnabled(True)

    def run_ocr(self):
        self.dismiss_hint()
        if self.busy:
            return
        if self.ocr_job and not self.ocr_job.done:
            self.clear_ocr()
            self.set_status("已取消文字識別")
            return
        if self.selection is not None:
            self.set_mode("pan" if self.mode == "ocr" else "ocr")
            return
        if self.ocr_job:
            self.ocr_job.deleteLater()
            self.ocr_job = None
        self.set_mode("ocr")
        self.buttons["ocr"].setChecked(True)
        self.set_status("正在本機識別文字…再次按 OCR 可取消")
        self.ocr_job = OcrJob(self.document.render(), self, positioned=True, settings=self.settings)
        self.ocr_job.layoutReady.connect(self.ocr_complete)
        self.ocr_job.failed.connect(self.ocr_failed)
        self.ocr_job.start()

    def retry_ocr(self):
        self.clear_ocr()
        self.run_ocr()

    def ocr_complete(self, words, languages):
        if self.closing:
            return
        self.selection = TextSelection(words)
        if not words:
            self.translate_after_ocr = False
            self.buttons["translate"].setChecked(False)
            self.selection = None
            self.buttons["ocr"].setChecked(False)
            self.mode = "pan"
            self.set_status("沒有識別到文字，請選擇更清楚的區域再試。")
            return
        pending = self.translate_after_ocr
        self.translate_after_ocr = False
        self.set_mode("ocr")
        if pending:
            self.translate_selection()

    def ocr_failed(self, message):
        self.translate_after_ocr = False
        self.buttons["translate"].setChecked(False)
        if not self.closing:
            self.buttons["ocr"].setChecked(False)
            self.mode = "pan"
            self.set_status(message)

    def refresh_translation_settings(self):
        config = get_config(self.settings)
        self.translation_provider.setCurrentIndex(max(0, self.translation_provider.findData(config['provider'])))
        self.translation_target.setCurrentIndex(max(0, self.translation_target.findData(config['target'])))

    def open_translation_settings(self):
        if not self.pinned:
            self.toggle_pin()
        self.settingsRequested.emit()

    def run_translation(self):
        self.dismiss_hint()
        if self.busy:
            return
        if self.translate_after_ocr:
            self.clear_ocr()
            self.set_status("已取消翻譯與文字識別")
            return
        if self.translation_job and not self.translation_job.done:
            self.cancel_translation()
            self.set_status("已取消翻譯")
            return
        if self.translation_row.isVisible():
            self.restore_original_translation()
            self.translation_row.hide()
            self.buttons['translate'].setChecked(False)
            self.reflow()
            return
        self.buttons['translate'].setChecked(True)
        if self.selection is None:
            if not (self.ocr_job and not self.ocr_job.done):
                self.run_ocr()
            if self.ocr_job and not self.ocr_job.done:
                self.translate_after_ocr = True
            return
        self.translation_row.show()
        if not self.translation_output.toPlainText():
            self.translate_selection()
        self.reflow()

    def translate_selection(self):
        self.dismiss_hint()
        if self.translation_job and not self.translation_job.done:
            self.cancel_translation()
            self.set_status("已取消翻譯")
            return
        if not self.selection:
            self.run_translation()
            return
        self.cancel_translation()
        self.translation_row.show()
        self.buttons['translate'].setChecked(True)
        config = get_config(self.settings, self.translation_provider.currentData())
        config['target'] = self.translation_target.currentData()
        source_selection = self.original_selection or self.selection
        self.translation_lines = selected_lines(source_selection)
        self.translation_source_selection = source_selection
        self.translation_source_image = self.document.render()
        self.translation_output.clear()
        self.translation_job = PositionedTranslationJob(config, self.translation_lines, self)
        self.translation_job.finished.connect(self.translation_complete)
        self.translation_job.failed.connect(self.translation_failed)
        self.translation_job.progress.connect(lambda index,total: self.set_status(f'正在原位翻譯 {index} / {total} 行…再次按翻譯可取消'))
        self.reflow()
        self.translation_job.start()

    def translation_complete(self, texts):
        if self.closing:
            return
        try:
            image, selection, sizes = translated_overlay(self.translation_source_image,
                self.translation_source_selection, self.translation_lines, texts)
        except ValueError as exc:
            self.translation_failed(str(exc))
            return
        self.original_selection = self.translation_source_selection
        self.translation_image = image
        self.selection = selection
        self.translation_output.setPlainText('\n'.join(texts))
        self.set_mode('ocr')
        self.translation_row.show()
        self.buttons['translate'].setChecked(True)
        self.reflow()
        self.set_status('翻譯完成 · 直接在圖片上選取譯文；「原文」可還原')

    def restore_original_translation(self):
        self.cancel_translation()
        if self.original_selection is not None:
            self.selection = self.original_selection
        self.translation_image = None
        self.original_selection = None
        self.translation_output.clear()
        self.surface.update()

    def translation_failed(self, message):
        if not self.closing:
            self.translation_output.setPlaceholderText(message)
            self.set_status(message)

    def copy_translation(self):
        if self.translation_output.toPlainText():
            QApplication.clipboard().setText(self.translation_output.toPlainText())
            self.set_status("譯文已複製")

    def cancel_translation(self):
        if self.translation_job:
            self.translation_job.cancel()
            self.translation_job.deleteLater()
            self.translation_job = None
        if hasattr(self, 'translation_output'):
            self.translation_output.setPlaceholderText("翻譯結果會出現在這裡，可選取或複製。")

    def select_all(self):
        if self.result_text.hasFocus():
            self.result_text.selectAll()
            return
        if self.translation_output.hasFocus():
            self.translation_output.selectAll()
            return
        if self.selection and self.mode == "ocr":
            self.selection.select_all()
            self.surface.update()

    def copy_text(self):
        if self.selection:
            QApplication.clipboard().setText(self.selection.selected_text or self.selection.all_text)
            self.set_status("文字已複製 · 可繼續在貼圖上選取")

    def copy(self):
        self.dismiss_hint()
        if self.result_text.hasFocus():
            self.copy_result()
            return
        if self.translation_output.hasFocus():
            cursor = self.translation_output.textCursor()
            QApplication.clipboard().setText(cursor.selectedText().replace("\u2029", "\n") or self.translation_output.toPlainText())
            return
        if self.mode == "ocr" and self.selection and self.selection.selected_text:
            self.copy_text()
        else:
            QApplication.clipboard().setImage(self.render_image())
            self.set_status("圖片已複製 · 點擊目標應用即可貼上")

    def sample_color(self, pos):
        if not self.color_mode or self.surface.points or self.text_input.isVisible():
            self.magnifier.hide()
            return
        point = self.surface.source_point(pos)
        self.show_pixel(QPoint(int(point.x()), int(point.y())), self.surface.mapToGlobal(pos))

    def show_pixel(self, point, cursor):
        image = self.render_image()
        self.pixel_point = QPoint(max(0, min(point.x(), image.width() - 1)),
                                  max(0, min(point.y(), image.height() - 1)))
        self.pixel_hex = image.pixelColor(self.pixel_point).name(QColor.HexRgb).upper()
        self.magnifier.present(image, self.pixel_point, cursor)

    def nudge_color(self, dx, dy):
        if not self.color_mode:
            return
        point = self.pixel_point if self.pixel_point is not None else self.document.base.rect().center()
        self.show_pixel(point + QPoint(dx, dy), QCursor.pos())

    def escape(self):
        if self.color_mode:
            self.toggle_color()
        else:
            self.close()

    def toggle_color(self):
        self.dismiss_hint()
        if self.busy:
            return
        enabled = not self.color_mode
        self.set_mode('pan')
        self.color_mode = enabled
        self.buttons['color'].setChecked(enabled)
        self.surface.setCursor(Qt.CrossCursor if enabled else Qt.OpenHandCursor)
        self.surface.setFocus()
        position = self.surface.mapFromGlobal(QCursor.pos())
        if enabled and self.surface.rect().contains(position):
            self.sample_color(position)

    def copy_color(self):
        self.dismiss_hint()
        if self.color_mode and self.pixel_hex:
            copied = self.pixel_hex
            QApplication.clipboard().setText(copied)
            self.set_mode('pan')
            self.set_status('已複製色碼 ' + copied + ' · 已退出取色')

    def toggle_image_search(self):
        self.dismiss_hint()
        if self.color_mode:
            self.toggle_color()
        self.search_row.setVisible(not self.search_row.isVisible())
        self.buttons['image_search'].setChecked(self.search_row.isVisible())
        self.reflow()

    def open_image_search(self):
        if not self.pinned:
            self.toggle_pin()
        if not QDesktopServices.openUrl(QUrl(self.search_provider.currentData())):
            self.set_status('無法開啟預設瀏覽器，請檢查系統的預設應用程式。')

    def copy_search_path(self):
        try:
            path = prepare_image(self.render_image())
            if not self.pinned:
                self.toggle_pin()
            QApplication.clipboard().setText(str(path))
            self.set_status('圖片路徑已複製 · 在網頁的上傳檔案對話框按 Ctrl+L 後貼上')
        except (ValueError, OSError) as exc:
            self.set_status('無法準備搜尋圖片：' + str(exc))

    def show_result(self, title, text, path=None, urls=None):
        self.result_path = path
        self.result_links.clear()
        for url in urls or []:
            self.result_links.addItem(url.toDisplayString(), url)
        self.result_links.setVisible(self.result_links.count() > 1)
        self.open_result_button.setText('開啟')
        self.open_result_button.setToolTip('以預設瀏覽器開啟二維碼網址' if urls else '以系統預設程式開啟檔案')
        self.open_result_button.setVisible(bool(path or urls))
        self.result_title.setText(title)
        self.result_text.setPlainText(text)
        self.result_row.show()
        self.reflow()

    def open_result(self):
        url = QUrl.fromLocalFile(self.result_path) if self.result_path else self.result_links.currentData()
        if url:
            if not self.pinned:
                self.toggle_pin()
            if not QDesktopServices.openUrl(url):
                self.set_status('無法開啟，請檢查系統的預設應用程式。')

    def hide_result(self):
        self.result_path = None
        self.result_links.clear()
        self.result_links.hide()
        self.open_result_button.hide()
        self.result_row.hide()
        self.result_text.clear()
        self.buttons['qr'].setChecked(False)
        self.reflow()

    def copy_result(self):
        cursor = self.result_text.textCursor()
        QApplication.clipboard().setText(cursor.selectedText().replace('\u2029', '\n') or self.result_text.toPlainText())
        self.set_status('已複製')

    def run_qr(self):
        self.dismiss_hint()
        if self.busy:
            return
        if self.qr_job and not self.qr_job.done:
            self.qr_job.cleanup()
            self.set_status('已取消二維碼識別')
            return
        if self.result_row.isVisible() and self.result_title.text().startswith('二維碼'):
            self.hide_result()
            return
        if self.qr_job:
            self.qr_job.deleteLater()
        self.buttons['qr'].setChecked(True)
        self.qr_job = QrJob(self.render_image(), self)
        self.qr_job.finished.connect(self.qr_complete)
        self.qr_job.failed.connect(self.set_status)
        self.set_status('正在本機識別二維碼…')
        self.qr_job.start()

    def qr_complete(self, codes):
        if self.closing:
            return
        urls = []
        for code in codes:
            url = web_url(code['text'])
            if url is not None and url not in urls:
                urls.append(url)
        self.show_result(f'二維碼 · {len(codes)} 個結果', '\n\n'.join(code['text'] for code in codes) if codes else '沒有找到二維碼。請包含完整邊框，或放大來源後重新截圖。', urls=urls)

    def toggle_record(self):
        self.dismiss_hint()
        if is_wayland():
            self.set_status("GIF / WebP 錄製目前支援 X11 工作階段。")
            return
        if self.region is None:
            self.set_status('請先截取螢幕區域，再按錄製按鈕；匯入的圖片沒有對應螢幕座標。')
            return
        self.record_row.setVisible(not self.record_row.isVisible())
        self.buttons['record'].setChecked(self.record_row.isVisible())
        self.reflow()

    def start_record(self):
        options = {'format': self.record_format.currentData(), 'fps': self.record_fps.value(),
                   'duration': self.record_duration.value(), 'width': self.record_width.value(), 'cursor': self.record_cursor.isChecked()}
        for key, value in options.items():
            self.settings.setValue('record/' + key, value)
        if not self.pinned:
            self.toggle_pin()
        self.recordRequested.emit(self, options)

    def quick_save(self):
        self.dismiss_hint()
        if self.settings.value('ask_save_path', False, type=bool):
            self.save_as()
            return
        folder = save_directory(self.settings)
        path = folder / ("rainshot_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self.save_to(path)
        except OSError as exc:
            self.set_status("無法建立儲存資料夾：" + str(exc))

    def save_to(self, path):
        try:
            save_image(self.render_image(), path)
            self.last_save = str(path)
            self.saved.emit(str(path))
            self.show_saved_status(path)
            return True
        except (ValueError, OSError) as exc:
            self.set_status("儲存失敗：" + str(exc))
            return False

    def save_as(self):
        self.hold += 1
        try:
            path, selected = QFileDialog.getSaveFileName(self, "另存圖片", str(save_directory(self.settings) / "rainshot.png"), "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)")
            if path:
                if not Path(path).suffix:
                    path += ".jpg" if "JPEG" in selected else ".webp" if "WebP" in selected else ".png"
                self.save_to(path)
        finally:
            self.hold -= 1
            if not self.closing:
                self.activateWindow()

    def request_scroll(self):
        self.dismiss_hint()
        if is_wayland():
            self.set_status("連續長截目前支援 X11；Wayland 可從更多選單逐張拼接圖片。")
            return
        if self.busy:
            return
        if self.document.marks or self.region is None:
            self.set_status("請在標註、裁剪前追加長截圖；也可從更多選單拼接圖片。")
            return
        if not self.pinned:
            self.toggle_pin()
        self.scrollRequested.emit(self)

    def append_file(self):
        if self.busy:
            return
        self.hold += 1
        try:
            path, _ = QFileDialog.getOpenFileName(self, "加入下一張重疊圖片", "", "圖片 (*.png *.jpg *.jpeg *.webp)")
            if path:
                self.append_image(load_image(path))
        except (ValueError, OSError) as exc:
            self.set_status(str(exc))
        finally:
            self.hold -= 1
            self.activateWindow()

    def append_image(self, image):
        if self.stitch_job and self.stitch_job.isRunning():
            return
        self.busy = True
        if not self.pinned:
            self.toggle_pin()
        self.set_status("正在檢查重疊區域…")
        self.stitch_job = StitchJob(self.document.render(), image, self)
        self.stitch_job.result.connect(self.accept_stitch)
        self.stitch_job.failed.connect(self.set_status)
        self.stitch_job.finished.connect(self.stitch_finished)
        self.stitch_job.start()
        self.update_state()

    def accept_stitch(self, image, overlap):
        if self.closing:
            return
        self.clear_ocr()
        self.document.replace(image)
        # Fit long images to the available screen, retaining the same image origin.
        self.scale = min(self.scale, (self.screen_geometry.height() - 170) / image.height())
        self.set_status(f"拼接完成 · 重疊 {overlap} px · 可繼續捲動、追加")
        self.update_state()

    def stitch_finished(self):
        self.busy = False
        if self.stitch_job:
            self.stitch_job.deleteLater()
            self.stitch_job = None
        if self.closing:
            self.deleteLater()
        else:
            self.update_state()

    def closeEvent(self, event):
        if self.closing:
            event.accept()
            return
        self.closing = True
        self.magnifier.hide()
        if self.outside_clicks:
            self.outside_clicks.stop()
        self.deactivate_timer.stop()
        self.toolbar_timer.stop()
        self.popup_timer.stop()
        self.corner_message.dismiss()
        self.cancel_translation()
        QApplication.instance().removeEventFilter(self)
        self.clear_ocr()
        # Hide immediately, but keep the QObject alive until its worker is done.
        if self.stitch_job and self.stitch_job.isRunning():
            self.setAttribute(Qt.WA_DeleteOnClose, False)
        event.accept()
        self.closed.emit(self)

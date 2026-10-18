"""Browser handoff using standard image-file drag and drop; no HTTP uploads."""
import time
import tempfile
from pathlib import Path
from PyQt5.QtCore import Qt, QPoint, QMimeData, QUrl, QStandardPaths
from PyQt5.QtGui import QDrag, QPixmap
from PyQt5.QtWidgets import QApplication, QToolButton
from .imaging import save_image

SEARCH_PROVIDERS = [('Google Lens', 'https://www.google.com/imghp?hl=zh-TW'),
                    ('Bing 圖像搜尋', 'https://www.bing.com/images')]


def web_url(text):
    """QR data stays inert except for explicit HTTP(S) navigation."""
    value = text.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    url = QUrl(value, QUrl.StrictMode)
    if not url.isValid() or url.scheme().lower() not in ('http', 'https') or not url.host() or url.userInfo():
        return None
    return url


def prune_search_cache(directory):
    files = sorted((p for p in directory.glob('search-*.png') if p.is_file() and not p.is_symlink()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for index, path in enumerate(files):
        total += path.stat().st_size
        if index >= 20 or total > 256 * 1024 * 1024 or time.time() - path.stat().st_mtime > 86400:
            path.unlink(missing_ok=True)


def prepare_image(image):
    directory = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / 'image-search'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    prune_search_cache(directory)
    with tempfile.NamedTemporaryFile(prefix='search-', suffix='.png', dir=directory, delete=False) as file:
        path = Path(file.name)
    try:
        save_image(image, path)
        path.chmod(0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def image_mime(image, path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    mime.setImageData(image)
    return mime


class ImageDragButton(QToolButton):
    def __init__(self, shot):
        super().__init__()
        self.shot, self.start = shot, None
        self.setText('拖曳截圖到網頁')
        self.setToolTip('按住並拖到搜尋網頁的圖片上傳區；會上傳目前截圖（包含標註）')
        self.setAccessibleName(self.text())
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        self.start = QPoint(event.pos()) if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start is None or not event.buttons() & Qt.LeftButton:
            return
        if (event.pos() - self.start).manhattanLength() < QApplication.startDragDistance():
            return
        self.start = None
        shot = self.shot
        shot.hold += 1
        drag = None
        try:
            image = shot.render_image()
            path = prepare_image(image)
            if not shot.pinned:
                shot.toggle_pin()
            drag = QDrag(self)
            drag.setMimeData(image_mime(image, path))
            drag.setPixmap(QPixmap.fromImage(image.scaled(140, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            drag.setHotSpot(QPoint(10, 10))
            drag.exec_(Qt.CopyAction)
        except (OSError, ValueError) as exc:
            shot.set_status('無法準備搜尋圖片：' + str(exc))
        finally:
            # Browsers can consume the URL after the drag loop ends. Keep its
            # private file until later bounded cache cleanup, not widget close.
            if drag:
                drag.deleteLater()
            self.setDown(False)
            shot.hold -= 1

    def mouseReleaseEvent(self, event):
        self.start = None
        super().mouseReleaseEvent(event)

"""Application preferences and the shared destination for explicit exports."""
import os
import tempfile
from pathlib import Path
from PyQt5.QtCore import QSettings, QStandardPaths


def load_settings():
    settings = QSettings('rainshot', 'rainshot')
    settings.remove('migration')
    settings.remove('pixel_color')
    return settings


def default_save_directory():
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return Path(pictures or Path.home()) / 'rainshot'


def save_directory(settings):
    value = str(settings.value('save_directory', '')).strip()
    return Path(value).expanduser() if value else default_save_directory()


def validate_save_directory(value):
    folder = Path(value).expanduser() if value.strip() else default_save_directory()
    if not folder.is_absolute():
        raise ValueError('請填入絕對路徑，例如 ~/圖片/rainshot。')
    folder.mkdir(parents=True, exist_ok=True)
    # Check read-only mounts and ACLs before accepting the preference.
    with tempfile.TemporaryFile(dir=folder):
        pass
    return folder


def copy_original(source, destination):
    """Atomically copy original bytes, preserving animated GIF/WebP files."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        return
    if destination.suffix.lower() != source.suffix.lower():
        raise ValueError('請保留原始副檔名；此操作會儲存原檔，保留動畫與畫質。')
    temporary = None
    try:
        with source.open('rb') as reader, tempfile.NamedTemporaryFile(
                prefix='.rainshot-save-', dir=destination.parent, delete=False) as writer:
            temporary = Path(writer.name)
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)

"""Bounded local capture history. Never delete user-saved images."""
import os
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import QStandardPaths
from .imaging import save_image


class History:
    def __init__(self, settings, directory=None):
        self.settings = settings
        self.directory = Path(directory or QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / 'captures'

    def captures(self):
        if not self.directory.exists():
            return []
        return sorted((p for p in self.directory.glob('capture_*.png') if p.is_file() and not p.is_symlink()), reverse=True)

    def record(self, image):
        if not self.settings.value('capture_history_enabled', self.settings.value('history_enabled', True, type=bool), type=bool):
            return None
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / ('capture_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.png')
        save_image(image, path)
        os.chmod(path, 0o600)
        self.prune()
        return str(path)

    def prune(self):
        count = max(1, min(100, self.settings.value('history_limit', 30, type=int)))
        total = 0
        for index, path in enumerate(self.captures()):
            total += path.stat().st_size
            if index >= count or total > 256 * 1024 * 1024:
                path.unlink(missing_ok=True)

    def entries(self):
        paths = [str(p) for p in self.captures()]
        saved = self.settings.value('history', [], type=list)
        return paths + [p for p in saved if isinstance(p, str) and p not in paths and Path(p).is_file()]

    def clear(self):
        for path in self.captures():
            path.unlink(missing_ok=True)
        self.settings.setValue('history', [])

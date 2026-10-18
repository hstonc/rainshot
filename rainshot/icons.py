"""Original 24px vector toolbar artwork, rendered at the display's pixel ratio."""
from PyQt5.QtCore import QByteArray, QSize, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

PATHS = {
    'image_search': '<path d="M11 20H3V3h17v8M3 14l5-5 5 5"/><circle cx="16" cy="16" r="4"/><path d="m19 19 3 3"/><circle cx="15" cy="7" r="1"/>',
    'qr': '<path d="M3 3h6v6H3Zm12 0h6v6h-6ZM3 15h6v6H3Zm12 0h3v3h3v3h-6Zm-3-3h9M12 3v6M3 12h6m3 3v6"/>',
    'color': '<path d="m15 3 6 6-3 3-2-2-9 9-4 2 2-4 9-9-2-2ZM9 13l3 3"/>',
    'record': '<rect x="3" y="5" width="18" height="14" rx="3"/><circle cx="12" cy="12" r="4" fill="currentColor"/>',
    'stop': '<rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/>',
    'play': '<path d="m7 4 14 8-14 8Z"/>',

    'annotate': '<path d="m4 17-1 4 4-1L20 7l-3-3Z M14 7l3 3"/>',
    'ocr': '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M7 9h10m-5 0v8m-3 0h6"/>',
    'translate': '<path d="M3 5h11M8 3v2m-3 3c1 4 4 6 8 8m-2-11c0 5-3 10-8 12m11 4 4-11 4 11m-6-4h4"/>',
    'pin': '<path d="m9 3 10 4-3 2-2 5 1 4-5-2-5-2 4-2 2-5Z M10 16l-4 6"/>',
    'scroll': '<rect x="5" y="3" width="14" height="7" rx="2"/><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5m-7-1v6m-3-3 3 3 3-3"/>',
    'save': '<path d="M4 3h13l4 4v14H3V3Zm3 0v6h10V3M7 21v-8h10v8"/>',
    'copy': '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    'undo': '<path d="M8 4 3 9l5 5M3 9h11a7 7 0 0 1 0 14" transform="translate(0 -2)"/>',
    'redo': '<path d="m16 4 5 5-5 5m5-5H10a7 7 0 0 0 0 14" transform="translate(0 -2)"/>',
    'more': '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    'close': '<path d="m6 6 12 12M18 6 6 18"/>',
    'pan': '<path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3m12-6 3 3-3 3"/>',
    'rect': '<rect x="4" y="5" width="16" height="14" rx="1"/>',
    'ellipse': '<ellipse cx="12" cy="12" rx="9" ry="7"/>',
    'arrow': '<path d="M4 20 20 4M10 4h10v10"/>',
    'line': '<path d="M4 20 20 4"/>',
    'pen': '<path d="M4 18c-2 5 6 5 6 0 0-2-4-3-6 0Zm4-3L17 3l4 3-11 11"/>',
    'highlight': '<path d="m5 15 8-12 7 5-8 12ZM5 15l7 5m-7-4-2 4h5M2 23h20"/>',
    'text': '<path d="M4 7V4h16v3M12 4v16m-5 0h10"/>',
    'number': '<circle cx="12" cy="12" r="9"/><path d="m9 9 3-2v10m-3 0h6"/>',
    'mosaic': '<path d="M3 3h18v18H3Zm6 0v18m6-18v18M3 9h18M3 15h18"/><path d="M3 3h6v6H3Zm6 6h6v6H9Zm6 6h6v6h-6Z" fill="currentColor"/>',
    'redact': '<rect x="3" y="6" width="18" height="12" rx="1" fill="currentColor"/>',
    'crop': '<path d="M7 2v15h15M2 7h15v15"/>',
}


def svg(name, color):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" color="{color}" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round">{PATHS[name]}</svg>').replace('currentColor', color)


def icon(name):
    result = QIcon()
    for state, color in [(QIcon.Off, '#edf0ff'), (QIcon.On, '#17213c')]:
        for mode, ink in [(QIcon.Normal, color), (QIcon.Disabled, '#73809c')]:
            for ratio in (1, 2, 3):
                pixmap = QPixmap(QSize(24 * ratio, 24 * ratio))
                pixmap.setDevicePixelRatio(ratio)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                QSvgRenderer(QByteArray(svg(name, ink).encode())).render(painter)
                painter.end()
                result.addPixmap(pixmap, mode, state)
    return result

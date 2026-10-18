"""Positioned OCR with selectable graphemes in source-image coordinates."""
from dataclasses import dataclass
import re
from PyQt5.QtCore import QRectF, QPointF, QTextBoundaryFinder
from PyQt5.QtGui import QFont, QFontMetricsF


@dataclass(frozen=True)
class Word:
    text: str
    rect: QRectF
    line: tuple
    confidence: float


def parse_tsv(text, width, height):
    words = []
    bounds = QRectF(0, 0, width, height)
    for row in text.splitlines():
        fields = row.split("\t", 11)
        if len(fields) != 12 or fields[0] != "5" or not fields[11].strip():
            continue
        try:
            line = tuple(int(n) for n in fields[1:5])
            x, y, w, h = (int(n) for n in fields[6:10])
            confidence = float(fields[10])
        except ValueError:
            continue
        rect = QRectF(x, y, w, h).intersected(bounds)
        if w <= 0 or h <= 0 or rect.isEmpty() or confidence < 0:
            continue
        words.append(Word(fields[11].strip(), rect, line, confidence))
    return words


def graphemes(text):
    # Qt's boundary finder uses UTF-16 indices, so slice UTF-16 bytes, not Python
    # code points; emoji and combining marks remain a single selectable unit.
    finder = QTextBoundaryFinder(QTextBoundaryFinder.Grapheme, text)
    encoded = text.encode("utf-16-le")
    start = 0
    result = []
    while True:
        end = finder.toNextBoundary()
        if end == -1:
            break
        result.append(encoded[start * 2:end * 2].decode("utf-16-le"))
        start = end
    return result


def cjk(char):
    return bool(char) and bool(re.match(r"[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]", char))


def separator(previous, word):
    if previous is None:
        return ""
    if previous.line != word.line:
        return "\n"
    if word.text[0] in ",.;:!?，。！？、；：%…)]}」』》" or previous.text[-1] in "([{（【「『《“‘":
        return ""
    if cjk(word.text[0]) and previous.text[-1] in ",.;:!?":
        return ""
    if cjk(previous.text[-1]) and cjk(word.text[0]):
        return ""
    return " "


@dataclass
class Glyph:
    text: str
    rect: QRectF
    word: int
    prefix: str = ""


class TextSelection:
    def __init__(self, words):
        self.words = list(words)
        self.glyphs = []
        self.anchor = None
        self.end = None
        previous = None
        line_rects = {}
        for word in self.words:
            line_rects[word.line] = line_rects.get(word.line, QRectF()).united(word.rect)
        for index, word in enumerate(self.words):
            clusters = graphemes(word.text)
            font = QFont("Noto Sans CJK TC")
            font.setPixelSize(max(1, round(word.rect.height())))
            metrics = QFontMetricsF(font)
            advances = [max(.1, metrics.horizontalAdvance(char)) for char in clusters]
            total = sum(advances)
            x = word.rect.left()
            for offset, (char, advance) in enumerate(zip(clusters, advances)):
                width = word.rect.width() * advance / total
                line_rect = line_rects[word.line]
                rect = QRectF(x, line_rect.y(), width, line_rect.height())
                self.glyphs.append(Glyph(char, rect, index, separator(previous, word) if offset == 0 else ""))
                x += width
            previous = word

    @property
    def all_text(self):
        return "".join(g.prefix + g.text for g in self.glyphs)

    @property
    def selected(self):
        if self.anchor is None or self.end is None:
            return []
        a, b = sorted((self.anchor, self.end))
        return self.glyphs[a:b + 1]

    @property
    def selected_text(self):
        selected = self.selected
        if not selected:
            return ""
        return selected[0].text + "".join(g.prefix + g.text for g in selected[1:])

    @property
    def highlight_rects(self):
        lines = {}
        for glyph in self.selected:
            line = self.words[glyph.word].line
            lines[line] = lines.get(line, QRectF()).united(glyph.rect)
        return list(lines.values())

    def hit(self, point, nearest=False):
        for index, glyph in enumerate(self.glyphs):
            if glyph.rect.contains(point):
                return index
        if nearest and self.glyphs:
            def distance(g):
                r = g.rect
                dx = max(r.left() - point.x(), 0, point.x() - r.right())
                dy = max(r.top() - point.y(), 0, point.y() - r.bottom())
                return dx * dx + dy * dy * 4
            return min(range(len(self.glyphs)), key=lambda i: distance(self.glyphs[i]))
        return None

    def begin(self, point):
        self.anchor = self.hit(point)
        self.end = self.anchor

    def extend(self, point):
        if self.anchor is not None:
            self.end = self.hit(point, nearest=True)

    def select_all(self):
        if self.glyphs:
            self.anchor, self.end = 0, len(self.glyphs) - 1

    def select_word(self, point):
        index = self.hit(point)
        if index is not None:
            indexes = [i for i, g in enumerate(self.glyphs) if g.word == self.glyphs[index].word]
            self.anchor, self.end = indexes[0], indexes[-1]

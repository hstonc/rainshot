"""Translate selected OCR lines and lay out selectable text in their original boxes."""
from collections import Counter
from dataclasses import dataclass
from PyQt5.QtCore import QObject, QTimer, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import QFont, QFontMetricsF, QPainter, QColor
from .ocr_layout import Word, Glyph, TextSelection, graphemes
from .translation import TranslationJob


@dataclass
class Line:
    text: str
    rect: QRectF
    indexes: list
    line: tuple


def selected_lines(selection):
    selected=selection.selected or selection.glyphs
    identities={id(g) for g in selected}
    groups={}
    for index,glyph in enumerate(selection.glyphs):
        if id(glyph) not in identities:continue
        key=selection.words[glyph.word].line
        groups.setdefault(key,[]).append(index)
    result=[]
    for key,indexes in groups.items():
        rect=QRectF();text=''
        for position,index in enumerate(indexes):
            glyph=selection.glyphs[index]
            rect=rect.united(glyph.rect)
            text+=(glyph.prefix if position else '')+glyph.text
        result.append(Line(text,rect,indexes,key))
    return result


class PositionedTranslationJob(QObject):
    finished=pyqtSignal(object)
    failed=pyqtSignal(str)
    progress=pyqtSignal(int,int)

    def __init__(self,config,lines,parent=None):
        super().__init__(parent)
        self.config=dict(config);self.lines=list(lines);self.results=[]
        self.current=None;self.done=False
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(120000)
        self.timer.timeout.connect(lambda:self.fail('逐行翻譯逾時，請選取較少文字後再試。'))

    def start(self):
        if self.done:return
        if not self.lines or len(self.lines)>80 or sum(len(line.text) for line in self.lines)>5000:
            self.fail('一次最多翻譯 80 行 / 5,000 字，請先選取較短的文字。');return
        self.timer.start();self.next_line()

    def next_line(self):
        if self.done:return
        if len(self.results)==len(self.lines):
            values=list(self.results);self.cancel();self.finished.emit(values);return
        self.progress.emit(len(self.results)+1,len(self.lines))
        self.current=TranslationJob(self.config,self.lines[len(self.results)].text,self)
        self.current.finished.connect(self.accept)
        self.current.failed.connect(self.fail)
        self.current.start()

    def accept(self,text):
        if self.done:return
        if len(text)>10000 or sum(map(len,self.results))+len(text)>20000:
            self.fail('譯文過長，已保留原圖。');return
        self.results.append(text)
        previous,self.current=self.current,None
        if previous:previous.deleteLater()
        QTimer.singleShot(0,self.next_line)

    def fail(self,message):
        if self.done:return
        self.cancel();self.failed.emit(message)

    def cancel(self):
        self.done=True;self.timer.stop()
        if self.current:
            self.current.cancel();self.current.deleteLater();self.current=None
        self.config.pop('key',None)


def background(image,rect):
    r=rect.toAlignedRect().intersected(image.rect())
    samples=[]
    for index in range(24):
        x=r.left()+round(index*max(0,r.width()-1)/23)
        y=r.top()+round(index*max(0,r.height()-1)/23)
        for px,py in [(x,r.top()-1),(x,r.bottom()+1),(r.left()-1,y),(r.right()+1,y)]:
            if image.rect().contains(px,py):samples.append(image.pixelColor(px,py).rgba())
    return QColor.fromRgba(Counter(samples).most_common(1)[0][0]) if samples else QColor('white')


def overlay(image,selection,lines,translations):
    if len(lines)!=len(translations):raise ValueError('譯文行數不符，已保留原圖。')
    result=image.copy();painter=QPainter(result);painter.setRenderHint(QPainter.TextAntialiasing)
    words=list(selection.words);replacements={};removed=set();sizes=[]
    try:
        for block,text in zip(lines,translations):
            # An engine may wrap a sentence; each source OCR line owns one box.
            text=' '.join(text.splitlines()).strip()
            if not text:raise ValueError('翻譯服務傳回空白行，已保留原圖。')
            rect=block.rect.intersected(QRectF(image.rect()))
            if rect.isEmpty():raise ValueError('OCR 文字範圍無效。')
            font=QFont('Noto Sans CJK TC')
            size=max(1,round(rect.height()))
            font.setPixelSize(size)
            ink_height=max(1,QFontMetricsF(font).tightBoundingRect(text).height())
            size=max(1,min(round(rect.height()*2),round(size*rect.height()/ink_height)))
            while True:
                font.setPixelSize(size);metrics=QFontMetricsF(font)
                ink_bounds=metrics.tightBoundingRect(text)
                if size==1 or (ink_bounds.height()<=rect.height() and metrics.horizontalAdvance(text)<=rect.width()):break
                size-=1
            # Extremely long outputs are clipped within the original region.
            ink=QColor('#15171d' if background(image,rect).lightnessF()>.5 else '#fafafa')
            painter.fillRect(rect,background(image,rect))
            painter.save();painter.setClipRect(rect);painter.setFont(font);painter.setPen(ink)
            baseline=rect.center().y()-ink_bounds.center().y()
            horizontal_scale=min(1,rect.width()/max(.1,metrics.horizontalAdvance(text)))
            painter.translate(rect.left(),baseline)
            painter.scale(horizontal_scale,1)
            painter.drawText(QPointF(0,0),text);painter.restore()
            sizes.append(size)
            index=len(words);words.append(Word(text,rect,block.line,100))
            clusters=graphemes(text);advances=[max(.1,metrics.horizontalAdvance(c)) for c in clusters]
            total=sum(advances);factor=min(1,rect.width()/max(.1,total));x=rect.left();glyphs=[]
            for position,(cluster,advance) in enumerate(zip(clusters,advances)):
                width=advance*factor
                glyphs.append(Glyph(cluster,QRectF(x,rect.top(),width,rect.height()),index,
                    selection.glyphs[block.indexes[0]].prefix if position==0 else ''))
                x+=width
            replacements[block.indexes[0]]=glyphs;removed.update(block.indexes)
    finally:painter.end()
    translated=TextSelection([]);translated.words=words
    for index,glyph in enumerate(selection.glyphs):
        if index in replacements:translated.glyphs.extend(replacements[index])
        elif index not in removed:translated.glyphs.append(glyph)
    return result,translated,sizes

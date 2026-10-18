"""Configurable screenshot-local keys, validated as one conflict-free set."""
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import Qt

ACTIONS = [('pin','P','釘住 / 取消釘住'), ('scroll','S','捲動長截圖'),
    ('ocr','O','文字識別'), ('translate','T','翻譯'), ('qr','Q','二維碼'),
    ('color','I','取色模式'), ('record','G','錄製 GIF / WebP'),
    ('copy_color','C','複製像素色碼'), ('copy','Ctrl+C','複製圖片 / 選取文字'),
    ('save','Ctrl+S','儲存圖片'), ('select_all','Ctrl+A','全選 OCR 文字'),
    ('undo','Ctrl+Z','上一步'), ('redo','Ctrl+Shift+Z','下一步'), ('redo_alt','Ctrl+Y','下一步（備用）'),
    ('close','Esc','結束取色 / 關閉貼圖'), ('pan','V','返回一般操作'),
    ('rect','R','矩形'), ('ellipse','E','橢圓'), ('arrow','A','箭頭'), ('line','L','直線'),
    ('pen','B','畫筆'), ('highlight','H','螢光'), ('text','X','文字'), ('number','N','序號'),
    ('mosaic','M','馬賽克'), ('redact','D','遮蓋')]


def bindings(settings=None):
    return {action: str(settings.value('local_shortcuts/'+action, key)) if settings is not None else key
            for action,key,_ in ACTIONS}


def validate(values):
    normalized={};used={}
    labels={action:label for action,_,label in ACTIONS}
    reserved={Qt.Key_Return,Qt.Key_Enter,Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down}
    for action,default,label in ACTIONS:
        raw=values.get(action,default).strip()
        sequence=QKeySequence(raw)
        if raw and (sequence.isEmpty() or sequence.count()!=1 or (sequence[0] & 0x01ffffff)==Qt.Key_unknown):
            raise ValueError(label+'：請輸入單一按鍵或組合鍵。')
        key=sequence.toString(QKeySequence.PortableText)
        if key and (sequence[0] in reserved or sequence[0]==int(Qt.SHIFT)+Qt.Key_Return):
            raise ValueError(label+'：方向鍵與 Enter 保留給取色和文字編輯。')
        if key in used:
            raise ValueError(label+' 與 '+labels[used[key]]+' 使用相同按鍵 '+key+'。')
        if key:used[key]=action
        normalized[action]=key
    return normalized


def hint(settings=None):
    keys=bindings(settings)
    groups=[[('pin','釘住'),('scroll','長截'),('ocr','識別'),('translate','翻譯'),('qr','二維碼')],
        [('color','取色'),('copy_color','複製色碼'),('record','錄製')],
        [('undo','上一步'),('redo','下一步')],
        [('copy','複製'),('save','儲存'),('close','結束 / 關閉')]]
    lines=[' · '.join(keys[action]+' '+label for action,label in group if keys[action]) for group in groups]
    return '\n'.join(line for line in lines if line)+'\n取色：方向鍵微調 · Enter 複製；文字：Enter 確認 · Shift+Enter 換行'

HINT=hint()

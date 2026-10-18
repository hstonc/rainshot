"""Actual optional PP-OCRv4 engine: synthetic image -> on-image text selection."""
import json
import os
import sys
import tempfile
from pathlib import Path
from PyQt5.QtCore import QSettings, Qt, QPoint
from PyQt5.QtGui import QImage,QPainter,QColor,QFont
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest,QSignalSpy
from rainshot.ocr import OcrJob
from rainshot.floating import FloatingShot
from rainshot.translation import TranslationJob, get_config

out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True,exist_ok=True)
temp=tempfile.TemporaryDirectory(prefix='rainshot-rapid-test-')
for key,suffix in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime')]:
 os.environ[key]=str(Path(temp.name)/suffix);Path(os.environ[key]).mkdir(mode=0o700)
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
settings=QSettings(str(out/'rapid-test.ini'),QSettings.IniFormat)
settings.setValue('ocr/engine','rapid');settings.setValue('ocr/python',str(Path(sys.argv[2]).absolute()))
image=QImage(1000,370,QImage.Format_RGB32);image.fill(Qt.white)
p=QPainter(image);p.setFont(QFont('Noto Sans CJK TC',25));p.setPen(QColor('#1b2338'))
p.drawText(35,75,'rainshot 12345');p.drawText(35,145,'繁體中文文字識別與翻譯');p.drawText(35,220,'Hello world. Local OCR test.');p.end()
image.save(str(out/'rapid-input.png'))
shot=FloatingShot(image,pinned=True,settings=settings);shot.show_active();shot.run_ocr()
done=QSignalSpy(shot.ocr_job.layoutReady);failed=QSignalSpy(shot.ocr_job.failed)
assert done.wait(60000) and not failed, list(failed)
text=shot.selection.all_text
assert '12345' in text and 'Hello world' in text and '繁體中文' in text,text
shot.selection.select_all();shot.copy_text()
assert QApplication.clipboard().text()==text
shot.set_toolbar_visible(True);shot.toolbar_timer.stop();shot.grab().save(str(out/'rapid-panel.png'))
report={'engine':'RapidOCR / PP-OCRv4','text':text,'lines':len(shot.selection.words),'local_selection_and_copy':True}
shot.close()
# Explicitly verify each no-key provider through the real Qt network adapter.
for provider in ['google','microsoft']:
 job=TranslationJob(get_config(settings,provider),'Hello world')
 success,errors=QSignalSpy(job.finished),QSignalSpy(job.failed)
 job.start()
 assert success.wait(60000) and not errors,list(errors)
 report[provider]=success[0][0];job.deleteLater()
(out/'rapid-and-free-api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))

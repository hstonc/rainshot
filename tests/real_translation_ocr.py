"""Real Tesseract -> local HTTP fixture -> positioned image result. No cloud requests."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QImage, QPainter, QColor, QFont
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest
from rainshot.floating import FloatingShot

out=Path(sys.argv[1]); out.mkdir(parents=True,exist_ok=True)
requests=[]
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
        self.wfile.write(json.dumps({'translatedText':'本機 API 測試回應 12345'}).encode())
    def log_message(self,*args): pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
app=QApplication([])
settings=QSettings(str(out/'pipeline.ini'),QSettings.IniFormat)
settings.setValue('ocr/engine','tesseract')
settings.setValue('translation/provider','libre')
settings.setValue('translation/libre/endpoint',f'http://127.0.0.1:{server.server_address[1]}/translate')
image=QImage(900,260,QImage.Format_ARGB32); image.fill(QColor('white'))
p=QPainter(image); p.setPen(QColor('#203b37')); p.setFont(QFont('Noto Sans',28)); p.drawText(40,100,'rainshot screenshot test 12345'); p.drawText(40,175,'Select text and translate.'); p.end()
shot=FloatingShot(image,pinned=True,settings=settings)
try:
    shot.show_active(); shot.run_translation()
    assert shot.translate_after_ocr
    for _ in range(600):
        app.processEvents(); QTest.qWait(50)
        if shot.translation_job and shot.translation_job.done: break
    assert len(requests)>=2, shot.status.text()
    expected='\n'.join(['本機 API 測試回應 12345']*len(requests))
    assert shot.translation_output.toPlainText()==expected, shot.status.text()
    assert '12345' in requests[0]['q'] and 'rainshot' in requests[0]['q']
    assert shot.selection and shot.ocr_job.temp is None
    shot.activateWindow(); app.processEvents()
    shot.surface.setFocus(); app.processEvents()
    QTest.keyClick(shot.surface, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(shot.surface, Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text()==expected
    assert shot.translation_image is not None and not shot.translation_output.isVisible()
    shot.set_toolbar_visible(True); app.processEvents()
    assert shot.tools.rect().contains(shot.translation_row.geometry())
    assert shot.render_image()!=shot.document.render()
    shot.grab().save(str(out/'translation-pipeline.png'))
    report={'ocr':'real Tesseract with positioned text','request':'OCR text, no image payload',
            'service':'local HTTP fixture, NOT a live provider verification','result':'positioned translation and Ctrl+C verified','translated_lines':len(requests),
            'temporary_files':'cleaned'}
    (out/'translation-pipeline.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report))
finally:
    shot.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)

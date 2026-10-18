import json
import os
import sys
import tempfile
import time
from pathlib import Path
from PyQt5.QtCore import QProcess,QPoint
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest,QSignalSpy
from rainshot.snap import SnapProbe
out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
temp=tempfile.TemporaryDirectory(prefix='rainshot-atspi-test-')
for key,suffix in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime')]:
 os.environ[key]=str(Path(temp.name)/suffix);Path(os.environ[key]).mkdir(mode=0o700)
import subprocess, ast
address = ast.literal_eval(subprocess.check_output(['gdbus','call','--session','--dest','org.a11y.Bus','--object-path','/org/a11y/bus','--method','org.a11y.Bus.GetAddress'],text=True).strip())[0]
os.environ['AT_SPI_BUS_ADDRESS'] = address
app=QApplication([])
process=QProcess();process.start(sys.executable,[str(Path(__file__).with_name('accessible_target.py'))])
try:
 end=time.monotonic()+6
 while process.bytesAvailable()==0 and time.monotonic()<end: QTest.qWait(50)
 data=json.loads(bytes(process.readAllStandardOutput()).splitlines()[0])
 point=QPoint(data['x']+20,data['y']+10)
 probe=SnapProbe();window=probe.window_at(point)
 assert window and window['pid']==data['pid'],(window,data)
 done=QSignalSpy(probe.ready);probe.request(point)
 assert done.wait(2000) and done[0][0],(list(done),bytes(probe.process.readAllStandardError()).decode())
 rects=done[0][0]
 assert any(r.width()<500 and r.height()<100 and r.contains(point) for r in rects),rects
 report={'pid_matched':True,'element_bounds':[[r.x(),r.y(),r.width(),r.height()] for r in rects]}
 (out/'accessibility.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
 probe.cancel()
finally:
 process.kill();process.waitForFinished(1000)

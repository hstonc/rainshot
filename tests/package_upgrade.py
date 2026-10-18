"""Run with fakeroot; exercise dpkg upgrades in an isolated installation root."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
old, new, report = [Path(arg).resolve() for arg in sys.argv[1:4]]
with tempfile.TemporaryDirectory(prefix='rainshot-upgrade-') as temp:
    root=Path(temp)
    (root/'var/lib/dpkg').mkdir(parents=True)
    (root/'var/lib/dpkg/status').touch()
    def install(package):
        result=subprocess.run(['dpkg','--root='+str(root),'--log='+str(root/'dpkg.log'),
            '--force-depends','--install',str(package)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    install(old)
    assert (root/'usr/bin/qingshot').is_symlink()
    install(new)
    assert not (root/'usr/bin/qingshot').exists() and not (root/'usr/bin/qingshot').is_symlink()
    assert (root/'usr/bin/rainshot').is_file()
    assert 'Version: 0.4.7' in (root/'var/lib/dpkg/status').read_text()
    for path in (root/'usr').rglob('*'):
        assert 'qingshot' not in path.name.lower()
    result={'isolated_dpkg_upgrade':'0.4.0 → 0.4.7','legacy_alias_removed':True,'current_launcher_preserved':True}
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))

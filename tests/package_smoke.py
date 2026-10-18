"""Test the extracted package, with a cwd that cannot import the source checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

base, sample, report_path = (Path(p).resolve() for p in sys.argv[1:4])
launcher = base / "usr/bin/rainshot"
with tempfile.TemporaryDirectory(prefix="rainshot-package-") as temp:
    runtime = Path(temp) / "runtime"
    runtime.mkdir(mode=0o700)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(Path(temp) / "config"), XDG_CACHE_HOME=str(Path(temp) / "cache"))
    env.pop("PYTHONPATH", None)
    version = subprocess.check_output([str(launcher), "--version"], env=env, cwd=temp, text=True).strip()
    assert version == "0.4.7"
    primary = subprocess.Popen([str(launcher), "--tray"], env=env, cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        lock = runtime / ("rainshot-" + str(os.getuid())) / "instance.lock"
        for _ in range(50):
            if lock.exists():
                break
            if primary.poll() is not None:
                raise RuntimeError(primary.stderr.read())
            time.sleep(.05)
        commands = [["--settings"], ["--history"], ["--open", str(sample)]] + [["--tray"]] * 12 + [["--close-all"]]
        for command in commands:
            result = subprocess.run([str(launcher)] + command, env=env, cwd=temp, capture_output=True, text=True, timeout=5)
            assert result.returncode == 0, result.stderr
        time.sleep(2.4)
        assert primary.poll() is None
        result = subprocess.run([str(launcher), "--quit"], env=env, cwd=temp, capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        primary.wait(timeout=5)
        assert primary.returncode == 0
        error = primary.stderr.read()
        assert "RuntimeError" not in error and "Traceback" not in error, error
        report = {"version": version, "background_start": "passed", "open_via_ipc": "passed", "settings_and_history_ipc": "passed",
                  "connection_count": len(commands), "after_disconnect_wait_seconds": 2.4,
                  "close_all_and_quit": "passed", "deleted_socket_error": "none"}
        report_path.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        if primary.poll() is None:
            primary.terminate()
            primary.wait(timeout=5)

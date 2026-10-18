#!/usr/bin/env python3
"""Build an architecture-independent Debian package without root or downloads."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from common import VERSION, install_tree

ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rainshot-deb-") as temp:
        stage = Path(temp)
        install_tree(stage)
        control = stage / "DEBIAN/control"
        control.parent.mkdir()
        installed_size = sum(p.stat().st_size for p in (stage / "usr").rglob("*") if p.is_file()) // 1024 + 1
        control.write_text(f"""Package: rainshot
Version: {VERSION}
Section: graphics
Priority: optional
Architecture: all
Maintainer: rainshot contributors <23431385+hstonc@users.noreply.github.com>
Homepage: https://github.com/hstonc/rainshot
Depends: python3 (>= 3.10), python3-pyqt5, python3-pyqt5.qtsvg, python3-numpy, libqt5svg5, qt5-image-formats-plugins, qtwayland5, libx11-6, libxi6, libxtst6, libzbar0, python3-opencv, python3-pyatspi, ffmpeg
Recommends: xdg-desktop-portal, libnotify-bin, tesseract-ocr, tesseract-ocr-chi-sim, tesseract-ocr-chi-tra, tesseract-ocr-eng
Installed-Size: {installed_size}
Description: Linux-native screenshot, annotation and offline image tools
 Region capture on X11, portal capture on Wayland, annotations, pinning,
 continuous vertical stitching, local QR and OCR, translation, GIF/WebP recording.
""")
        out = destination / f"rainshot_{VERSION}_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(out)], check=True)
        return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", nargs="?", default="dist")
    print(build(parser.parse_args().destination))

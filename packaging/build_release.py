#!/usr/bin/env python3
"""Build public source and checksum-pinned Arch recipes; optionally Debian."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import shutil
import tarfile
from common import ROOT, VERSION, source_files

ARCH_DEPENDENCIES = ('python>=3.10', 'python-pyqt5', 'python-numpy', 'python-opencv',
                     'python-atspi', 'qt5-svg', 'qt5-imageformats', 'qt5-wayland', 'libx11', 'libxi', 'libxtst', 'zbar', 'ffmpeg')
ARCH_OPTIONAL = ('tesseract: local OCR', 'tesseract-data-eng: English OCR',
                 'tesseract-data-chi_sim: Simplified Chinese OCR',
                 'tesseract-data-chi_tra: Traditional Chinese OCR',
                 'xdg-desktop-portal: Wayland screenshot portal')


def archive(destination, entries):
    """Deterministic gzip/tar metadata; executable source entry points retained."""
    with open(destination, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as tar:
                for name, data, executable in sorted(entries):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), 0o755 if executable else 0o644
                    info.mtime = info.uid = info.gid = 0
                    tar.addfile(info, io.BytesIO(data))


def build_source(destination, root=ROOT):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    out = destination / f'rainshot-{VERSION}-source.tar.gz'
    archive(out, [(f'rainshot-{VERSION}/' + str(path.relative_to(root)), path.read_bytes(),
                   path.name == 'run.sh') for path in source_files(root)])
    return out


def build_arch(destination, source):
    destination, source = Path(destination), Path(source)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    recipe = (ROOT / 'packaging/arch/PKGBUILD.in').read_text().replace('@VERSION@', VERSION).replace('@SHA256@', checksum)
    folder = destination / 'arch-build'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'PKGBUILD').write_text(recipe)
    info = ['pkgbase = rainshot', 'pkgdesc = Linux screenshot, floating annotation and local OCR tools',
            f'pkgver = {VERSION}', 'pkgrel = 1', 'url = https://github.com/hstonc/rainshot',
            'arch = any', 'license = GPL-3.0-or-later']
    info += ['depends = ' + value for value in ARCH_DEPENDENCIES]
    info += ['optdepends = ' + value for value in ARCH_OPTIONAL]
    info += [f'source = {source.name}::https://github.com/hstonc/rainshot/releases/download/v{VERSION}/{source.name}',
             'sha256sums = ' + checksum, '', 'pkgname = rainshot']
    (folder / '.SRCINFO').write_text('\n'.join(info) + '\n')
    shutil.copyfile(source, folder / source.name)
    out = destination / f'rainshot-{VERSION}-arch-build.tar.gz'
    archive(out, [(f'rainshot-{VERSION}-arch-build/' + name,
                   (folder / name).read_bytes(), False) for name in ('PKGBUILD', '.SRCINFO')])
    return out


def checksums(destination):
    destination = Path(destination)
    files = sorted(path for path in destination.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    (destination / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in files))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', nargs='?', default='dist')
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    out = Path(args.destination).resolve()
    source = build_source(out)
    print(source)
    print(build_arch(out, source))
    if not args.source_only:
        from build_deb import build
        print(build(out))
    checksums(out)

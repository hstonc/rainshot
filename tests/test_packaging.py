"""Public packages preserve notices and avoid local desktop QA data."""
import hashlib
import importlib
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def packagers(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'packaging'))
    return importlib.import_module('common'), importlib.import_module('build_release')


def test_public_source_is_reproducible_and_excludes_local_qa(packagers, tmp_path):
    common, release = packagers
    root = tmp_path / 'source'
    for name, content in {
        'README.md': b'public', 'LICENSE': b'license', 'NOTICE': b'notice',
        'run.sh': b'#!/bin/sh\n', 'rainshot/module.py': b'# application\n',
        'docs/COMPATIBILITY.md': b'compatibility', 'docs/assets/demo.png': b'public demo',
        'docs/private-shot.png': b'PRIVATE', 'docs/report.json': b'PRIVATE',
        '.env': b'PRIVATE', 'rainshot/__pycache__/module.pyc': b'PRIVATE',
        'packaging/build/cache.py': b'PRIVATE',
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    first = release.build_source(tmp_path / 'first', root)
    second = release.build_source(tmp_path / 'second', root)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        names = archive.getnames()
        assert any(name.endswith('/NOTICE') for name in names)
        assert any(name.endswith('/docs/assets/demo.png') for name in names)
        assert not any('private-shot' in name or 'report.json' in name or '.env' in name
                       or '__pycache__' in name or '/build/' in name for name in names)
        assert archive.getmember(f'rainshot-{common.VERSION}/run.sh').mode == 0o755
        assert all(b'PRIVATE' not in archive.extractfile(name).read() for name in names)


def test_staged_launcher_works_outside_checkout_and_preserves_licenses(packagers, tmp_path):
    common, _ = packagers
    stage = common.install_tree(tmp_path / 'stage', '/usr/local')
    binary = stage / 'bin/rainshot'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env.pop('PYTHONPATH', None)
    assert subprocess.check_output([str(binary), '--version'], cwd=tmp_path, env=env,
                                   text=True, timeout=10).strip() == common.VERSION
    assert (stage / 'share/doc/rainshot/NOTICE').read_bytes() == (ROOT / 'NOTICE').read_bytes()
    assert (stage / 'share/licenses/rainshot/LICENSE').read_bytes() == (ROOT / 'LICENSE').read_bytes()
    assert not list((stage / 'share/doc/rainshot/docs').glob('*.json'))
    assert not list((stage / 'share/doc/rainshot/docs').glob('*.png'))
    assert (stage / 'share/applications/io.github.rainshot.rainshot.desktop').is_file()
    with pytest.raises(ValueError):
        common.install_tree('/', '/usr')


def test_arch_recipe_verifies_the_exact_released_source(packagers, tmp_path):
    common, release = packagers
    source = release.build_source(tmp_path)
    recipe = release.build_arch(tmp_path, source)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    pkgbuild = (tmp_path / 'arch-build/PKGBUILD').read_text()
    info = (tmp_path / 'arch-build/.SRCINFO').read_text()
    assert checksum in pkgbuild and 'sha256sums = ' + checksum in info
    assert 'SKIP' not in pkgbuild and '@VERSION@' not in pkgbuild and '@SHA256@' not in pkgbuild
    assert (tmp_path / 'arch-build' / source.name).read_bytes() == source.read_bytes()
    subprocess.run(['bash', '-n', str(tmp_path / 'arch-build/PKGBUILD')], check=True)
    for dependency in release.ARCH_DEPENDENCIES:
        assert dependency in pkgbuild and 'depends = ' + dependency in info
    with tarfile.open(recipe) as archive:
        assert len(archive.getmembers()) == 2
        assert all(member.name.endswith(('PKGBUILD', '.SRCINFO')) for member in archive.getmembers())

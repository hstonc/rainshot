"""Shared public-file policy and native distro package layout."""
import ast
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
VERSION = next(node.value.value for node in ast.parse((ROOT / 'rainshot/__init__.py').read_text()).body
               if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets))


def source_files(root=ROOT):
    """Exclude local QA captures, caches, build products and credentials."""
    paths = [root / name for name in ('README.md', 'LICENSE', 'NOTICE', 'pyproject.toml', 'run.sh', '.gitignore')]
    for directory in ('rainshot', 'tests', 'packaging', '.github'):
        for path in (root / directory).rglob('*'):
            relative = path.relative_to(root / directory)
            if (not path.is_file() or path.is_symlink()
                    or any(part in {'__pycache__', '.pytest_cache', 'dist', 'build', '.venv'} for part in relative.parts)
                    or path.suffix in {'.pyc', '.pyo', '.deb', '.rpm'}):
                continue
            paths.append(path)
    paths.extend((root / 'docs').glob('*.md'))
    if (root / 'docs/assets').is_dir():
        paths.extend(path for path in (root / 'docs/assets').rglob('*')
                     if path.is_file() and not path.is_symlink() and path.suffix in {'.png', '.svg', '.webp'})
    return sorted(set(path for path in paths if path.is_file() and not path.is_symlink()))


def install_tree(destination, prefix='/usr', root=ROOT):
    """Stage modules, desktop integration, license and public documentation."""
    destination = Path(destination).resolve()
    prefix_path = Path(prefix)
    if not prefix_path.is_absolute() or '..' in prefix_path.parts:
        raise ValueError('prefix must be an absolute path without ..')
    if destination == Path('/'):
        raise ValueError('Use a staging directory, not the live filesystem root.')
    stage = destination / str(prefix_path).lstrip('/')
    app = stage / 'lib/rainshot/rainshot'
    shutil.copytree(root / 'rainshot', app, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    binary = stage / 'bin/rainshot'
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text('#!/bin/sh\nset -eu\n'
                      'RAINSHOT_LIB=$(CDPATH= cd -- "$(dirname -- "$0")/../lib/rainshot" && pwd)\n'
                      'export PYTHONPATH="$RAINSHOT_LIB${PYTHONPATH:+:$PYTHONPATH}"\n'
                      'exec /usr/bin/python3 -m rainshot "$@"\n')
    binary.chmod(0o755)
    for source, target in (
        ('packaging/io.github.rainshot.rainshot.desktop', 'share/applications/io.github.rainshot.rainshot.desktop'),
        ('rainshot/icon.svg', 'share/icons/hicolor/scalable/apps/io.github.rainshot.rainshot.svg'),
        ('README.md', 'share/doc/rainshot/README.md'), ('NOTICE', 'share/doc/rainshot/NOTICE'),
        ('LICENSE', 'share/doc/rainshot/copyright'), ('LICENSE', 'share/licenses/rainshot/LICENSE'),
    ):
        target = stage / target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / source, target)
        target.chmod(0o644)
    for path in source_files(root):
        relative = path.relative_to(root)
        if relative.parts[0] == 'docs':
            target = stage / 'share/doc/rainshot' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(0o644)
    for path in app.rglob('*'):
        if path.is_file():
            path.chmod(0o644)
    return stage

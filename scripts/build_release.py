"""Build a self-contained skill ZIP from an explicit public-file allowlist."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contest_daily import __version__


def copy_runtime(target):
    package = target/'contest_daily'
    package.mkdir(parents=True, exist_ok=True)
    for source in (ROOT/'contest_daily').glob('*.py'):
        shutil.copyfile(source, package/source.name)
    for directory in ('assets', 'presets'):
        (target/directory).mkdir(exist_ok=True)
        for source in (ROOT/directory).iterdir():
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, target/directory/source.name)
    for name in ('requirements.txt', '.env.example'):
        shutil.copyfile(ROOT/name, target/name)


def build(output=None):
    output = Path(output or ROOT/'dist'/f'competitor-daily-v{__version__}.zip').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='competitor-skill-') as directory:
        stage = Path(directory)
        skill = ROOT/'skills/competitor-daily'
        for name in ('SKILL.md',): shutil.copyfile(skill/name, stage/name)
        for name in ('agents', 'assets', 'scripts', 'references'):
            shutil.copytree(skill/name, stage/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        license_path = ROOT/'LICENSE' if (ROOT/'LICENSE').is_file() else ROOT/'open-source/LICENSE'
        shutil.copyfile(license_path, stage/'LICENSE')
        copy_runtime(stage/'runtime')
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(stage.rglob('*')):
                if not path.is_file(): continue
                relative = path.relative_to(stage)
                if path.is_symlink() or any(part in ('.env', '.git', 'data', 'tmp', '__pycache__') for part in relative.parts):
                    raise ValueError('发行包中出现非公开运行文件：'+str(relative))
                archive.write(path, relative.as_posix())
    manifest = {'version':__version__, 'filename':output.name, 'bytes':output.stat().st_size,
                'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
    output.with_suffix('.sha256').write_text(manifest['sha256']+'  '+output.name+'\n', encoding='ascii')
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))

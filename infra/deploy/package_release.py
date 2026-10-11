#!/usr/bin/env python3
"""Package exact CI images and runtime files; never includes checkout credentials or .env."""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--sha', required=True)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.sha):
        parser.error('expected full commit SHA')
    root = Path(__file__).resolve().parents[2]
    paths = [root / 'compose.production.yml']
    for directory in ['infra/nginx', 'infra/deploy', 'data', 'docs/validation']:
        paths.extend(p for p in (root / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    # Metadata creation cannot migrate an existing schema. Refuse silent schema changes during CD.
    schema_files = sorted((root / 'backend/app').rglob('models.py'))
    schema_files += sorted((root / 'backend/alembic').rglob('*.py'))
    schema_files += [root / 'backend/app/shared/enums.py', root / 'backend/app/core/db.py']
    schema = hashlib.sha256()
    for path in schema_files:
        schema.update(path.relative_to(root).as_posix().encode())
        schema.update(path.read_bytes())
    files = {p.relative_to(root).as_posix(): p for p in paths}
    for component in ['backend', 'frontend']:
        path = args.images / f'{component}.tar.gz'
        if not path.is_file():
            parser.error(f'missing {path}')
        files[f'images/{path.name}'] = path
    manifest = {'sha': args.sha, 'schema': schema.hexdigest(), 'files': {name: digest(p) for name, p in files.items()}}
    import io
    payload = json.dumps(manifest, indent=2).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w') as archive:
        info = tarfile.TarInfo('manifest.json')
        info.size = len(payload)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(payload))
        for name, path in files.items():
            archive.add(path, arcname=name, recursive=False)


if __name__ == '__main__':
    main()

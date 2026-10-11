#!/usr/bin/env python3
"""Forced SSH command: accept one checksummed release on stdin, then deploy only the FSP project."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path('/home/fedya/fsp-platform')
MAX_BYTES = 2_500_000_000


def validate(archive: tarfile.TarFile) -> dict:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)) or len(names) > 5000:
        raise ValueError('duplicate or excessive archive entries')
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not member.isfile():
            raise ValueError('only regular files with safe relative paths are accepted')
        if member.name != 'manifest.json' and member.name != 'compose.production.yml' and not any(
            member.name.startswith(prefix) for prefix in ['infra/', 'data/', 'docs/validation/', 'images/']
        ):
            raise ValueError('unexpected runtime path')
        total += member.size
    if total > MAX_BYTES:
        raise ValueError('unpacked release too large')
    manifest_member = archive.getmember('manifest.json')
    if manifest_member.size > 1_000_000:
        raise ValueError('manifest too large')
    manifest = json.load(archive.extractfile(manifest_member))
    if not re.fullmatch(r'[0-9a-f]{40}', manifest.get('sha', '')):
        raise ValueError('invalid commit SHA')
    if not re.fullmatch(r'[0-9a-f]{64}', manifest.get('schema', '')):
        raise ValueError('invalid schema fingerprint')
    if set(manifest['files']) != set(names) - {'manifest.json'}:
        raise ValueError('manifest does not cover archive')
    required = {'compose.production.yml', 'infra/deploy/Caddyfile', 'infra/nginx/default.conf',
                'images/backend.tar.gz', 'images/frontend.tar.gz'}
    if not required <= set(names):
        raise ValueError('incomplete release')
    for member in members:
        if member.name == 'manifest.json':
            continue
        with archive.extractfile(member) as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != manifest['files'][member.name]:
            raise ValueError(f'checksum mismatch: {member.name}')
    return manifest


def main() -> None:
    os.umask(0o077)
    (ROOT / 'incoming').mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'incoming') as incoming:
        incoming = Path(incoming)
        bundle = incoming / 'release.tar'
        count = 0
        with bundle.open('wb') as target:
            while chunk := sys.stdin.buffer.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_BYTES:
                    raise ValueError('release too large')
                target.write(chunk)
        with tarfile.open(bundle, 'r:') as archive:
            manifest = validate(archive)
            release = incoming / 'release'
            release.mkdir()
            # Explicit streaming extraction also works on Ubuntu's Python 3.12; no links are allowed.
            for member in archive.getmembers():
                target = release / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o644)
            release.chmod(0o755)
            for directory in release.rglob('*'):
                if directory.is_dir():
                    directory.chmod(0o755)
        subprocess.run(['bash', str(ROOT / 'bin/deploy.sh'), str(release), manifest['sha']], check=True)


if __name__ == '__main__':
    main()

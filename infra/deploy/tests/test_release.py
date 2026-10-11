import hashlib
import importlib.util
import io
import json
import tarfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('receiver', Path(__file__).parents[1] / 'receive_release.py')
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class ReleaseValidationTests(unittest.TestCase):
    def archive(self, *, corrupt=False, extra=None, duplicate=False):
        files = {name: b'contents' for name in ['compose.production.yml', 'infra/deploy/Caddyfile',
                 'infra/nginx/default.conf', 'images/backend.tar.gz', 'images/frontend.tar.gz']}
        manifest = {'sha': 'a' * 40, 'schema': 'b' * 64,
                    'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        if corrupt:
            files['images/backend.tar.gz'] = b'changed'
        files['manifest.json'] = json.dumps(manifest).encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name, data in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            if duplicate:
                entry = tarfile.TarInfo('manifest.json')
                archive.addfile(entry, io.BytesIO())
            if extra:
                archive.addfile(extra, io.BytesIO())
        buffer.seek(0)
        return tarfile.open(fileobj=buffer, mode='r:')

    def test_valid_release(self):
        with self.archive() as archive:
            self.assertEqual(receiver.validate(archive)['sha'], 'a' * 40)

    def test_corrupted_image_rejected(self):
        with self.archive(corrupt=True) as archive, self.assertRaisesRegex(ValueError, 'checksum'):
            receiver.validate(archive)

    def test_path_traversal_rejected(self):
        with self.archive(extra=tarfile.TarInfo('../shared/.env')) as archive, self.assertRaises(ValueError):
            receiver.validate(archive)

    def test_absolute_path_rejected(self):
        with self.archive(extra=tarfile.TarInfo('/home/fedya/.ssh/authorized_keys')) as archive, self.assertRaises(ValueError):
            receiver.validate(archive)

    def test_symlink_rejected(self):
        entry = tarfile.TarInfo('infra/link')
        entry.type = tarfile.SYMTYPE
        entry.linkname = '../../shared/.env'
        with self.archive(extra=entry) as archive, self.assertRaises(ValueError):
            receiver.validate(archive)

    def test_unlisted_file_rejected(self):
        with self.archive(extra=tarfile.TarInfo('infra/extra')) as archive, self.assertRaisesRegex(ValueError, 'cover'):
            receiver.validate(archive)

    def test_duplicate_rejected(self):
        with self.archive(duplicate=True) as archive, self.assertRaisesRegex(ValueError, 'duplicate'):
            receiver.validate(archive)


if __name__ == '__main__':
    unittest.main()

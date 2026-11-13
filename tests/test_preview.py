import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('preview', Path(__file__).resolve().parents[1] / 'scripts/preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewExport(unittest.TestCase):
    def dataset(self, root):
        (root / 'review').mkdir()
        rows = []
        for index in range(6):
            identifier = f'match-{index}'
            body = f'original-{index}'.encode()
            (root / f'{identifier}.mp4').write_bytes(body)
            metadata = dict(title=identifier, duration_s=12, source_size_bytes=len(body), source_sha256=hashlib.sha256(body).hexdigest(), algorithm_version='test', rallies=[], secret_path='/private/gt')
            (root / 'review' / f'{identifier}.json').write_text(json.dumps(metadata))
            rows.append({'id': identifier})
        (root / 'review/manifest.json').write_text(json.dumps({'videos': rows}))

    def test_export_publishes_only_verified_public_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.dataset(root)
            target = root / 'output'
            preview.export(root, target)
            manifest = (target / 'manifest.json').read_text()
            self.assertNotIn('secret_path', manifest)
            self.assertNotIn('/private', manifest)
            self.assertEqual(len(json.loads(manifest)['items']), 6)
            self.assertEqual(len(list(target.glob('*.mp4'))), 6)
            (root / 'match-0.mp4').write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                preview.export(root, target)
            self.assertEqual((target / 'manifest.json').read_text(), manifest)

    def test_unsafe_id_is_rejected_before_reading_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.dataset(root)
            (root / 'review/manifest.json').write_text(json.dumps({'videos': [{'id': '../private'}]}))
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                preview.export(root, root / 'output')

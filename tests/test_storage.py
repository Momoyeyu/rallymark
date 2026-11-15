import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "storage", Path(__file__).resolve().parents[1] / "scripts/storage.py"
)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


class StorageMountTests(unittest.TestCase):
    def test_named_volume_default_is_supported(self):
        with patch.dict(os.environ, {}, clear=True):
            storage.validate_mount()

    def test_missing_or_root_mount_is_rejected(self):
        for mount in ("/", "/definitely-missing-data-disk"):
            with patch.dict(os.environ, {"STORAGE_MOUNT": mount}, clear=True):
                with self.assertRaises(RuntimeError):
                    storage.validate_mount()

    def test_all_video_paths_must_be_on_expected_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "STORAGE_MOUNT": tmp,
                "MEDIA_STORAGE": tmp,
                "ALGORITHM_STORAGE": tmp,
                "PREVIEW_DATA_PATH": tmp,
            }
            with (
                patch.object(Path, "is_mount", return_value=True),
                patch.dict(os.environ, env, clear=True),
            ):
                storage.validate_mount()
                os.environ["MEDIA_STORAGE"] = "/another-filesystem"
                with self.assertRaises(RuntimeError):
                    storage.validate_mount()

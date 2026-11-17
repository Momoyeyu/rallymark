import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "gpu_selection", Path(__file__).resolve().parents[1] / "scripts/gpu_selection.py"
)
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)


class SelectionTests(unittest.TestCase):
    def test_resolve_uses_uuid_and_requested_order_with_count(self):
        data = "0, GPU-aaa, RTX 4080\n4, GPU-bbb, RTX 4090\n"
        self.assertEqual(gpu.resolve(data, "4,0", 1), ["GPU-bbb"])
        self.assertEqual(gpu.resolve(data, "all", 2), ["GPU-aaa", "GPU-bbb"])
        for value, count in [("9", 1), ("0,GPU-aaa", 0), ("4", 2)]:
            with self.assertRaises(ValueError):
                gpu.resolve(data, value, count)

    def test_invalid_selection_never_silently_uses_other_cards(self):
        for value, count in [
            ("all", 1),
            ("0,0", 1),
            ("", 0),
            ("1", -1),
            ("0;anything", 0),
        ]:
            with self.assertRaises(ValueError):
                gpu.selectors(value, count)

    def test_override_limits_container_and_worker_to_same_pool(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"GPU_DEVICE": "GPU-aaa,GPU-bbb", "GPU_COUNT": "1"},
            clear=True,
        ):
            result = gpu.override(Path(directory)).read_text()
            self.assertIn("devices: !override", result)
            self.assertIn("nvidia.com/gpu=GPU-aaa", result)
            self.assertIn("GPU_DEVICE: GPU-aaa", result)
            self.assertNotIn("GPU-bbb", result)

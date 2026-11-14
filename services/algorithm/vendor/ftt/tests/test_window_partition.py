import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "partition", Path(__file__).resolve().parents[1] / "code/window_partition.py"
)
partition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(partition)


class WindowPartitionTests(unittest.TestCase):
    def test_global_windows_are_preserved_once_in_order(self):
        windows = [(x * 384, x * 384 + 768) for x in range(33)]
        for count in range(1, 9):
            shards = [partition.select_windows(windows, i, count) for i in range(count)]
            self.assertEqual([w for shard in shards for w in shard], windows)
            self.assertLessEqual(max(map(len, shards)) - min(map(len, shards)), 1)

    def test_invalid_and_empty_partitions_are_rejected(self):
        for index, count in [(-1, 2), (2, 2), (0, 0), (0, 3)]:
            with self.assertRaises(ValueError):
                partition.select_windows([(0, 768), (384, 1152)], index, count)

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from window_decode import ordered_prefetch


class OrderedDecode(unittest.TestCase):
    def test_preserves_order_and_values(self):
        self.assertEqual(
            list(ordered_prefetch(range(7), lambda i: i * i, workers=2, depth=3)),
            [(i, i * i) for i in range(7)],
        )

    def test_failures_propagate(self):
        def decode(i):
            if i == 2:
                raise ValueError("bad frame")
            return i

        with self.assertRaises(ValueError):
            list(ordered_prefetch(range(5), decode, 2, 2))

    def test_rejects_unbounded_queue(self):
        with self.assertRaises(ValueError):
            list(ordered_prefetch([1], lambda x: x, 1, 9))

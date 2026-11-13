"""The durable problem-set judge; expected examples are checked-in strict JSON."""

import copy
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from ftt_score_rules import filter_scores  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures/score_postprocess"


def restore(value):
    if value == {"invalid_number": "nan"}:
        return math.nan
    if isinstance(value, list):
        return [restore(v) for v in value]
    if isinstance(value, dict):
        return {k: restore(v) for k, v in value.items()}
    return value


class ScoreProblemCases(unittest.TestCase):
    def test_examples(self):
        paths = sorted(FIXTURES.glob("*.json"))
        self.assertGreaterEqual(len(paths), 29)
        for path in paths:
            c = json.loads(path.read_text())
            data = restore(c["input"])
            before = copy.deepcopy(data)
            with self.subTest(case=c["id"], reason=c["reason"]):
                if c["expected_error"]:
                    with self.assertRaises(ValueError):
                        filter_scores(
                            data["rallies"], data["ocr_rows"], **data["parameters"]
                        )
                    continue
                result = filter_scores(
                    data["rallies"], data["ocr_rows"], **data["parameters"]
                )
                actual = [
                    {
                        k: r[k]
                        for k in ["start_s", "end_s", "score_label", "score_status"]
                    }
                    for r in result["rallies"]
                ]
                self.assertEqual(actual, c["expected"])
                self.assertEqual(
                    data, before, "Inference must not mutate input metadata"
                )
                ids = [i for r in result["rallies"] for i in r["original_indices"]] + [
                    i for r in result["discarded"] for i in r["original_indices"]
                ]
                self.assertEqual(
                    sorted(ids),
                    list(range(1, len(data["rallies"]) + 1)),
                    "Every input is retained, merged or explicitly discarded exactly once",
                )

    def test_fragment_audit_grows_linearly_not_with_accumulated_members(self):
        n = 200
        rows = [dict(start_s=0, end_s=1, score=0.99, tad_indices=[1], ocr_indices=[1])]
        rows += [
            dict(
                start_s=1 + i * 0.2,
                end_s=1.1 + i * 0.2,
                score=0.5,
                tad_indices=[i + 1],
                ocr_indices=[],
            )
            for i in range(1, n)
        ]
        ocr = [
            dict(start_s=0, end_s=1, score=0.99, pre_score=[0, 0], post_score=[1, 0])
        ]
        result = filter_scores(rows, ocr, fragment_gap_s=0.2, edge_window_s=0)
        self.assertEqual(len(result["rallies"]), 1)
        self.assertLess(
            sum(len(m.get("into", [])) for m in result["merged_fragments"]), 2 * n
        )

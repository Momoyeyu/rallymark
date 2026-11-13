"""Independent small-state oracle: enumerate actual legal winner sequences."""

import copy
import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from ftt_score_rules import _infer, filter_scores  # noqa: E402


def playable(a, b):
    return max(a, b) < 11 or abs(a - b) < 2


def paths(start, target):
    steps = sum(target) - sum(start)
    answer = []
    for winners in itertools.product((0, 1), repeat=steps):
        state = list(start)
        sequence = []
        for side in winners:
            if not playable(*state):
                break
            sequence.append(tuple(state))
            state[side] += 1
        else:
            if tuple(state) == target:
                answer.append(sequence)
    return answer


class ScoreOracleTests(unittest.TestCase):
    def test_interpolation_matches_exhaustive_winner_sequences(self):
        checked = 0
        for start in [(0, 0), (8, 8), (9, 10), (10, 10), (11, 10), (11, 11)]:
            for da, db in itertools.product(range(5), repeat=2):
                target = (start[0] + da, start[1] + db)
                if not playable(*target):
                    continue
                possible = paths(start, target)
                if not possible:
                    continue
                rows = [
                    dict(score_label=None, score_status="unknown")
                    for _ in range(da + db)
                ]
                _infer(rows, start, target)
                for i, row in enumerate(rows):
                    values = {p[i] for p in possible}
                    expected = (
                        f"{next(iter(values))[0]}:{next(iter(values))[1]}"
                        if len(values) == 1
                        else None
                    )
                    self.assertEqual(row["score_label"], expected, (start, target, i))
                checked += 1
        self.assertGreater(checked, 50)

    def test_random_complete_scoreboards_remove_only_inserted_false_candidates(self):
        rng = random.Random(20261113)
        for _ in range(200):
            state = [0, 0]
            rows = []
            ocr = []
            expected = []
            for i in range(rng.randint(3, 10)):
                a = 10 + i * 20
                b = a + 4
                side = rng.randrange(2)
                after = state.copy()
                after[side] += 1
                ocr.append(
                    dict(
                        start_s=a,
                        end_s=b,
                        score=0.99,
                        pre_score=state.copy(),
                        post_score=after.copy(),
                    )
                )
                rows.append(
                    dict(
                        start_s=a,
                        end_s=b,
                        score=0.99,
                        ocr_indices=[i + 1],
                        tad_indices=[2 * i + 1],
                    )
                )
                expected.append((a, b, f"{state[0]}:{state[1]}"))
                if i:
                    rows.insert(
                        -1,
                        dict(
                            start_s=a - 10,
                            end_s=a - 8,
                            score=0.9,
                            tad_indices=[2 * i],
                            ocr_indices=[],
                        ),
                    )
                state = after
            before = copy.deepcopy(rows)
            result = filter_scores(rows, ocr, fragment_gap_s=0, edge_window_s=0)
            self.assertEqual(
                [
                    (r["start_s"], r["end_s"], r["score_label"])
                    for r in result["rallies"]
                ],
                expected,
            )
            self.assertEqual(rows, before)

    def test_large_deuce_scores_need_no_enumeration(self):
        start = 10**9
        rows = [dict(score_label=None, score_status="unknown") for _ in range(10000)]
        _infer(rows, (start, start), (start + 5000, start + 5000))
        for i, row in enumerate(rows):
            expected = f"{start + i // 2}:{start + i // 2}" if i % 2 == 0 else None
            self.assertEqual(row["score_label"], expected)

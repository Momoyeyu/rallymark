import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "evaluate_grid.py"
spec = importlib.util.spec_from_file_location("evaluate_grid", SCRIPT)
eval_grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_grid)


def rows(*bounds):
    return [{"start_s": a, "end_s": b} for a, b in bounds]


def test_exact_and_partial_continuous_seconds():
    exact = eval_grid.evaluate(rows((1, 11)), rows((1, 11)))
    assert exact["duration_f2"] == 1
    part = eval_grid.evaluate(rows((1, 11)), rows((6, 16)))
    assert (part["duration_tp_s"], part["duration_fp_s"], part["duration_fn_s"]) == (
        5,
        5,
        5,
    )
    assert part["duration_f1"] == 0.5
    assert part["event_03_tp"] == 1
    assert part["event_05_tp"] == 0
    assert part["coverage_05_recall"] == 1


def test_split_and_overmerge_do_not_claim_perfect_event_recall():
    split = eval_grid.evaluate(rows((0, 10)), rows((0, 5), (5, 10)))
    assert split["duration_recall"] == 1
    assert split["event_05_recall"] == 1
    assert split["event_05_precision"] == 0.5
    merged = eval_grid.evaluate(rows((0, 10), (12, 22)), rows((0, 22)))
    assert merged["coverage_05_recall"] == 1
    assert merged["event_03_recall"] == 0.5
    assert merged["event_05_recall"] == 0
    assert merged["event_05_missed_rounds"] == 2


def test_duration_union_avoids_double_counting():
    value = eval_grid.evaluate(rows((0, 10)), rows((0, 7), (3, 10)))
    assert value["duration_tp_s"] == 10
    assert value["duration_fp_s"] == 0
    assert value["duration_f1"] == 1


def test_empty_conventions():
    assert eval_grid.evaluate([], [])["event_05_f1"] == 1
    assert eval_grid.evaluate(rows((0, 1)), [])["duration_recall"] == 0
    assert eval_grid.evaluate([], rows((0, 1)))["event_05_precision"] == 0


def test_matching_uses_augmenting_paths():
    # First prediction can match either GT, second only the first.
    pairs = eval_grid.maximum_matching([[0, 1], [0]], 2)
    assert len(pairs) == 2
    assert len({p for p, _ in pairs}) == len({g for _, g in pairs}) == 2


def test_score_and_subsecond_manual_boundaries_ignored_as_labels():
    value = eval_grid.evaluate(
        [{"start_s": 1, "end_s": 4, "score": "2:3"}],
        [{"start_s": 1.25, "end_s": 4.25, "score": 0.9}],
    )
    assert value["duration_tp_s"] == 2.75
    assert value["event_05_tp"] == 1


def test_selection_does_not_use_held_out_video():
    records = [
        {
            "video_id": "a",
            "top_k": 30,
            "nearby_seconds": 1,
            "selection_f2": 0.9,
            "selection_f1": 0.8,
            "event_05_f1": 0.8,
            "coverage_05_recall": 0.8,
        },
        {
            "video_id": "a",
            "top_k": 31,
            "nearby_seconds": 1,
            "selection_f2": 0.8,
            "selection_f1": 0.7,
            "event_05_f1": 0.7,
            "coverage_05_recall": 0.7,
        },
        {
            "video_id": "b",
            "top_k": 30,
            "nearby_seconds": 1,
            "selection_f2": 0,
            "selection_f1": 0,
            "event_05_f1": 0,
            "coverage_05_recall": 0,
        },
        {
            "video_id": "b",
            "top_k": 31,
            "nearby_seconds": 1,
            "selection_f2": 1,
            "selection_f1": 1,
            "event_05_f1": 1,
            "coverage_05_recall": 1,
        },
    ]
    assert eval_grid.select_config(records, ["a"])["top_k"] == 30
    assert eval_grid.select_config(records, ["b"])["top_k"] == 31


@pytest.mark.parametrize("bounds", [(-1, 1), (1, 1), (2, 1), (0, float("nan"))])
def test_invalid_intervals_rejected(bounds):
    with pytest.raises(ValueError):
        eval_grid.evaluate(rows(bounds), [])


def test_best_f1_alternative_and_pareto_preserve_tradeoff():
    records = [
        {
            "video_id": "a",
            "top_k": 30,
            "nearby_seconds": 1,
            "selection_f2": 0.9,
            "selection_f1": 0.8,
            "selection_recall": 0.95,
            "selection_precision": 0.65,
        },
        {
            "video_id": "a",
            "top_k": 31,
            "nearby_seconds": 1,
            "selection_f2": 0.8,
            "selection_f1": 0.9,
            "selection_recall": 0.8,
            "selection_precision": 0.95,
        },
        {
            "video_id": "a",
            "top_k": 32,
            "nearby_seconds": 1,
            "selection_f2": 0.7,
            "selection_f1": 0.7,
            "selection_recall": 0.7,
            "selection_precision": 0.7,
        },
    ]
    assert (
        eval_grid.select_config(records, ["a"], primary="selection_f1")["top_k"] == 31
    )
    frontier = eval_grid.pareto_frontier(records, ["a"])
    assert {row["top_k"] for row in frontier} == {30, 31}


def test_recall_priority_respects_f1_floor_before_minimizing_misses():
    records = [
        {
            "video_id": "a",
            "top_k": 30,
            "nearby_seconds": 1,
            "selection_f1": 1,
            "coverage_05_missed_rounds": 2,
            "event_05_missed_rounds": 2,
            "duration_recall": 0.8,
        },
        {
            "video_id": "a",
            "top_k": 31,
            "nearby_seconds": 1,
            "selection_f1": 0.9,
            "coverage_05_missed_rounds": 1,
            "event_05_missed_rounds": 1,
            "duration_recall": 0.9,
        },
        {
            "video_id": "a",
            "top_k": 32,
            "nearby_seconds": 1,
            "selection_f1": 0.89,
            "coverage_05_missed_rounds": 0,
            "event_05_missed_rounds": 0,
            "duration_recall": 1,
        },
        {
            "video_id": "held",
            "top_k": 30,
            "nearby_seconds": 1,
            "selection_f1": 1,
            "coverage_05_missed_rounds": 0,
            "event_05_missed_rounds": 0,
            "duration_recall": 1,
        },
    ]
    assert eval_grid.select_recall_config(records, ["a"])["top_k"] == 31


def test_complete_miss_distinguishes_low_coverage_and_event_miss():
    value = eval_grid.evaluate(
        rows((0, 10), (20, 30), (40, 50)), rows((0, 1), (20, 29))
    )
    assert value["coverage_zero_missed_rounds"] == 1
    assert value["coverage_05_missed_rounds"] == 2
    assert value["event_05_missed_rounds"] == 2
    assert value["coverage_90_recall"] == pytest.approx(1 / 3)
    aggregated = eval_grid.aggregate([value, value])
    assert aggregated["pooled"]["coverage_zero_missed_rounds"] == 2
    assert aggregated["pooled"]["coverage_90"]["recall"] == pytest.approx(1 / 3)

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "search_extended", SCRIPTS / "search_extended.py"
)
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


def candidate(a, b, score):
    return {"start_s": a, "end_s": b, "score": score}


def test_unchanged_rule_matches_production_and_allows_longer_distance():
    tad = [
        candidate(2, 5, 0.9),
        candidate(4, 8, 0.8),
        candidate(12, 14, 0.7),
        candidate(25, 28, 0.6),
    ]
    ocr = [candidate(5, 7, 0.9)]
    prepared = search.prepare(search.POST, tad, ocr, 4)
    for gap in [1, 2, 5, 10]:
        result = search.fuse(*prepared, gap)
        original = search.POST.postprocess(tad, ocr, top_k=4, nearby_seconds=gap)
        assert result["rallies"] == original["rallies"]
        assert result["discarded_tad"] == original["discarded_tad"]
    assert len(search.fuse(*prepared, 30)["rallies"]) == 1
    with pytest.raises(ValueError):
        search.fuse(*prepared, -1)


def test_false_positives_never_outweigh_a_completely_missed_rally():
    safe = {
        "coverage_zero_missed_rounds": 0,
        "coverage_05_missed_rounds": 0,
        "event_03_fn": 0,
        "event_05_fn": 0,
        "event_03_fp": 100,
        "event_05_fp": 100,
        "duration_tp_s": 10,
        "selection_f1": 0.1,
    }
    missed = dict(
        safe,
        coverage_zero_missed_rounds=1,
        event_03_fp=0,
        event_05_fp=0,
        selection_f1=1,
    )
    assert search.rank([safe], (200, 2)) < search.rank([missed], (20, 10))


def test_selection_uses_only_training_video_rows():
    metrics = {
        "coverage_zero_missed_rounds": 0,
        "coverage_05_missed_rounds": 0,
        "event_03_fn": 0,
        "event_05_fn": 0,
        "event_03_fp": 1,
        "event_05_fp": 1,
        "duration_tp_s": 10,
        "selection_f1": 0.9,
    }
    records = [
        dict(video_id="a", top_k=1, nearby_seconds=5, **metrics),
        dict(video_id="a", top_k=2, nearby_seconds=5, **dict(metrics, event_03_fp=2)),
        dict(
            video_id="b",
            top_k=1,
            nearby_seconds=5,
            **dict(metrics, coverage_zero_missed_rounds=1),
        ),
        dict(video_id="b", top_k=2, nearby_seconds=5, **metrics),
    ]
    assert search.select(records, ["a"]) == {"top_k": 1, "nearby_seconds": 5}

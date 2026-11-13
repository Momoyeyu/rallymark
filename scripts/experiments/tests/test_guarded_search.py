import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "search_guarded", SCRIPTS / "search_guarded.py"
)
guarded = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guarded)


def row(a, b, score):
    return {"start_s": a, "end_s": b, "score": score}


def test_protection_retains_strong_orphan_under_longer_exclusion():
    initial, orphans = guarded.prepare(
        guarded.POST, [row(12, 15, 0.9), row(25, 25.2, 0.1)], [row(20, 24, 0.9)], 2
    )
    result = guarded.fuse_guarded(initial, orphans, 10, 0.5, {1})
    assert [(r["start_s"], r["end_s"]) for r in result["rallies"]] == [
        (12, 15),
        (20, 24),
    ]
    assert result["discarded_tad"][0]["drop_reason"] == "short_orphan"


def test_no_protection_or_duration_filter_equals_unchanged_rule():
    initial, orphans = guarded.prepare(
        guarded.POST, [row(12, 15, 0.9)], [row(20, 24, 0.9)], 1
    )
    assert (
        guarded.fuse_guarded(initial, orphans, 10, 0, set())["rallies"]
        == guarded.fuse(initial, orphans, 10)["rallies"]
    )


def test_dominance_detects_lost_true_content_even_if_total_coverage_is_equal():
    old_positive = [(0, 5)]
    shifted_prediction = [(5, 10)]
    assert guarded.previous_positive_loss(old_positive, shifted_prediction) == 5


def test_grid_reload_preserves_integer_candidate_counts():
    parsed = guarded.parse_grid_row(
        {
            "video_id": "nina",
            "top_k": "200",
            "protect_top_m": "100",
            "nearby_seconds": "10",
            "min_duration_s": "0.5",
        }
    )
    assert isinstance(parsed["top_k"], int)
    assert isinstance(parsed["protect_top_m"], int)
    assert parsed["video_id"] == "nina"

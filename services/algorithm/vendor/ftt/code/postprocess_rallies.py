#!/usr/bin/env python3
"""Fuse TAD proposals with OCR end times without reading ground truth."""

import argparse
import importlib.util
import json
import math
from functools import lru_cache
from pathlib import Path


def merge_intervals(intervals):
    """Merge overlapping or touching intervals, including transitive overlaps."""
    groups = []
    for item in sorted(intervals, key=lambda x: (x["start_s"], x["end_s"])):
        if groups and item["start_s"] <= groups[-1]["end_s"]:
            groups[-1]["end_s"] = max(groups[-1]["end_s"], item["end_s"])
            groups[-1]["members"].extend(item["members"])
        else:
            groups.append(
                {
                    "start_s": item["start_s"],
                    "end_s": item["end_s"],
                    "members": list(item["members"]),
                }
            )
    return groups


def prepare(rows, kind):
    intervals = []
    for index, row in enumerate(rows, 1):
        start, end, score = (row[key] for key in ("start_s", "end_s", "score"))
        if any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            for x in (start, end, score)
        ):
            raise ValueError("Interval times and score must be finite numbers")
        if start < 0 or end <= start or not 0 <= score <= 1:
            raise ValueError("Invalid interval bounds or score")
        member = dict(start_s=start, end_s=end, score=score, kind=kind, index=index)
        intervals.append(dict(start_s=start, end_s=end, members=[member]))
    return intervals


def summarize(group):
    tad = [row for row in group["members"] if row["kind"] == "tad"]
    ocr = [row for row in group["members"] if row["kind"] == "ocr"]
    return {
        "start_s": group["start_s"],
        "end_s": max(row["end_s"] for row in ocr) if ocr else group["end_s"],
        "score": max(row["score"] for row in group["members"]),
        "source": "tad_ocr" if tad and ocr else ("ocr_only" if ocr else "tad_only"),
        "tad_indices": sorted(row["index"] for row in tad),
        "ocr_indices": sorted(row["index"] for row in ocr),
        "tad_score": max((row["score"] for row in tad), default=None),
        "ocr_score": max((row["score"] for row in ocr), default=None),
    }


def distance(a, b):
    return max(0, a["start_s"] - b["end_s"], b["start_s"] - a["end_s"])


@lru_cache(maxsize=1)
def score_module():
    spec = importlib.util.spec_from_file_location(
        "ftt_score_constraints", Path(__file__).with_name("ftt_score_rules.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def postprocess(
    tad_rows,
    ocr_rows,
    threshold=0.10,
    nearby_seconds=5,
    *,
    top_k=None,
    protect_top_m=0,
    min_duration_s=0,
    score_filter=False,
    fragment_gap_s=1,
    score_confidence=0.8,
    edge_window_s=30,
    video_duration_s=None,
    score_observations=None,
):
    if (
        isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise ValueError("Threshold must be between 0 and 1")
    if (
        isinstance(nearby_seconds, bool)
        or not math.isfinite(nearby_seconds)
        or not 1 <= nearby_seconds <= 30
    ):
        raise ValueError("Nearby seconds must be between 1 and 30")
    if top_k is not None and (
        isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 200
    ):
        raise ValueError("Prediction count must be an integer between 1 and 200")
    if (
        isinstance(protect_top_m, bool)
        or not isinstance(protect_top_m, int)
        or not 0 <= protect_top_m <= 200
        or top_k is not None
        and protect_top_m > top_k
    ):
        raise ValueError("Protected count must be an integer in [0, Top-N]")
    if (
        isinstance(min_duration_s, bool)
        or not math.isfinite(min_duration_s)
        or not 0 <= min_duration_s <= 5
    ):
        raise ValueError("Minimum orphan duration must be in [0,5]")
    tad = prepare(tad_rows, "tad")
    ranking = sorted(
        tad,
        key=lambda item: (
            -item["members"][0]["score"],
            item["start_s"],
            item["end_s"],
            item["members"][0]["index"],
        ),
    )
    protected = {item["members"][0]["index"] for item in ranking[:protect_top_m]}
    ocr = prepare(ocr_rows, "ocr")
    if top_k is None:
        tad = [item for item in tad if item["members"][0]["score"] >= threshold]
    else:
        tad = sorted(
            tad,
            key=lambda item: (
                -item["members"][0]["score"],
                item["start_s"],
                item["end_s"],
                item["members"][0]["index"],
            ),
        )[:top_k]
    merged_tad = merge_intervals(tad)
    mixed = merge_intervals(merged_tad + ocr)
    legal = [
        summarize(group)
        for group in mixed
        if any(row["kind"] == "ocr" for row in group["members"])
    ]
    orphan_tad = [
        summarize(group)
        for group in mixed
        if all(row["kind"] == "tad" for row in group["members"])
    ]
    discarded = []
    # Newly accepted TAD intervals also become legal. Prefer the strongest
    # proposal when several orphan candidates occupy the same neighborhood.
    for candidate in sorted(
        orphan_tad, key=lambda x: (-x["score"], x["start_s"], x["end_s"])
    ):
        if candidate["end_s"] - candidate["start_s"] < min_duration_s:
            discarded.append(dict(candidate, drop_reason="short_orphan"))
            continue
        gap = min(
            (distance(candidate, interval) for interval in legal), default=math.inf
        )
        if gap <= nearby_seconds and not protected.intersection(
            candidate["tad_indices"]
        ):
            discarded.append(dict(candidate, nearest_legal_gap_s=gap))
        else:
            legal.append(candidate)
    result = {
        "parameters": {
            "tad_threshold": threshold if top_k is None else None,
            "top_k": top_k,
            "nearby_seconds": nearby_seconds,
            "protect_top_m": protect_top_m,
            "min_duration_s": min_duration_s,
            "score_filter": score_filter,
            "fragment_gap_s": fragment_gap_s,
            "score_confidence": score_confidence,
            "edge_window_s": edge_window_s,
        },
        "selected_tad": [item["members"][0] for item in tad],
        "rallies": sorted(legal, key=lambda x: (x["start_s"], x["end_s"])),
        "tad_merged": [summarize(group) for group in merged_tad],
        "discarded_tad": discarded,
    }

    if score_filter:
        result["rallies_before_scores"] = result["rallies"]
        filtered = score_module().filter_scores(
            result["rallies"],
            ocr_rows,
            fragment_gap_s=fragment_gap_s,
            confidence_min=score_confidence,
            edge_window_s=edge_window_s,
            video_duration_s=video_duration_s,
            score_observations=score_observations,
        )
        result["rallies"] = filtered.pop("rallies")
        result["score_constraints"] = filtered
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tad", type=Path, required=True)
    parser.add_argument("--ocr", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    select = parser.add_mutually_exclusive_group()
    select.add_argument("--top-k", type=int)
    select.add_argument("--threshold", type=float)
    for name in [
        "nearby-seconds",
        "min-duration-s",
        "fragment-gap-s",
        "score-confidence",
        "edge-window-s",
    ]:
        parser.add_argument("--" + name, type=float)
    parser.add_argument("--protect-top-m", type=int)
    parser.add_argument(
        "--score-filter", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--video-duration-s", type=float)
    args = parser.parse_args()
    allowed = {
        "top_k",
        "nearby_seconds",
        "protect_top_m",
        "min_duration_s",
        "score_filter",
        "fragment_gap_s",
        "score_confidence",
        "edge_window_s",
    }
    config = json.loads(args.config.read_text()) if args.config else {}
    if set(config) - allowed:
        parser.error(
            "Unknown postprocess configuration keys: " + str(set(config) - allowed)
        )
    config.setdefault("top_k", 200)
    for key in allowed:
        value = getattr(args, key, None)
        if value is not None:
            config[key] = value
    if args.threshold is not None:
        config.update(top_k=None, threshold=args.threshold)
    tad = json.loads(args.tad.read_text())
    ocr = json.loads(args.ocr.read_text())
    observations = args.ocr.parent / "observations.json"
    result = postprocess(
        tad["rallies"],
        ocr["rallies"],
        **config,
        video_duration_s=args.video_duration_s or tad.get("duration_s"),
        score_observations=json.loads(observations.read_text())
        if observations.exists()
        else None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

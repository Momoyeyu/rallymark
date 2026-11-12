#!/usr/bin/env python3
"""Fuse TAD proposals with OCR end times without reading ground truth."""
import argparse
import json
import math
from pathlib import Path


def merge_intervals(intervals):
    """Merge overlapping or touching intervals, including transitive overlaps."""
    groups = []
    for item in sorted(intervals, key=lambda x: (x["start_s"], x["end_s"])):
        if groups and item["start_s"] <= groups[-1]["end_s"]:
            groups[-1]["end_s"] = max(groups[-1]["end_s"], item["end_s"])
            groups[-1]["members"].extend(item["members"])
        else:
            groups.append({
                "start_s": item["start_s"], "end_s": item["end_s"],
                "members": list(item["members"]),
            })
    return groups


def prepare(rows, kind):
    intervals = []
    for index, row in enumerate(rows, 1):
        start, end, score = (row[key] for key in ("start_s", "end_s", "score"))
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) for x in (start, end, score)):
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


def postprocess(tad_rows, ocr_rows, threshold=0.10, nearby_seconds=5, *, top_k=None):
    if isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Threshold must be between 0 and 1")
    if isinstance(nearby_seconds, bool) or not math.isfinite(nearby_seconds) or not 1 <= nearby_seconds <= 10:
        raise ValueError("Nearby seconds must be between 1 and 10")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 200):
        raise ValueError("Prediction count must be an integer between 1 and 200")
    tad = prepare(tad_rows, "tad")
    ocr = prepare(ocr_rows, "ocr")
    if top_k is None:
        tad = [item for item in tad if item["members"][0]["score"] >= threshold]
    else:
        tad = sorted(tad, key=lambda item: (
            -item["members"][0]["score"], item["start_s"], item["end_s"],
            item["members"][0]["index"],
        ))[:top_k]
    merged_tad = merge_intervals(tad)
    mixed = merge_intervals(merged_tad + ocr)
    legal = [summarize(group) for group in mixed
             if any(row["kind"] == "ocr" for row in group["members"])]
    orphan_tad = [summarize(group) for group in mixed
                  if all(row["kind"] == "tad" for row in group["members"])]
    discarded = []
    # Newly accepted TAD intervals also become legal. Prefer the strongest
    # proposal when several orphan candidates occupy the same neighborhood.
    for candidate in sorted(orphan_tad, key=lambda x: (-x["score"], x["start_s"], x["end_s"])):
        gap = min((distance(candidate, interval) for interval in legal), default=math.inf)
        if gap <= nearby_seconds:
            discarded.append(dict(candidate, nearest_legal_gap_s=gap))
        else:
            legal.append(candidate)
    return {
        "parameters": {"tad_threshold": threshold if top_k is None else None,
                       "top_k": top_k, "nearby_seconds": nearby_seconds},
        "selected_tad": [item["members"][0] for item in tad],
        "rallies": sorted(legal, key=lambda x: (x["start_s"], x["end_s"])),
        "tad_merged": [summarize(group) for group in merged_tad],
        "discarded_tad": discarded,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tad", type=Path, required=True)
    parser.add_argument("--ocr", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--top-k", type=int, help="Use the N highest-confidence TAD proposals (default: 200)")
    selection.add_argument("--threshold", type=float, help="Legacy confidence-threshold selection")
    parser.add_argument("--nearby-seconds", type=float, default=5)
    args = parser.parse_args()
    result = postprocess(
        json.loads(args.tad.read_text())["rallies"],
        json.loads(args.ocr.read_text())["rallies"],
        args.threshold if args.threshold is not None else 0.10, args.nearby_seconds,
        top_k=(args.top_k if args.top_k is not None else 200) if args.threshold is None else None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

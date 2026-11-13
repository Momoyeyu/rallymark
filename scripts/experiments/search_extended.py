#!/usr/bin/env python3
"""Broaden the unchanged fusion rule and rank omission before false rallies."""

import argparse
import csv
import math
import time
from collections import defaultdict
from pathlib import Path

from evaluate_grid import (
    DEFAULT_VIDEOS,
    ROOT,
    aggregate,
    evaluate,
    load_module,
    read_rows,
    sha256,
    write_json,
)

POST_PATH = ROOT / "services/algorithm/vendor/ftt/code/postprocess_rallies.py"
POST = load_module("extended_production_post", POST_PATH)


def prepare(post, tad_rows, ocr_rows, top_k):
    if not 1 <= top_k <= 200:
        raise ValueError("Top-N must be in [1,200]")
    tad = sorted(
        post.prepare(tad_rows, "tad"),
        key=lambda item: (
            -item["members"][0]["score"],
            item["start_s"],
            item["end_s"],
            item["members"][0]["index"],
        ),
    )[:top_k]
    mixed = post.merge_intervals(
        post.merge_intervals(tad) + post.prepare(ocr_rows, "ocr")
    )
    legal, orphans = [], []
    for group in mixed:
        target = (
            legal if any(row["kind"] == "ocr" for row in group["members"]) else orphans
        )
        target.append(post.summarize(group))
    orphans.sort(key=lambda x: (-x["score"], x["start_s"], x["end_s"]))
    return legal, orphans


def fuse(initial_legal, orphans, nearby_seconds):
    if not math.isfinite(nearby_seconds) or not 1 <= nearby_seconds <= 30:
        raise ValueError("Experimental distance must be in [1,30] seconds")
    legal, discarded = list(initial_legal), []
    for candidate in orphans:
        gap = min((POST.distance(candidate, row) for row in legal), default=math.inf)
        if gap <= nearby_seconds:
            discarded.append(dict(candidate, nearest_legal_gap_s=gap))
        else:
            legal.append(candidate)
    return {
        "rallies": sorted(legal, key=lambda x: (x["start_s"], x["end_s"])),
        "discarded_tad": discarded,
    }


def rank(rows, config, coarse=False):
    def total(key):
        return sum(r[key] for r in rows)

    omissions = (
        total("coverage_zero_missed_rounds"),
        total("coverage_05_missed_rounds"),
        total("event_03_fn"),
    )
    if coarse:
        quality = (total("event_03_fp"), total("event_05_fn"), total("event_05_fp"))
    else:
        quality = (total("event_05_fn"), total("event_03_fp"), total("event_05_fp"))
    return (
        *omissions,
        *quality,
        -total("duration_tp_s"),
        -total("selection_f1"),
        -config[1],
        -config[0],
    )


def group_rows(records, videos):
    groups = defaultdict(list)
    for row in records:
        if row["video_id"] in videos:
            groups[(row["top_k"], row["nearby_seconds"])].append(row)
    if any({r["video_id"] for r in rows} != set(videos) for rows in groups.values()):
        raise ValueError("Incomplete grid")
    return groups


def select(records, videos, coarse=False):
    groups = group_rows(records, videos)
    config = min(groups, key=lambda key: rank(groups[key], key, coarse))
    return {"top_k": config[0], "nearby_seconds": config[1]}


def selected_rows(records, videos, config):
    return [
        r
        for r in records
        if r["video_id"] in videos
        and r["top_k"] == config["top_k"]
        and r["nearby_seconds"] == config["nearby_seconds"]
    ]


def run(args):
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "complete.json").unlink(missing_ok=True)
    provenance, inputs, records = {}, {}, []
    for key in DEFAULT_VIDEOS:
        paths = {
            "tad": args.input / f"raw/{key}/tad/predictions.json",
            "ocr": args.input / f"raw/{key}/ocr/predictions.json",
            "gt": args.input / f"gt/{key}.json",
        }
        inputs[key] = {name: read_rows(path) for name, path in paths.items()}
        provenance[key] = {
            name: {"path": str(path.relative_to(args.input)), "sha256": sha256(path)}
            for name, path in paths.items()
        }
    gaps = [1 + i / 4 for i in range(117)]
    write_json(
        args.output / "protocol.json",
        {
            "top_k": [1, 200],
            "nearby_seconds": [1, 30],
            "step_s": 0.25,
            "rule": "Unchanged fusion; only experiment distance validation expanded to30. Production unchanged.",
            "strict_priority": [
                "zero_intersection_misses",
                "under_50pct_coverage_misses",
                "IoU03_FN",
                "IoU05_FN",
                "IoU03_FP",
                "IoU05_FP",
                "max_duration_TP",
                "max_combined_F1",
                "longer_gap_tie",
                "larger_N_tie",
            ],
            "coarse_priority": "Same except IoU03_FP precedes IoU05_FN. A rally with IoU0.3..0.5 is a boundary error, not a wholly fake rally.",
            "model_inference": "Reused unchanged six-video raw predictions; no GPU or GT access in fusion.",
            "code_sha256": {
                "production_helpers": sha256(POST_PATH),
                "metrics": sha256(Path(__file__).with_name("evaluate_grid.py")),
                "search": sha256(Path(__file__)),
            },
            "input_provenance": provenance,
        },
    )
    for key, data in inputs.items():
        cache = {}
        for top_k in range(1, 201):
            prepared = prepare(POST, data["tad"], data["ocr"], top_k)
            for gap in gaps:
                result = fuse(*prepared, gap)
                signature = tuple((r["start_s"], r["end_s"]) for r in result["rallies"])
                if signature not in cache:
                    cache[signature] = evaluate(data["gt"], result["rallies"])
                records.append(
                    dict(
                        video_id=key,
                        top_k=top_k,
                        nearby_seconds=gap,
                        **cache[signature],
                    )
                )
        print(key, "23400 configurations; distinct outputs", len(cache), flush=True)
    with (args.output / "grid.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    summary = {
        "videos": DEFAULT_VIDEOS,
        "configurations_per_video": 23400,
        "rows": len(records),
        "input_provenance": provenance,
    }
    for policy, coarse in [("strict", False), ("coarse", True)]:
        config = select(records, DEFAULT_VIDEOS, coarse)
        rows = selected_rows(records, DEFAULT_VIDEOS, config)
        folds, heldout = [], []
        for video in DEFAULT_VIDEOS:
            training = [v for v in DEFAULT_VIDEOS if v != video]
            chosen = select(records, training, coarse)
            result = selected_rows(records, [video], chosen)[0]
            heldout.append(result)
            folds.append(
                {
                    "video": video,
                    "training": training,
                    "parameters": chosen,
                    "metrics": result,
                }
            )
        summary[policy] = {
            "parameters": config,
            "aggregate": aggregate(rows),
            "per_video": rows,
            "leave_one_out": {"aggregate": aggregate(heldout), "folds": folds},
        }
    summary["previous_recommendation"] = {
        "parameters": {"top_k": 200, "nearby_seconds": 2},
        "aggregate": aggregate(
            selected_rows(records, DEFAULT_VIDEOS, {"top_k": 200, "nearby_seconds": 2})
        ),
    }
    by_gap = []
    for gap in gaps:
        subset = [r for r in records if r["nearby_seconds"] == gap]
        config = select(subset, DEFAULT_VIDEOS)
        rows = selected_rows(subset, DEFAULT_VIDEOS, config)
        a = aggregate(rows)
        by_gap.append(
            {
                "nearby_seconds": gap,
                "top_k": config["top_k"],
                "complete_misses": a["pooled"]["coverage_zero_missed_rounds"],
                "under_half_misses": a["pooled"]["coverage_05"]["missed_rounds"],
                "event03_fn": a["pooled"]["event_03"]["fn"],
                "event05_fn": a["pooled"]["event_05"]["fn"],
                "false_rallies": a["pooled"]["event_03"]["fp"],
                "macro_event05_f1": a["macro"]["event_05_f1"],
                "macro_duration_recall": a["macro"]["duration_recall"],
            }
        )
    summary["distance_sensitivity"] = by_gap
    summary["elapsed_seconds"] = time.monotonic() - started
    write_json(args.output / "summary.json", summary)
    with (args.output / "by_distance.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(by_gap[0]))
        writer.writeheader()
        writer.writerows(by_gap)
    write_json(
        args.output / "complete.json",
        {
            "summary_sha256": sha256(args.output / "summary.json"),
            "rows": len(records),
            "elapsed_seconds": time.monotonic() - started,
        },
    )
    print(
        {policy: summary[policy]["parameters"] for policy in ["strict", "coarse"]},
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())

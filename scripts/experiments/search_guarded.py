#!/usr/bin/env python3
"""Experimental long-distance suppression with protected TAD ranks; no product changes."""

import argparse
import csv
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path

from evaluate_grid import (
    DEFAULT_VIDEOS,
    ROOT,
    aggregate,
    evaluate,
    intersection_duration,
    intervals,
    load_module,
    read_rows,
    sha256,
    union,
    write_json,
)
from search_extended import POST, fuse, prepare

GAPS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30]
DURATIONS = [0, 0.5, 1, 1.5, 2]
PROTECTIONS = [0, 10, 20, 30, 50, 100, 200]
CONFIG_FIELDS = ["top_k", "nearby_seconds", "min_duration_s", "protect_top_m"]


def fuse_guarded(
    initial_legal, orphans, nearby_seconds, min_duration_s, protected_indices
):
    if not 1 <= nearby_seconds <= 600 or not 0 <= min_duration_s <= 2:
        raise ValueError("Invalid experimental configuration")
    legal, discarded = list(initial_legal), []
    for candidate in orphans:
        if candidate["end_s"] - candidate["start_s"] < min_duration_s:
            discarded.append(dict(candidate, drop_reason="short_orphan"))
            continue
        gap = min((POST.distance(candidate, row) for row in legal), default=math.inf)
        protected = bool(protected_indices.intersection(candidate["tad_indices"]))
        if gap <= nearby_seconds and not protected:
            discarded.append(
                dict(candidate, nearest_legal_gap_s=gap, drop_reason="nearby")
            )
        else:
            legal.append(candidate)
    return {
        "rallies": sorted(legal, key=lambda r: (r["start_s"], r["end_s"])),
        "discarded_tad": discarded,
    }


def positive_intersection(gt, predicted):
    return union(
        [
            (max(a, c), min(b, d))
            for a, b in gt
            for c, d in predicted
            if max(a, c) < min(b, d)
        ]
    )


def previous_positive_loss(previous_positive, predicted):
    old = sum(b - a for a, b in previous_positive)
    return max(0.0, old - intersection_duration(previous_positive, union(predicted)))


def config_tuple(row):
    return tuple(row[key] for key in CONFIG_FIELDS)


def metric_rows(rows):
    return [
        {k: v for k, v in row.items() if k not in ["min_duration_s", "protect_top_m"]}
        for row in rows
    ]


def parse_grid_row(row):
    return {
        key: value
        if key == "video_id"
        else int(value)
        if key in {"top_k", "protect_top_m"}
        else float(value)
        for key, value in row.items()
    }


def no_regression(row, baseline):
    return (
        row["lost_previous_gt_seconds"] <= 1e-8
        and row["event_03_fn"] <= baseline["event_03_fn"]
        and row["event_05_fn"] <= baseline["event_05_fn"]
    )


def rank(rows, config):
    def total(key):
        return sum(r[key] for r in rows)

    return (
        total("coverage_zero_missed_rounds"),
        total("coverage_05_missed_rounds"),
        total("event_03_fn"),
        total("event_05_fn"),
        total("event_03_fp"),
        total("event_05_fp"),
        -total("duration_tp_s"),
        -total("selection_f1"),
        config[3],
        config[1],
        -config[0],
        config[2],
    )


def select(records, videos, baselines, require_no_regression=True, minimum_gap=1):
    groups = defaultdict(list)
    for row in records:
        if row["video_id"] in videos and row["nearby_seconds"] >= minimum_gap:
            groups[config_tuple(row)].append(row)
    eligible = {
        c: rs
        for c, rs in groups.items()
        if len(rs) == len(videos)
        and (
            not require_no_regression
            or all(no_regression(r, baselines[r["video_id"]]) for r in rs)
        )
    }
    if not eligible:
        return None
    config = min(eligible, key=lambda c: rank(eligible[c], c))
    return dict(zip(CONFIG_FIELDS, config, strict=True))


def matching_rows(records, videos, config):
    return [
        r
        for r in records
        if r["video_id"] in videos and all(r[k] == v for k, v in config.items())
    ]


def run(args):
    started = time.monotonic()
    top_counts = range(160, 201) if args.refine else range(1, 201)
    protections = range(50, 101) if args.refine else PROTECTIONS
    durations = [i / 4 for i in range(9)] if args.refine else DURATIONS
    gaps = [5, 8, 10, 12, 15, 20, 25, 30, 45, 60, 600] if args.refine else GAPS
    if args.confirm:
        top_counts = [200]
        protections = range(201)
        durations = [i / 4 for i in range(9)]
        gaps = [1 + i / 4 for i in range(117)] + [45, 60, 600]
    if args.conservative_from:
        top_counts = [200]
        protections = range(201)
        durations = [0.5]
        gaps = list(range(1, 31)) + [45, 60, 600]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "complete.json").unlink(missing_ok=True)
    inputs, baselines, records, positive, provenance = {}, {}, [], {}, {}
    for video in DEFAULT_VIDEOS:
        paths = {
            kind: args.input
            / (
                f"gt/{video}.json"
                if kind == "gt"
                else f"raw/{video}/{kind}/predictions.json"
            )
            for kind in ["gt", "tad", "ocr"]
        }
        inputs[video] = {kind: read_rows(path) for kind, path in paths.items()}
        provenance[video] = {
            kind: {"path": str(path.relative_to(args.input)), "sha256": sha256(path)}
            for kind, path in paths.items()
        }
        d = inputs[video]
        baseline = fuse(*prepare(POST, d["tad"], d["ocr"], 200), 2)["rallies"]
        baselines[video] = evaluate(d["gt"], baseline)
        positive[video] = positive_intersection(
            union(intervals(d["gt"])), union(intervals(baseline))
        )
    count = (
        sum(sum(m <= n for m in protections) for n in top_counts)
        * len(gaps)
        * len(durations)
    )
    write_json(
        args.output / "protocol.json",
        {
            "top_k": [min(top_counts), max(top_counts)],
            "nearby_seconds": gaps,
            "min_duration_s": durations,
            "protect_top_m": list(protections),
            "source_grid": str(args.conservative_from)
            if args.conservative_from
            else None,
            "stage": "conservative"
            if args.conservative_from
            else "confirm"
            if args.confirm
            else ("refine" if args.refine else "coarse"),
            "configurations_per_video": count,
            "method": "Only TAD-only orphan candidates: drop short intervals; protect candidates containing any globally top-M selected TAD member against nearby exclusion. OCR fusion unchanged.",
            "selection": "No loss of any GT-positive second covered by previous200,2; no per-video IoU03/05 FN increase. Then minimize omissions, FN, fake rallies, boundary FP; prefer smaller M and shorter gap on exact score ties.",
            "inference_reads_gt": False,
            "source_sha256": {
                "search": sha256(Path(__file__)),
                "extended_helpers": sha256(
                    Path(__file__).with_name("search_extended.py")
                ),
            },
            "input_provenance": provenance,
        },
    )
    if args.conservative_from:
        source = args.conservative_from.parent
        marker = json.loads((source / "complete.json").read_text())
        source_protocol = json.loads((source / "protocol.json").read_text())
        if (
            marker["summary_sha256"] != sha256(source / "summary.json")
            or source_protocol["input_provenance"] != provenance
        ):
            raise ValueError("Source grid is incomplete or uses different inputs")
        with args.conservative_from.open() as handle:
            for row in csv.DictReader(handle):
                gap = float(row["nearby_seconds"])
                if (
                    int(row["top_k"]) == 200
                    and float(row["min_duration_s"]) == 0.5
                    and gap in gaps
                ):
                    records.append(parse_grid_row(row))
        if len(records) != count * len(DEFAULT_VIDEOS):
            raise ValueError("Source grid has missing or duplicated operating points")
    search_inputs = {} if args.conservative_from else inputs
    for video, data in search_inputs.items():
        ranking = sorted(
            range(1, len(data["tad"]) + 1),
            key=lambda i: (
                -data["tad"][i - 1]["score"],
                data["tad"][i - 1]["start_s"],
                data["tad"][i - 1]["end_s"],
                i,
            ),
        )
        cache = {}
        for n in top_counts:
            prepared = prepare(POST, data["tad"], data["ocr"], n)
            for m in protections:
                if m > n:
                    continue
                protected = set(ranking[:m])
                for duration in durations:
                    for gap in gaps:
                        result = fuse_guarded(*prepared, gap, duration, protected)
                        signature = tuple(
                            (r["start_s"], r["end_s"]) for r in result["rallies"]
                        )
                        if signature not in cache:
                            cache[signature] = dict(
                                **evaluate(data["gt"], result["rallies"]),
                                lost_previous_gt_seconds=previous_positive_loss(
                                    positive[video], signature
                                ),
                            )
                        records.append(
                            dict(
                                video_id=video,
                                top_k=n,
                                nearby_seconds=gap,
                                min_duration_s=duration,
                                protect_top_m=m,
                                **cache[signature],
                            )
                        )
        print(
            video, count, "configurations;", len(cache), "distinct outputs", flush=True
        )
    with (args.output / "grid.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    summary = {
        "videos": DEFAULT_VIDEOS,
        "configurations_per_video": count,
        "rows": len(records),
        "baseline": {v: baselines[v] for v in DEFAULT_VIDEOS},
    }
    for policy, minimum_gap, constrain in [
        ("no_regression", 1, True),
        ("long_gap", 5, True),
        ("counts_only", 1, False),
    ]:
        config = select(records, DEFAULT_VIDEOS, baselines, constrain, minimum_gap)
        if config is None:
            summary[policy] = None
            continue
        rows = matching_rows(records, DEFAULT_VIDEOS, config)
        folds, held = [], []
        for video in DEFAULT_VIDEOS:
            train = [v for v in DEFAULT_VIDEOS if v != video]
            chosen = select(records, train, baselines, constrain, minimum_gap)
            if chosen is None:
                raise ValueError("Training fold has no feasible configurations")
            r = matching_rows(records, [video], chosen)[0]
            held.append(r)
            folds.append(
                {
                    "video": video,
                    "training": train,
                    "parameters": chosen,
                    "metrics": r,
                    "heldout_satisfies_constraints": no_regression(r, baselines[video]),
                }
            )
        summary[policy] = {
            "parameters": config,
            "aggregate": aggregate(metric_rows(rows)),
            "per_video": rows,
            "leave_one_out": {
                "aggregate": aggregate(metric_rows(held)),
                "folds": folds,
            },
        }
    summary["elapsed_seconds"] = time.monotonic() - started
    write_json(args.output / "summary.json", summary)
    scores = load_module(
        "guarded_scores", ROOT / "services/algorithm/src/rallymark_algorithm/scores.py"
    )
    dataset = {
        d["id"]: d
        for d in json.loads((args.input / "dataset.json").read_text())["videos"]
    }
    for policy in ["no_regression", "long_gap", "counts_only"]:
        if summary[policy] is None:
            continue
        c = summary[policy]["parameters"]
        manifest = []
        for video, data in inputs.items():
            ranking = sorted(
                range(1, len(data["tad"]) + 1),
                key=lambda i: (
                    -data["tad"][i - 1]["score"],
                    data["tad"][i - 1]["start_s"],
                    data["tad"][i - 1]["end_s"],
                    i,
                ),
            )
            result = fuse_guarded(
                *prepare(POST, data["tad"], data["ocr"], c["top_k"]),
                c["nearby_seconds"],
                c["min_duration_s"],
                set(ranking[: c["protect_top_m"]]),
            )
            rallies = scores.enrich_scores(
                [
                    {"start_s": r["start_s"], "end_s": r["end_s"]}
                    for r in result["rallies"]
                ],
                result["rallies"],
                data["ocr"],
            )
            title = json.loads((args.input / f"gt/{video}.json").read_text()).get(
                "title", video
            )
            metadata = {
                "title": title,
                "duration_s": dataset[video]["duration_s"],
                "source_size_bytes": dataset[video]["bytes"],
                "source_sha256": dataset[video]["sha256"],
                "parameters": c,
                "selection_policy": policy,
                "rallies": rallies,
                "fusion": result,
                "warnings": ["实验性后处理；比分沿用OCR，未单独评估。"],
            }
            write_json(args.output.parent / f"review-{policy}/{video}.json", metadata)
            manifest.append(
                {
                    "id": video,
                    "video": os.path.relpath(
                        args.input / "videos" / f"{video}.mp4",
                        args.output.parent / f"review-{policy}",
                    ),
                    "metadata": f"{video}.json",
                    "rallies": len(rallies),
                }
            )
        write_json(
            args.output.parent / f"review-{policy}/manifest.json",
            {"parameters": c, "videos": manifest},
        )
    write_json(
        args.output / "complete.json",
        {
            "summary_sha256": sha256(args.output / "summary.json"),
            "rows": len(records),
            "elapsed_seconds": time.monotonic() - started,
        },
    )
    print(
        {
            p: (summary[p]["parameters"] if summary[p] else None)
            for p in ["no_regression", "long_gap", "counts_only"]
        },
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--refine", action="store_true")
    phase.add_argument("--confirm", action="store_true")
    phase.add_argument("--conservative-from", type=Path, metavar="GRID_CSV")
    run(parser.parse_args())

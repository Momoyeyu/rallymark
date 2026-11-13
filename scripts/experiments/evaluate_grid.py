#!/usr/bin/env python3
"""Offline CPU evaluation of production fusion. Ground truth never enters inference.

All times are continuous seconds. Manual one-second labels are used as supplied;
no tolerance padding, discretization, or score-label comparison is applied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import platform
import subprocess
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VIDEOS = ["nina", "sun", "harimoto", "hayata", "wang", "chen"]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def intervals(rows):
    result = []
    for row in rows:
        start, end = row["start_s"], row["end_s"]
        if (
            any(
                isinstance(x, bool)
                or not isinstance(x, (int, float))
                or not math.isfinite(x)
                for x in (start, end)
            )
            or start < 0
            or end <= start
        ):
            raise ValueError(f"Invalid interval bounds: {start!r}, {end!r}")
        result.append((float(start), float(end)))
    return result


def union(bounds):
    merged = []
    for start, end in sorted(bounds):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def intersection_duration(left, right):
    total = 0.0
    i = j = 0
    while i < len(left) and j < len(right):
        total += max(0.0, min(left[i][1], right[j][1]) - max(left[i][0], right[j][0]))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return total


def prf(tp, fp, fn):
    # Empty sets agree perfectly; an undefined precision/recall on one empty side
    # is zero when the other side contains events/duration.
    if tp + fp + fn == 0:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "f2": 1.0}
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn),
        "f2": 5 * tp / (5 * tp + fp + 4 * fn),
    }


def maximum_matching(adjacency, ground_truth_count):
    """Maximum cardinality bipartite matching via augmenting paths, not greedy."""
    owners = [-1] * ground_truth_count

    def augment(prediction, seen):
        for gt in adjacency[prediction]:
            if gt in seen:
                continue
            seen.add(gt)
            if owners[gt] == -1 or augment(owners[gt], seen):
                owners[gt] = prediction
                return True
        return False

    for prediction in range(len(adjacency)):
        augment(prediction, set())
    return sorted((pred, gt) for gt, pred in enumerate(owners) if pred != -1)


def evaluate(gt_rows, prediction_rows):
    gt, pred = intervals(gt_rows), intervals(prediction_rows)
    gt_union, pred_union = union(gt), union(pred)
    gt_duration = sum(b - a for a, b in gt_union)
    pred_duration = sum(b - a for a, b in pred_union)
    tp = intersection_duration(gt_union, pred_union)
    result = {
        "gt_count": len(gt),
        "prediction_count": len(pred),
        "gt_duration_s": gt_duration,
        "prediction_duration_s": pred_duration,
        "duration_tp_s": tp,
        "duration_fp_s": max(0.0, pred_duration - tp),
        "duration_fn_s": max(0.0, gt_duration - tp),
    }
    result.update(
        {
            f"duration_{key}": value
            for key, value in prf(
                tp, result["duration_fp_s"], result["duration_fn_s"]
            ).items()
        }
    )
    ious = []
    for a, b in pred:
        ious.append(
            [
                max(0.0, min(b, d) - max(a, c))
                / ((b - a) + (d - c) - max(0.0, min(b, d) - max(a, c)))
                for c, d in gt
            ]
        )
    for threshold, label in [(0.3, "03"), (0.5, "05")]:
        adjacency = [
            [i for i, value in enumerate(row) if value >= threshold] for row in ious
        ]
        pairs = maximum_matching(adjacency, len(gt))
        count = len(pairs)
        result.update(
            {
                f"event_{label}_tp": count,
                f"event_{label}_fp": len(pred) - count,
                f"event_{label}_fn": len(gt) - count,
                f"event_{label}_missed_rounds": len(gt) - count,
            }
        )
        result.update(
            {
                f"event_{label}_{key}": value
                for key, value in prf(count, len(pred) - count, len(gt) - count).items()
            }
        )
    coverage = [intersection_duration([(a, b)], pred_union) / (b - a) for a, b in gt]
    covered = sum(value >= 0.5 for value in coverage)
    result.update(
        coverage_zero_missed_rounds=sum(value == 0 for value in coverage),
        coverage_90_count=sum(value >= 0.9 for value in coverage),
        coverage_90_recall=sum(value >= 0.9 for value in coverage) / len(gt)
        if gt
        else 1.0,
        coverage_05_count=covered,
        coverage_05_missed_rounds=len(gt) - covered,
        coverage_05_recall=covered / len(gt) if gt else 1.0,
        coverage_mean=sum(coverage) / len(gt) if gt else 1.0,
    )
    for beta in (1, 2):
        result[f"selection_f{beta}"] = (
            result[f"duration_f{beta}"] + result[f"event_05_f{beta}"]
        ) / 2
    result["selection_recall"] = (
        result["duration_recall"] + result["event_05_recall"]
    ) / 2
    result["selection_precision"] = (
        result["duration_precision"] + result["event_05_precision"]
    ) / 2
    return result


def aggregate(records):
    if not records:
        raise ValueError("Cannot aggregate no records")
    metrics = [
        key for key in records[0] if key not in ("video_id", "top_k", "nearby_seconds")
    ]
    macro = {key: sum(row[key] for row in records) / len(records) for key in metrics}
    pooled = {}
    for prefix, suffix in [("duration", "_s"), ("event_03", ""), ("event_05", "")]:
        counts = {
            name: sum(row[f"{prefix}_{name}{suffix}"] for row in records)
            for name in ("tp", "fp", "fn")
        }
        pooled[prefix] = dict(**counts, **prf(**counts))
    n_gt = sum(row["gt_count"] for row in records)
    covered = sum(row["coverage_05_count"] for row in records)
    pooled["coverage_05"] = {
        "count": covered,
        "missed_rounds": n_gt - covered,
        "recall": covered / n_gt if n_gt else 1.0,
    }
    pooled["coverage_zero_missed_rounds"] = sum(
        row["coverage_zero_missed_rounds"] for row in records
    )
    covered_90 = sum(row["coverage_90_count"] for row in records)
    pooled["coverage_90"] = {
        "count": covered_90,
        "recall": covered_90 / n_gt if n_gt else 1.0,
    }
    return {"video_count": len(records), "macro": macro, "pooled": pooled}


def select_config(records, video_ids, primary="selection_f2"):
    groups = defaultdict(list)
    videos = set(video_ids)
    for row in records:
        if row["video_id"] in videos:
            groups[(row["top_k"], row["nearby_seconds"])].append(row)
    candidates = []
    for (top_k, nearby), rows in groups.items():
        if {row["video_id"] for row in rows} != videos:
            raise ValueError("Incomplete parameter grid")

        def mean(key, rows=rows):
            return sum(row.get(key, 0.0) for row in rows) / len(rows)

        secondary = "selection_f1" if primary == "selection_f2" else "selection_f2"
        objective = (
            mean(primary),
            mean(secondary),
            mean("event_05_f1"),
            mean("coverage_05_recall"),
            -abs(nearby - 5),
            -abs(top_k - 200),
            -nearby,
            -top_k,
        )
        candidates.append((objective, top_k, nearby))
    if not candidates:
        raise ValueError("No candidate parameters")
    _, top_k, nearby = max(candidates)
    return {"top_k": top_k, "nearby_seconds": nearby}


def select_recall_config(records, video_ids, f1_fraction=0.9):
    """Minimize rally misses subject to a training-only relative macro F1 floor."""
    groups = defaultdict(list)
    videos = set(video_ids)
    for row in records:
        if row["video_id"] in videos:
            groups[(row["top_k"], row["nearby_seconds"])].append(row)
    best_f1 = max(
        sum(row["selection_f1"] for row in rows) / len(rows) for rows in groups.values()
    )
    candidates = []
    for (top_k, nearby), rows in groups.items():
        if {row["video_id"] for row in rows} != videos:
            raise ValueError("Incomplete parameter grid")
        mean_f1 = sum(row["selection_f1"] for row in rows) / len(rows)
        if mean_f1 + 1e-12 < f1_fraction * best_f1:
            continue
        objective = (
            -sum(row["coverage_05_missed_rounds"] for row in rows),
            -sum(row["event_05_missed_rounds"] for row in rows),
            sum(row["duration_recall"] for row in rows) / len(rows),
            mean_f1,
            -abs(nearby - 5),
            -abs(top_k - 200),
            -nearby,
            -top_k,
        )
        candidates.append((objective, top_k, nearby))
    _, top_k, nearby = max(candidates)
    return {"top_k": top_k, "nearby_seconds": nearby}


def pareto_frontier(records, video_ids):
    """Non-dominated macro recall/precision points, retaining parameter ties."""
    groups = defaultdict(list)
    for row in records:
        if row["video_id"] in video_ids:
            groups[(row["top_k"], row["nearby_seconds"])].append(row)
    points = []
    for (top_k, nearby), rows in groups.items():
        points.append(
            {
                "top_k": top_k,
                "nearby_seconds": nearby,
                "macro_recall": sum(r["selection_recall"] for r in rows) / len(rows),
                "macro_precision": sum(r["selection_precision"] for r in rows)
                / len(rows),
            }
        )
    points.sort(key=lambda row: (-row["macro_recall"], -row["macro_precision"]))
    frontier = []
    best_precision = -1.0
    previous = None
    for row in points:
        pair = (row["macro_recall"], row["macro_precision"])
        if row["macro_precision"] > best_precision or pair == previous:
            frontier.append(row)
            best_precision = max(best_precision, row["macro_precision"])
            previous = pair
    return frontier


def config_rows(records, config, video_ids):
    return [
        row
        for row in records
        if row["video_id"] in video_ids
        and row["top_k"] == config["top_k"]
        and row["nearby_seconds"] == config["nearby_seconds"]
    ]


def read_rows(path):
    data = json.loads(path.read_text())
    rows = data if isinstance(data, list) else data["rallies"]
    intervals(rows)
    return rows


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    started = time.monotonic()
    post_path = ROOT / "services/algorithm/vendor/ftt/code/postprocess_rallies.py"
    scores_path = ROOT / "services/algorithm/src/rallymark_algorithm/scores.py"
    post = load_module("experiment_postprocess", post_path)
    scores = load_module("experiment_scores", scores_path)
    args.output.mkdir(parents=True, exist_ok=True)
    # Remove a prior success marker before attempting a new evaluation.
    (args.output / "complete.json").unlink(missing_ok=True)
    inputs, provenance = {}, {}
    for video in args.videos:
        paths = {
            "gt": args.experiment / "gt" / f"{video}.json",
            "tad": args.experiment / "raw" / video / "tad/predictions.json",
            "ocr": args.experiment / "raw" / video / "ocr/predictions.json",
        }
        inputs[video] = {key: read_rows(path) for key, path in paths.items()}
        provenance[video] = {
            key: {
                "path": str(path.relative_to(args.experiment)),
                "sha256": sha256(path),
            }
            for key, path in paths.items()
        }
    n_steps = round(9 / args.interval_step)
    nearby_values = [round(1 + i * args.interval_step, 8) for i in range(n_steps + 1)]
    if not math.isclose(nearby_values[-1], 10):
        raise ValueError("Interval step must divide the [1, 10] span exactly")
    grid = [
        (k, nearby)
        for k in range(args.top_k_min, args.top_k_max + 1)
        for nearby in nearby_values
    ]
    baseline = {"top_k": 200, "nearby_seconds": 5.0}
    if (200, 5.0) not in grid:
        grid.append((200, 5.0))
    records = []
    for video, data in inputs.items():
        # Repeated postprocess outputs have identical metric values; cache those
        # values only. Every requested parameter is still executed and exported.
        metric_cache = {}
        for top_k, nearby in grid:
            fused = post.postprocess(
                data["tad"], data["ocr"], top_k=top_k, nearby_seconds=nearby
            )
            signature = tuple((r["start_s"], r["end_s"]) for r in fused["rallies"])
            if signature not in metric_cache:
                metric_cache[signature] = evaluate(data["gt"], fused["rallies"])
            records.append(
                dict(
                    video_id=video,
                    top_k=top_k,
                    nearby_seconds=nearby,
                    **metric_cache[signature],
                )
            )
        print(
            f"{video}: {len(grid)} configurations, {len(metric_cache)} distinct interval outputs",
            flush=True,
        )
    with (args.output / "grid.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    eligible = [
        row
        for row in records
        if args.top_k_min <= row["top_k"] <= args.top_k_max
        and row["nearby_seconds"] in nearby_values
    ]
    best = select_config(eligible, args.videos)
    best_f1 = select_config(eligible, args.videos, primary="selection_f1")
    best_recall = select_recall_config(eligible, args.videos)
    baseline_rows = config_rows(records, baseline, args.videos)
    best_rows = config_rows(records, best, args.videos)
    folds, held_out = [], []
    alternative_folds = {"best_f1": [], "recall_priority": []}
    alternative_held_out = {"best_f1": [], "recall_priority": []}
    for video in args.videos:
        train = [v for v in args.videos if v != video]
        selected = select_config(eligible, train)
        row = config_rows(records, selected, [video])[0]
        held_out.append(row)
        folds.append(
            {
                "held_out_video": video,
                "training_videos": train,
                "selected_parameters": selected,
                "training": aggregate(config_rows(records, selected, train)),
                "held_out": row,
                "baseline": config_rows(records, baseline, [video])[0],
            }
        )
        for policy, policy_folds in alternative_folds.items():
            alternative = (
                select_config(eligible, train, primary="selection_f1")
                if policy == "best_f1"
                else select_recall_config(eligible, train)
            )
            alternative_row = config_rows(records, alternative, [video])[0]
            alternative_held_out[policy].append(alternative_row)
            policy_folds.append(
                {
                    "held_out_video": video,
                    "training_videos": train,
                    "selected_parameters": alternative,
                    "held_out": alternative_row,
                }
            )
        data = inputs[video]
        fused = post.postprocess(data["tad"], data["ocr"], **selected)
        timing_rows = [
            {"start_s": r["start_s"], "end_s": r["end_s"]} for r in fused["rallies"]
        ]
        enriched = scores.enrich_scores(timing_rows, fused["rallies"], data["ocr"])
        write_json(
            args.output / "selected" / f"{video}.json",
            {
                "video_id": video,
                "selection": "leave_one_video_out",
                "training_videos": train,
                "parameters": selected,
                "metrics": row,
                "rallies": enriched,
                "fusion": fused,
                "input_provenance": provenance[video],
            },
        )
    per_video = {}
    for video in args.videos:
        selected = select_config(eligible, [video])
        per_video[video] = {
            "parameters": selected,
            "metrics": config_rows(records, selected, [video])[0],
        }
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    summary = {
        "schema_version": 1,
        "units": "continuous seconds",
        "videos": args.videos,
        "manual_label_precision_s": 1,
        "boundary_tolerance_s": 0,
        "score_labels_evaluated": False,
        "git_commit": commit,
        "python": platform.python_version(),
        "code_sha256": {
            "postprocess": sha256(post_path),
            "scores": sha256(scores_path),
            "evaluator": sha256(Path(__file__)),
        },
        "input_provenance": provenance,
        "grid": {
            "top_k_min": args.top_k_min,
            "top_k_max": args.top_k_max,
            "nearby_seconds": nearby_values,
            "configurations_per_video": len(grid),
            "rows": len(records),
        },
        "selection_policy": {
            "primary": "macro mean(duration_f2, event_05_f2)",
            "secondary": "macro mean(duration_f1, event_05_f1)",
            "tie_breaks": [
                "macro event_05_f1",
                "macro coverage_05_recall",
                "distance to nearby=5",
                "distance to top_k=200",
                "smaller nearby_seconds",
                "smaller top_k",
            ],
            "note": "F2 weights recall; event matching penalizes split/merged detections.",
        },
        "metric_definitions": {
            "duration": "Union intersection TP; prediction union minus TP FP; GT union minus TP FN.",
            "event": "One-to-one maximum cardinality matching at IoU >= 0.3 and >= 0.5.",
            "coverage": "Fraction of each GT interval covered by prediction union; recalls at >= 0.5 and >= 0.9. Zero missed means no positive-duration intersection, distinct from partial coverage and event-IoU FN.",
            "empty": "Both sets empty: P/R/F=1. Only one empty: P/R/F=0.",
            "limitations": "One-second manual labels; no padding. Score labels excluded. Six-video LOO is exploratory.",
        },
        "baseline": {
            "parameters": baseline,
            "aggregate": aggregate(baseline_rows),
            "per_video": baseline_rows,
        },
        "in_sample_best": {
            "parameters": best,
            "aggregate": aggregate(best_rows),
            "per_video": best_rows,
        },
        "leave_one_video_out": {"aggregate": aggregate(held_out), "folds": folds},
        "best_f1_alternative": {
            "parameters": best_f1,
            "aggregate": aggregate(config_rows(records, best_f1, args.videos)),
            "per_video": config_rows(records, best_f1, args.videos),
        },
        "recall_priority_alternative": {
            "parameters": best_recall,
            "policy": "macro selection F1 >= 90% best macro selection F1; minimize coverage misses, then event05 misses; maximize duration recall, F1; baseline-distance tie breaks",
            "aggregate": aggregate(config_rows(records, best_recall, args.videos)),
            "per_video": config_rows(records, best_recall, args.videos),
        },
        "alternative_leave_one_video_out": {
            policy: {
                "aggregate": aggregate(alternative_held_out[policy]),
                "folds": alternative_folds[policy],
            }
            for policy in alternative_folds
        },
        "pareto_recall_precision": pareto_frontier(eligible, args.videos),
        "per_video_oracle": per_video,
        "elapsed_seconds": time.monotonic() - started,
    }
    write_json(args.output / "summary.json", summary)
    # Compact source-backed tables for downstream reports; no narrative inference.
    with (args.output / "comparison.csv").open("w", newline="") as handle:
        fields = [
            "scope",
            "video_id",
            "top_k",
            "nearby_seconds",
            "duration_precision",
            "duration_recall",
            "duration_f1",
            "duration_f2",
            "event_03_precision",
            "event_03_recall",
            "event_03_f1",
            "event_05_precision",
            "event_05_recall",
            "event_05_f1",
            "event_05_f2",
            "event_05_missed_rounds",
            "coverage_05_recall",
            "coverage_05_missed_rounds",
            "coverage_zero_missed_rounds",
            "coverage_90_recall",
            "selection_f1",
            "selection_f2",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for scope, rows in [
            ("baseline", baseline_rows),
            ("in_sample_best", best_rows),
            ("leave_one_video_out", held_out),
            ("best_f1_alternative", config_rows(records, best_f1, args.videos)),
            (
                "recall_priority_alternative",
                config_rows(records, best_recall, args.videos),
            ),
            ("leave_one_video_out_best_f1", alternative_held_out["best_f1"]),
            (
                "leave_one_video_out_recall_priority",
                alternative_held_out["recall_priority"],
            ),
            ("per_video_oracle", [entry["metrics"] for entry in per_video.values()]),
        ]:
            writer.writerows(dict(scope=scope, **row) for row in rows)
    with (args.output / "policy_comparison.csv").open("w", newline="") as handle:
        metrics = [
            "selection_f1",
            "selection_f2",
            "duration_recall",
            "duration_f1",
            "duration_f2",
            "duration_fn_s",
            "event_05_precision",
            "event_05_recall",
            "event_05_f1",
            "event_05_f2",
            "coverage_05_recall",
            "coverage_90_recall",
        ]
        fields = [
            "scope",
            "top_k",
            "nearby_seconds",
            *["macro_" + key for key in metrics],
            "total_event_05_missed_rounds",
            "total_coverage_05_missed_rounds",
            "total_coverage_zero_missed_rounds",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for scope, config, rows in [
            ("baseline", baseline, baseline_rows),
            ("in_sample_f2", best, best_rows),
            ("in_sample_f1", best_f1, config_rows(records, best_f1, args.videos)),
            (
                "in_sample_recall_priority",
                best_recall,
                config_rows(records, best_recall, args.videos),
            ),
            ("held_out_f2", {}, held_out),
            ("held_out_f1", {}, alternative_held_out["best_f1"]),
            ("held_out_recall_priority", {}, alternative_held_out["recall_priority"]),
        ]:
            agg = aggregate(rows)
            writer.writerow(
                dict(
                    scope=scope,
                    **config,
                    **{"macro_" + key: agg["macro"][key] for key in metrics},
                    total_event_05_missed_rounds=sum(
                        row["event_05_missed_rounds"] for row in rows
                    ),
                    total_coverage_zero_missed_rounds=sum(
                        row["coverage_zero_missed_rounds"] for row in rows
                    ),
                    total_coverage_05_missed_rounds=sum(
                        row["coverage_05_missed_rounds"] for row in rows
                    ),
                )
            )
    write_json(
        args.output / "complete.json",
        {
            "status": "complete",
            "summary_sha256": sha256(args.output / "summary.json"),
            "rows": len(records),
            "elapsed_seconds": time.monotonic() - started,
        },
    )
    print(
        f"Wrote {args.output / 'summary.json'}; elapsed {summary['elapsed_seconds']:.1f}s",
        flush=True,
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--videos", nargs="+", default=DEFAULT_VIDEOS)
    parser.add_argument("--top-k-min", type=int, default=30)
    parser.add_argument("--top-k-max", type=int, default=200)
    parser.add_argument("--interval-step", type=float, default=0.25)
    args = parser.parse_args()
    if not 1 <= args.top_k_min <= args.top_k_max <= 200:
        parser.error("Top K bounds must satisfy 1 <= min <= max <= 200")
    if not math.isfinite(args.interval_step) or not 0 < args.interval_step <= 9:
        parser.error("Interval step must be finite and between 0 and 9")
    if len(set(args.videos)) != len(args.videos) or len(args.videos) < 2:
        parser.error("At least two distinct video IDs required for leave-one-video-out")
    run(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Export common-parameter, GPU-free review metadata from a completed search."""

import argparse
import json
from pathlib import Path

from evaluate_grid import ROOT, load_module, read_rows, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument(
        "--policy",
        choices=[
            "in_sample_best",
            "best_f1_alternative",
            "recall_priority_alternative",
        ],
        required=True,
    )
    args = parser.parse_args()
    summary_path = args.evaluation / "summary.json"
    marker = json.loads((args.evaluation / "complete.json").read_text())
    if marker["summary_sha256"] != sha256(summary_path):
        raise ValueError("Evaluation is incomplete or summary was modified")
    summary = json.loads(summary_path.read_text())
    parameters = summary[args.policy]["parameters"]
    for key, path in {
        "postprocess": ROOT
        / "services/algorithm/vendor/ftt/code/postprocess_rallies.py",
        "scores": ROOT / "services/algorithm/src/rallymark_algorithm/scores.py",
    }.items():
        if sha256(path) != summary["code_sha256"][key]:
            raise ValueError(f"{key} changed since evaluation; rerun the search")
    post = load_module(
        "review_postprocess",
        ROOT / "services/algorithm/vendor/ftt/code/postprocess_rallies.py",
    )
    scores = load_module(
        "review_scores", ROOT / "services/algorithm/src/rallymark_algorithm/scores.py"
    )
    manifest = {
        "policy": args.policy,
        "parameters": parameters,
        "evaluation_sha256": sha256(summary_path),
        "videos": [],
    }
    for video_id in summary["videos"]:
        base = args.experiment / "raw" / video_id
        tad_path, ocr_path = (
            base / "tad/predictions.json",
            base / "ocr/predictions.json",
        )
        for kind, path in [("tad", tad_path), ("ocr", ocr_path)]:
            if sha256(path) != summary["input_provenance"][video_id][kind]["sha256"]:
                raise ValueError(f"{video_id}: {kind} changed since evaluation")
        tad, ocr = read_rows(tad_path), read_rows(ocr_path)
        raw = json.loads(tad_path.read_text())
        fused = post.postprocess(tad, ocr, **parameters)
        timing = [
            {"start_s": r["start_s"], "end_s": r["end_s"]} for r in fused["rallies"]
        ]
        rallies = scores.enrich_scores(timing, fused["rallies"], ocr)
        # GT contributes title only; neither timing nor score labels enter output.
        title = json.loads(
            (args.experiment / "gt" / f"{video_id}.json").read_text()
        ).get("title", video_id)
        warnings = [] if ocr else ["比分 OCR 未产生有效区间，本结果仅使用 TAD。"]
        layout_path = args.experiment / "layout" / f"{video_id}.json"
        if layout_path.exists():
            warning = json.loads(layout_path.read_text()).get("warning")
            if warning:
                warnings.append(warning)
        output = args.experiment / "review" / f"{video_id}.json"
        video_path = args.experiment / "videos" / f"{video_id}.mp4"
        write_json(
            output,
            {
                "title": title,
                "duration_s": raw["duration_s"],
                "source_size_bytes": video_path.stat().st_size,
                "source_sha256": sha256(video_path),
                "warnings": warnings,
                "parameters": parameters,
                "selection_policy": args.policy,
                "rallies": rallies,
                "fusion": fused,
                "input_provenance": summary["input_provenance"][video_id],
            },
        )
        manifest["videos"].append(
            {
                "id": video_id,
                "title": title,
                "video": f"../videos/{video_id}.mp4",
                "metadata": output.name,
                "metadata_sha256": sha256(output),
                "rallies": len(rallies),
            }
        )
    write_json(args.experiment / "review/manifest.json", manifest)
    write_json(
        args.experiment / "review/recommended.json",
        {
            "parameters": parameters,
            "selection_policy": args.policy,
            "note": "Common in-sample recommendation; consult held-out metrics before generalizing.",
        },
    )
    print(json.dumps(parameters))


if __name__ == "__main__":
    main()

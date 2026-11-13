#!/usr/bin/env python3
"""Import a completed FTT experiment and verify the production adapter, without GPU."""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/algorithm/src"))
from rallymark_algorithm.runner import fuse_predictions, validate_rallies
from rallymark_algorithm.scores import enrich_scores
from rallymark_algorithm.settings import AlgorithmConfig


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if source == output or source in output.parents:
        parser.error("Source and output must be separate directories")
    shutil.copytree(
        source,
        output,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("videos", "frames*", "__pycache__"),
    )
    params = read(source / "best_config.json")
    config = AlgorithmConfig(
        **{("tad_top_k" if k == "top_k" else k): v for k, v in params.items()}
    )
    snapshot = config.model_dump(
        exclude={"version", "lease_seconds", "max_attempts", "runner"}
    )
    settings = SimpleNamespace(ftt_root=ROOT / "services/algorithm/vendor/ftt")
    verified = []
    for video in read(source / "dataset.json")["videos"]:
        key = video["id"]
        original = source / video["file"]
        if (
            original.stat().st_size != video["bytes"]
            or sha256(original) != video["sha256"]
        ):
            raise ValueError(f"Video binding mismatch: {key}")
        destination = output / video["file"]
        destination.parent.mkdir(exist_ok=True)
        if not destination.exists():
            try:
                os.link(original, destination)
            except OSError:
                shutil.copyfile(original, destination)
        base = source / "raw" / key
        tad = read(base / "tad/predictions.json")["rallies"]
        ocr = read(base / "ocr/predictions.json")["rallies"]
        fused = fuse_predictions(
            settings,
            snapshot,
            tad,
            ocr,
            video["duration_s"],
            read(base / "ocr/observations.json"),
        )
        expected = read(source / f"predictions/{key}.json")
        if fused != expected:
            raise ValueError(f"Product adapter differs from FTT: {key}")
        normalized = validate_rallies(fused["rallies"], video["duration_s"])
        rallies = enrich_scores(normalized, fused["rallies"], ocr)
        for actual, raw in zip(rallies, expected["rallies"], strict=True):
            if (actual["score"], actual["score_status"]) != (
                raw["score_label"],
                raw["score_status"],
            ):
                raise ValueError(f"Score adaptation mismatch: {key}")
        previous = read(base / "previous.json")
        metadata = {
            "title": previous.get("title", key),
            "duration_s": video["duration_s"],
            "source_size_bytes": video["bytes"],
            "source_sha256": video["sha256"],
            "parameters": params,
            "algorithm_version": config.version,
            "selection_policy": "six_match_development_score_constraints",
            "warnings": fused.get("score_constraints", {}).get("warnings", []),
            "rallies": rallies,
        }
        path = output / "review" / f"{key}.json"
        write(path, metadata)
        verified.append(
            {
                "id": key,
                "metadata": path.name,
                "metadata_sha256": sha256(path),
                "rallies": len(rallies),
            }
        )
    write(
        output / "review/manifest.json",
        {"parameters": params, "algorithm_version": config.version, "videos": verified},
    )
    write(
        output / "adapter-verification.json",
        {
            "ftt_commit": "c836c83bbbfa0327a25f6cb6077cafa83bb69f10",
            "algorithm_version": config.version,
            "exact_match": True,
            "videos": verified,
        },
    )
    print(
        json.dumps(
            {"verified": len(verified), "rallies": sum(r["rallies"] for r in verified)}
        )
    )


if __name__ == "__main__":
    main()

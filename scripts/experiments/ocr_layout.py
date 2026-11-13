#!/usr/bin/env python3
"""Locate the existing OCR crop using broadcast pixels, without annotations.

Only horizontal translation is supported, for the existing 1920x1080 layout.
This script writes layout metadata only; callers retain their baseline OCR
artifacts and extract a separate frame set using the returned crop_xywh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

BASELINE_X = 85
CROP_Y = 915
CROP_WIDTH = 540
CROP_HEIGHT = 120
MAGENTA_X = 415
MAGENTA_Y0 = 15
MAGENTA_Y1 = 110
WINDOW_WIDTH = 53
MAX_CROP_X = 150
MIN_CROP_X = -85
MIN_OCCUPANCY = 0.50
SAMPLE_COUNT = 12
SAMPLE_HORIZON_S = 60.0
MIN_VISIBLE_SAMPLES = 3  # Existing OCR's repeated-observation requirement.


def detect_frame_layout(frame: np.ndarray) -> dict:
    """Return the best 53px magenta window and its associated OCR crop X."""
    if frame.shape != (1080, 1920, 3):
        raise ValueError(f"Expected 1920x1080 BGR frame, got {frame.shape}")
    region = frame[
        CROP_Y + MAGENTA_Y0 : CROP_Y + MAGENTA_Y1,
        MAGENTA_X + MIN_CROP_X : MAGENTA_X + MAX_CROP_X + WINDOW_WIDTH,
    ].astype(np.float32)
    b, g, r = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    # Identical color predicate to the frozen scoreboard OCR visibility gate.
    mask = (r > 100) & (b > 90) & (r > 1.5 * g) & (b > 1.3 * g)
    columns = mask.mean(axis=0)
    occupancies = np.convolve(
        columns, np.ones(WINDOW_WIDTH) / WINDOW_WIDTH, mode="valid"
    )
    peak = float(occupancies.max())
    tied = (
        np.flatnonzero(np.isclose(occupancies, peak, rtol=0, atol=1e-12)) + MIN_CROP_X
    )
    # Keep the baseline position when several windows are equally plausible.
    x = int(tied[np.argmin(np.abs(tied - BASELINE_X))])
    return {"x": x, "occupancy": peak}


def summarize_layout(samples: list[dict]) -> dict:
    """Use visible samples; replay shots need not contain the overlay."""
    valid = [s for s in samples if s.get("occupancy", 0) >= MIN_OCCUPANCY]
    xs = [s["x"] for s in valid]
    detected_x = round(float(np.median(xs))) if xs else None
    # A shift greater than half a games column is not the same fixed layout.
    stable = [x for x in xs if abs(x - detected_x) <= WINDOW_WIDTH / 2]
    required = max(MIN_VISIBLE_SAMPLES, math.ceil(len(valid) / 2))
    accepted = len(stable) >= required
    warning = None
    if not accepted:
        warning = (
            f"Uncertain magenta layout: {len(valid)}/{len(samples)} visible "
            f"samples, {len(stable)} consistent; using baseline crop X={BASELINE_X}"
        )
    confidence = float(np.median([s["occupancy"] for s in valid])) if valid else 0.0
    return {
        "crop_xywh": [
            detected_x if accepted else BASELINE_X,
            CROP_Y,
            CROP_WIDTH,
            CROP_HEIGHT,
        ],
        "detected_x": detected_x,
        "accepted": accepted,
        "warning": warning,
        "confidence": confidence,
        "all_sample_median_occupancy": float(
            np.median([s.get("occupancy", 0) for s in samples])
        )
        if samples
        else 0.0,
        "stability": {
            "valid_samples": len(valid),
            "consistent_samples": len(stable),
            "total_samples": len(samples),
            "x_min": min(xs) if xs else None,
            "x_max": max(xs) if xs else None,
            "x_mad_px": float(np.median(np.abs(np.array(xs) - detected_x)))
            if xs
            else None,
            "search_boundary_hit": detected_x in (MIN_CROP_X, MAX_CROP_X),
        },
        "samples": samples,
    }


def detect_video_layout(video: str | Path) -> dict:
    """Sample 12 evenly spaced bin centers in the video's first 60 seconds."""
    video = Path(video)
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video}")
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0:
            raise ValueError(f"Cannot determine video duration: {video}")
        horizon = min(SAMPLE_HORIZON_S, frame_count / fps)
        samples = []
        for time_s in (np.arange(SAMPLE_COUNT) + 0.5) * horizon / SAMPLE_COUNT:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(time_s * 1000))
            ok, frame = cap.read()
            sample = {"time_s": round(float(time_s), 6)}
            if ok:
                sample.update(detect_frame_layout(frame))
            else:
                sample.update(x=None, occupancy=0.0, warning="Frame decode failed")
            samples.append(sample)
        result = summarize_layout(samples)
        result.update(
            schema_version=1,
            video=video.name,
            method="magenta_occupancy_horizontal_translation",
            parameters={
                "sample_count": SAMPLE_COUNT,
                "sample_horizon_s": SAMPLE_HORIZON_S,
                "actual_sample_horizon_s": horizon,
                "magenta_relative_xyxy": [415, 15, 468, 110],
                "crop_x_search_inclusive": [MIN_CROP_X, MAX_CROP_X],
                "minimum_occupancy": MIN_OCCUPANCY,
                "minimum_visible_samples": MIN_VISIBLE_SAMPLES,
                "minimum_consistent_samples": max(
                    MIN_VISIBLE_SAMPLES,
                    math.ceil(result["stability"]["valid_samples"] / 2),
                ),
                "consistency_radius_px": WINDOW_WIDTH / 2,
                "baseline_crop_xywh": [85, 915, 540, 120],
            },
        )
        return result
    finally:
        cap.release()


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crop_filter(x: int) -> str:
    """Translate the existing crop; pad missing source pixels on its left."""
    padding = f"pad=iw+{-x}:ih:{-x}:0," if x < 0 else ""
    return f"fps=2,{padding}crop=540:120:{max(0, x)}:915"


def rerun_ocr(video: Path, raw: Path, ocr_script: Path, python: str) -> dict:
    """Preserve frozen OCR and write a separately identifiable calibrated run.

    A completed raw TAD result and baseline predictions are required. For the
    active batch, call only after its complete.json appears. An existing Nina
    reference can be imported as completed input before calling this function.
    """
    if not (raw / "tad/predictions.json").is_file():
        raise ValueError(f"Raw TAD is not complete: {raw}")
    baseline = raw / "ocr_fixed"
    output = raw / "ocr"
    if not baseline.exists():
        if not (output / "predictions.json").is_file():
            raise ValueError(f"Baseline OCR predictions missing: {output}")
        output.rename(baseline)
    completed = output / "layout_calibration.json"
    if completed.is_file():
        return json.loads(completed.read_text())
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    layout = detect_video_layout(video)
    (raw / "layout.json").write_text(json.dumps(layout, indent=2) + "\n")
    frames = output / "frames"
    frames.mkdir(exist_ok=True)
    extraction_started = time.perf_counter()
    with (output / "pipeline.log").open("w") as log:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(video),
                "-vf",
                crop_filter(layout["crop_xywh"][0]),
                "-q:v",
                "2",
                str(frames / "%06d.jpg"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
        extraction_seconds = time.perf_counter() - extraction_started
        ocr_started = time.perf_counter()
        env = dict(os.environ, CUDA_VISIBLE_DEVICES="")
        process = subprocess.run(
            [python, str(ocr_script), "--frames", str(frames), "--out", str(output)],
            check=False,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        ocr_seconds = time.perf_counter() - ocr_started
    predictions = output / "predictions.json"
    if not predictions.is_file():
        raise RuntimeError(
            f"OCR produced no predictions; inspect {output / 'pipeline.log'}"
        )
    result = json.loads(predictions.read_text())
    # Original runner writes its hard-coded crop into metadata, even though it
    # consumes external crops. Correct that provenance without changing rallies.
    result["metadata"].update(
        crop_xywh=layout["crop_xywh"],
        horizontal_layout_calibration="../layout.json",
    )
    predictions.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    record = {
        "video": video.name,
        "video_sha256": checksum(video),
        "layout": layout,
        "ffmpeg_filter": crop_filter(layout["crop_xywh"][0]),
        "frame_extraction_seconds": extraction_seconds,
        "ocr_wall_seconds": ocr_seconds,
        "total_seconds": time.perf_counter() - started,
        "ocr_exit_code": process.returncode,
        "rallies": len(result["rallies"]),
        "ocr_script_sha256": checksum(ocr_script),
        "layout_script_sha256": checksum(Path(__file__)),
        "baseline_predictions_sha256": checksum(baseline / "predictions.json"),
        "predictions_sha256": checksum(predictions),
        "gt_used_for_inference": False,
    }
    # The frozen OCR CSV writer exits nonzero for zero rallies after writing
    # valid JSON artifacts; retain its exit code explicitly in the record.
    if process.returncode and result["rallies"]:
        raise RuntimeError(f"OCR exited {process.returncode}; inspect pipeline.log")
    completed.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rerun-ocr", type=Path, metavar="RAW_DIRECTORY")
    parser.add_argument("--ocr-script", type=Path)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    if args.rerun_ocr:
        if not args.ocr_script:
            parser.error("--rerun-ocr requires --ocr-script")
        result = rerun_ocr(args.video, args.rerun_ocr, args.ocr_script, args.python)
    else:
        result = detect_video_layout(args.video)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()

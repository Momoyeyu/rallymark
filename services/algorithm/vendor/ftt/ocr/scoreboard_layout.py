"""Pixel-only horizontal calibration for the supported 1080p broadcast layout.

Promoted from the frozen six-match experiment; no annotations are used.
"""

import math
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


def crop_filter(x: int) -> str:
    """Translate the existing crop; pad missing source pixels on its left."""
    padding = f"pad=iw+{-x}:ih:{-x}:0," if x < 0 else ""
    return f"fps=2,{padding}crop=540:120:{max(0, x)}:915"

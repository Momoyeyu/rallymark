#!/usr/bin/env python3
"""Scoreboard-only rally baseline for 15_raw.MP4.

This script never reads the rally ground truth. It uses the broadcast score
overlay to detect point increments, then applies fixed timing heuristics to
produce rally proposals. Run the existing evaluate_rallies.py separately.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from importlib.metadata import version
from pathlib import Path

import cv2
import numpy as np
import onnx
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from ftt_score_rules import valid_score, legal_step, is_terminal


FPS = 2.0
FRAME_CROP = (85, 915, 540, 120)  # x, y, width, height in 1920x1080 frame
MAGENTA_CROP = (415, 15, 468, 110)  # x0,y0,x1,y1 within FRAME_CROP
SCORE_CROP = (465, 5, 535, 110)
VISIBILITY_FRACTION = 0.50
OCR_CONFIDENCE = 0.50
STABLE_SAMPLES = 3
STABLE_HORIZON = 6  # observations, i.e. <= 3 s
NORMAL_SCORE_LAG_S = 0.75
FIRST_APPEARANCE_LAG_S = 2.0
RALLY_DURATION_S = 4.5


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def onnx_constant_elements(path: Path) -> int:
    """Count serialized constants; mostly weights, not trainable-param metadata."""
    model = onnx.load(str(path), load_external_data=False)
    count = sum(math.prod(t.dims) for t in model.graph.initializer)
    for node in model.graph.node:
        if node.op_type == "Constant":
            count += sum(math.prod(attr.t.dims) for attr in node.attribute
                         if attr.type == onnx.AttributeProto.TENSOR)
    return count


def score_visible(frame: np.ndarray) -> tuple[bool, float]:
    x0, y0, x1, y1 = MAGENTA_CROP
    b, g, r = cv2.split(frame[y0:y1, x0:x1].astype(np.float32))
    mask = (r > 100) & (b > 90) & (r > 1.5 * g) & (b > 1.3 * g)
    fraction = float(np.mean(mask))
    return fraction >= VISIBILITY_FRACTION, fraction


def read_score(ocr: RapidOCR, frame: np.ndarray) -> tuple[tuple[int, int] | None, float]:
    x0, y0, x1, y1 = SCORE_CROP
    results, _ = ocr(frame[y0:y1, x0:x1])
    rows: dict[str, tuple[int, float]] = {}
    for box, raw, confidence in results or []:
        value = raw.strip()
        if not re.fullmatch(r"\d{1,3}", value) or float(confidence) < OCR_CONFIDENCE:
            continue
        digit = int(value)
        center_y = sum(float(p[1]) for p in box) / 4
        label = "top" if center_y < 55 else "bottom"
        if label not in rows or rows[label][1] < confidence:
            rows[label] = (digit, float(confidence))
    if len(rows) != 2:
        return None, 0.0
    return (rows["top"][0], rows["bottom"][0]), min(rows["top"][1], rows["bottom"][1])


def stable_states(observations: list[dict]) -> list[dict]:
    """Accept a state only after three agreeing OCR reads in a 3 s window."""
    states: list[dict] = []
    for i, row in enumerate(observations):
        if row["score"] is None:
            continue
        recent = observations[max(0, i - STABLE_HORIZON + 1):i + 1]
        agreeing = [r for r in recent if r["score"] == row["score"]]
        if len(agreeing) < STABLE_SAMPLES:
            continue
        score = tuple(row["score"])
        if not valid_score(score):
            continue
        if states and states[-1]["score"] == list(score):
            states[-1]["last_seen_s"] = row["t_s"]
            continue
        first = agreeing[-STABLE_SAMPLES]["t_s"]
        states.append({"score": list(score), "first_seen_s": first,
                       "confirmed_s": row["t_s"], "last_seen_s": row["t_s"],
                       "ocr_confidence": round(float(np.median([r["ocr_confidence"] for r in agreeing])), 4)})
    # A replay may flash an old score. Keep only strictly legal, one-point increments.
    accepted: list[dict] = []
    for state in states:
        if not accepted:
            accepted.append(state)
            continue
        top, bottom = state["score"]
        old_top, old_bottom = accepted[-1]["score"]
        if legal_step((old_top, old_bottom), (top, bottom)):
            accepted.append(state)
    # At game point the broadcaster may remove the overlay immediately after
    # updating 11, leaving only one sampled frame. This rule uses the visible
    # score and the ensuing absence of OCR, never the rally annotation.
    if accepted:
        old_top, old_bottom = accepted[-1]["score"]
        tail = [r for r in observations if r["t_s"] > accepted[-1]["last_seen_s"]
                and r["score"] is not None]
        if len(tail) == 1:
            row = tail[0]
            top, bottom = row["score"]
            next_window = [r for r in observations if row["t_s"] < r["t_s"] <= row["t_s"] + 5]
            game_over = is_terminal((top, bottom))
            if legal_step((old_top, old_bottom), (top, bottom)) \
                    and game_over and row["ocr_confidence"] >= 0.95 \
                    and sum(not r["visible"] for r in next_window) >= 4:
                accepted.append({"score": row["score"], "first_seen_s": row["t_s"],
                                 "confirmed_s": row["t_s"], "last_seen_s": row["t_s"],
                                 "ocr_confidence": row["ocr_confidence"],
                                 "terminal_game_point_single_frame": True})
    return accepted


def proposals(states: list[dict], duration_s: float) -> list[dict]:
    points: list[dict] = []
    if states:
        top, bottom = states[0]["score"]
        # If the initial 0:0 overlay is absent in the intro, the first
        # observed 0:1 or 1:0 still implies one completed point.
        if (top, bottom) in {(0, 1), (1, 0)}:
            points.append({"change_s": states[0]["first_seen_s"],
                           "pre_score": [0, 0], "post_score": [top, bottom],
                           "confidence": states[0]["ocr_confidence"],
                           "first_appearance": True})
    for previous, current in zip(states, states[1:]):
        points.append({"change_s": current["first_seen_s"],
                       "pre_score": previous["score"], "post_score": current["score"],
                       "confidence": current["ocr_confidence"],
                       "first_appearance": False})
    out = []
    for point in points:
        lag = FIRST_APPEARANCE_LAG_S if point["first_appearance"] else NORMAL_SCORE_LAG_S
        end = max(0.0, point["change_s"] - lag)
        start = max(0.0, end - duration_s)
        # GT notation is Kuai:Nina; overlay positions are Nina (top), Kuai (bottom).
        top, bottom = point["pre_score"]
        out.append({"start_s": round(start, 3), "end_s": round(end, 3),
                    "score": round(point["confidence"], 4),
                    "pre_score_kuai_nina": f"{bottom}:{top}",
                    "score_change_s": point["change_s"],
                    "post_score_top_bottom": point["post_score"],
                    "first_appearance": point["first_appearance"]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=Path, required=True, help="ffmpeg 2 fps 540x120 crops")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-observations", action="store_true",
                        help="Reapply score-state rules to previously saved OCR reads")
    parser.add_argument("--execution-provider", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    started = time.perf_counter()
    args.out.mkdir(parents=True, exist_ok=True)
    images = sorted(args.frames.glob("*.jpg"))
    if not images:
        raise SystemExit("No extracted frames")
    if args.reuse_observations:
        observations = json.loads((args.out / "observations.json").read_text())
        if len(observations) != len(images):
            raise RuntimeError("Cached OCR frame count does not match extracted frames")
    else:
        use_cuda = args.execution_provider == "cuda"
        ocr = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=1,
                       det_use_cuda=use_cuda, cls_use_cuda=use_cuda, rec_use_cuda=use_cuda)
        execution_providers = {}
        for name in ["text_det", "text_cls", "text_rec"]:
            engine = getattr(ocr, name)
            holder = getattr(engine, "infer", getattr(engine, "session", None))
            session = holder.session
            providers = session.get_providers()
            execution_providers[name] = providers
            if use_cuda and providers[0] != "CUDAExecutionProvider":
                raise RuntimeError(f"{name} did not enable requested CUDA execution provider")
        observations = []
        for index, path in enumerate(images):
            frame = cv2.imread(str(path))
            if frame is None or frame.shape[:2] != (120, 540):
                raise RuntimeError(f"Bad frame: {path}")
            visible, fraction = score_visible(frame)
            score, confidence = read_score(ocr, frame) if visible else (None, 0.0)
            observations.append({"t_s": round(index / FPS, 3), "visible": visible,
                                 "magenta_fraction": round(fraction, 4),
                                 "score": list(score) if score else None,
                                 "ocr_confidence": round(confidence, 4)})
    states = stable_states(observations)
    rallies = proposals(states, RALLY_DURATION_S)
    model_dir = Path(__import__("rapidocr_onnxruntime").__file__).parent / "models"
    models = {p.name: {"bytes": p.stat().st_size, "sha256": checksum(p),
                       "onnx_constant_elements": onnx_constant_elements(p)}
              for p in sorted(model_dir.glob("*.onnx"))}
    metadata = {"method": "broadcast scoreboard visibility + RapidOCR digits + fixed timing",
                "rapidocr_version": version("rapidocr-onnxruntime"), "frames": len(images),
                "onnx_intra_threads": 4, "onnx_inter_threads": 1,
                "sample_fps": FPS, "crop_xywh": FRAME_CROP,
                "visibility_fraction": VISIBILITY_FRACTION,
                "ocr_confidence": OCR_CONFIDENCE,
                "stable_samples": STABLE_SAMPLES, "stable_horizon_samples": STABLE_HORIZON,
                "normal_score_lag_s": NORMAL_SCORE_LAG_S,
                "first_appearance_lag_s": FIRST_APPEARANCE_LAG_S,
                "assumed_rally_duration_s": RALLY_DURATION_S,
                "terminal_game_point_rule": "single high-confidence legal game-winning update followed by >=4 absent overlay samples in 5 s",
                "execution_provider": args.execution_provider,
                "session_providers": execution_providers if not args.reuse_observations else {},
                "cpu_wall_seconds": round(time.perf_counter() - started, 3),
                "models": models, "vlm_tokens": 0, "gt_used_for_inference": False}
    (args.out / "observations.json").write_text(json.dumps(observations, ensure_ascii=False, indent=2))
    (args.out / "score_states.json").write_text(json.dumps(states, ensure_ascii=False, indent=2))
    (args.out / "predictions.json").write_text(json.dumps({"metadata": metadata, "rallies": rallies}, ensure_ascii=False, indent=2))
    with (args.out / "rallies.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rallies[0]) if rallies else ["start_s", "end_s", "score"])
        writer.writeheader()
        writer.writerows(rallies)
    print(json.dumps({"visible_frames": sum(o["visible"] for o in observations),
                      "valid_ocr_frames": sum(o["score"] is not None for o in observations),
                      "states": len(states), "rallies": len(rallies),
                      "models": models}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Validation decoding for original-video, two-level sports TriDet.

Window candidates are mapped to physical clip time before per-video NMS.
All windows in the validation split are retained; no test media are loaded.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

from opentad.evaluations.mAP import mAP
from opentad.models.utils.post_processing import batched_nms


@torch.no_grad()
def decode_window(head, prediction, meta, *, topk, min_score=.001):
    points, offsets, scores = prediction
    if scores.shape[0] != 1:
        raise ValueError("decode_window expects one video window")
    score = scores[0]
    n_points, n_classes = score.shape
    values, indexes = torch.topk(score.reshape(-1), min(topk, score.numel()))
    keep = values >= min_score
    values, indexes = values[keep], indexes[keep]
    pos = torch.div(indexes, n_classes, rounding_mode="floor")
    cls = indexes.remainder(n_classes)
    if pos.numel() == 0:
        return []
    intervals = head.get_proposals(points[pos], offsets[0, cls, pos])
    valid_length = meta["end_frame"] - meta["start_frame"]
    intervals = intervals.clamp(0, valid_length)
    keep = intervals[:, 1] > intervals[:, 0]
    intervals = ((intervals[keep] + meta["start_frame"]) / meta["fps"]).cpu()
    values, cls = values[keep].cpu(), cls[keep].cpu()
    return [(float(a), float(b), int(c), float(s))
            for (a, b), c, s in zip(intervals.tolist(), cls.tolist(), values.tolist())]


def finish_predictions(rows_by_video, class_names, *, max_segments):
    results = {}
    for video_id, rows in rows_by_video.items():
        if rows:
            intervals = torch.tensor([x[:2] for x in rows], dtype=torch.float32)
            labels = torch.tensor([x[2] for x in rows], dtype=torch.long)
            scores = torch.tensor([x[3] for x in rows], dtype=torch.float32)
            intervals, scores, labels = batched_nms(
                intervals, scores, labels, sigma=.5, min_score=.001,
                max_seg_num=max_segments, use_soft_nms=True, multiclass=True)
            results[video_id] = [dict(segment=[float(a), float(b)],
                                      label=class_names[int(c)], score=float(s))
                                 for (a, b), c, s in zip(intervals.tolist(),
                                                          labels.tolist(), scores.tolist())]
        else:
            results[video_id] = []
    return {"results": results}


@torch.no_grad()
def decode_relation_rows(relation, meta):
    """Serialize soft-link choices on predicted nodes in video seconds."""
    a_seg, a_cls, a_scores, _ = relation["actions"]
    r_seg, r_cls, r_scores, _ = relation["parents"]
    probabilities = relation["relation_probabilities"]
    valid_length = meta["end_frame"] - meta["start_frame"]

    def video_row(segment, label, score):
        left, right = segment.clamp(0, valid_length).tolist()
        return [(left + meta["start_frame"]) / meta["fps"],
                (right + meta["start_frame"]) / meta["fps"],
                int(label), float(score)]

    parents = [video_row(seg, cls, score)
               for seg, cls, score in zip(r_seg, r_cls, r_scores)]
    rows = []
    for i, (seg, cls, score) in enumerate(zip(a_seg, a_cls, a_scores)):
        action = video_row(seg, cls, score)
        if action[1] <= action[0]:
            continue
        choice = int(probabilities[i].argmax())
        parent = parents[choice] if choice < len(parents) else None
        rows.append(dict(action=action, parent=parent,
                         probability=float(probabilities[i, choice])))
    return rows


def _temporal_iou(a, b):
    overlap = max(0., min(a[1], b[1]) - max(a[0], b[0]))
    return overlap / max(1e-8, (a[1]-a[0]) + (b[1]-b[0]) - overlap)


def _best_gt(pred, annotations, expected_label, threshold):
    candidates = [(i, _temporal_iou(pred["segment"], a["segment"]))
                  for i, a in enumerate(annotations)
                  if a["label_id"] == expected_label]
    if not candidates:
        return -1
    idx, value = max(candidates, key=lambda item: item[1])
    return idx if value >= threshold else -1


def evaluate_relation_edges(annotation_root, per_window, final_actions, final_parents, *, subset="validation"):
    """End-to-end edge P/R/F1 after final per-video detector NMS.

    Learned links cover the selected 256/64 nodes per window. A final action
    outside that budget receives the fixed geometry fallback (coverage >=.5).
    This fallback count is reported so the learned component is not overstated.
    """
    root = Path(annotation_root)
    action_gt = json.loads((root / "fine_annotations.json").read_text())["database"]
    parent_gt = json.loads((root / "coarse_annotations.json").read_text())["database"]
    action_names = (root / "fine_class_map.txt").read_text().splitlines()
    parent_names = (root / "coarse_class_map.txt").read_text().splitlines()
    action_label = {name: idx for idx, name in enumerate(action_names)}
    parent_label = {name: idx for idx, name in enumerate(parent_names)}
    relation_index = defaultdict(list)
    seen = set()
    for window in per_window:
        key = (window["video_id"], window["start_frame"], window["end_frame"])
        if key in seen:
            continue
        seen.add(key)
        relation_index[window["video_id"]].extend(window.get("relations", []))

    edges = []
    fallback_actions = 0
    selected_actions = 0
    for video_id, actions in final_actions["results"].items():
        parents = final_parents["results"].get(video_id, [])
        for action in actions:
            label_id = action_label[action["label"]]
            matches = [row for row in relation_index[video_id]
                       if row["action"][2] == label_id and
                       _temporal_iou(row["action"][:2], action["segment"]) >= .999]
            parent = None
            probability = 1.
            if matches:
                selected_actions += 1
                chosen = max(matches, key=lambda row: row["action"][3])
                probability = chosen["probability"]
                if chosen["parent"] is not None:
                    p = chosen["parent"]
                    candidates = [(row, _temporal_iou(p[:2], row["segment"]))
                                  for row in parents if parent_label[row["label"]] == p[2]]
                    if candidates:
                        best, overlap = max(candidates, key=lambda pair: pair[1])
                        if overlap >= .5:
                            parent = best
            else:
                fallback_actions += 1
                candidates = [(row, max(0., min(action["segment"][1], row["segment"][1]) -
                                             max(action["segment"][0], row["segment"][0])) /
                                   max(1e-8, action["segment"][1] - action["segment"][0]))
                              for row in parents]
                if candidates:
                    best, coverage = max(candidates, key=lambda pair: (pair[1], pair[0]["score"]))
                    if coverage >= .5:
                        parent = best
            if parent is not None:
                confidence = action["score"] * parent["score"] * probability
                edges.append((confidence, video_id, action, parent))

    gt_count = sum(len(row["annotations"]) for row in action_gt.values()
                   if row["subset"] == subset)
    results = {}
    for threshold in (.3, .4, .5, .6, .7):
        used = set()
        tp = fp = 0
        for _, video_id, action, parent in sorted(edges, key=lambda row: row[0], reverse=True):
            fine = action_gt[video_id]["annotations"]
            coarse = parent_gt[video_id]["annotations"]
            ai = _best_gt(action, fine, action_label[action["label"]], threshold)
            ri = _best_gt(parent, coarse, parent_label[parent["label"]], threshold)
            key = (video_id, fine[ai]["instance_id"]) if ai >= 0 else None
            good = (ai >= 0 and ri >= 0 and
                    fine[ai]["parent_instance_id"] == coarse[ri]["instance_id"] and
                    key not in used)
            if good:
                tp += 1
                used.add(key)
            else:
                fp += 1
        fn = gt_count - tp
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        results[f"{threshold:.1f}"] = dict(
            precision=100*precision, recall=100*recall,
            f1=100*2*precision*recall/max(1e-8, precision+recall),
            tp=tp, fp=fp, fn=fn)
    return dict(by_tiou=results, gt_edges=gt_count,
                predicted_edges=len(edges), selected_actions=selected_actions,
                geometry_fallback_actions=fallback_actions,
                protocol="final NMS detections; selected soft links and geometry fallback")


def evaluate_predictions(annotation_root, per_window, out_dir):
    annotation_root, out_dir = Path(annotation_root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    merged = {task: defaultdict(list) for task in ("coarse", "fine")}
    seen = set()
    for item in per_window:
        key = (item["video_id"], item["start_frame"], item["end_frame"])
        if key in seen:
            continue  # DDP DistributedSampler may pad the final rank.
        seen.add(key)
        for task in ("coarse", "fine"):
            merged[task][item["video_id"]].extend(item[task])
    outputs = {}
    final = {}
    for task, budget in (("coarse", 200), ("fine", 500)):
        names = (annotation_root / f"{task}_class_map.txt").read_text().splitlines()
        pred = finish_predictions(merged[task], names, max_segments=budget)
        final[task] = pred
        path = out_dir / f"{task}_validation_predictions.json"
        path.write_text(json.dumps(pred))
        evaluator = mAP(str(annotation_root / f"opentad_{task}.json"), pred,
                        subset="validation", tiou_thresholds=np.linspace(.3, .7, 5), thread=4)
        outputs[task] = {k: 100 * float(v) for k, v in evaluator.evaluate().items()}
    outputs["validation_windows"] = len(seen)
    outputs["test_accessed"] = False
    if any(item.get("relations") for item in per_window):
        outputs["relation"] = evaluate_relation_edges(
            annotation_root, per_window, final["fine"], final["coarse"])
    return outputs

#!/usr/bin/env python3
"""Run the final FTT two-level checkpoint on one unannotated original video."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import threading
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENTAD = ROOT / "third_party/OpenTAD"
sys.path.insert(0, str(OPENTAD))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from mmengine import Config

import opentad.datasets  # noqa: F401 - register OpenTAD components
from sports_dual_adapter_model import SportsDualAdapterTriDet
from sports_e2e_pair_data import frame_windows, video_dimensions
from sports_e2e_validation import decode_window, finish_predictions

NAMES = {
    1: "顺旋转发球", 2: "逆旋转发球", 3: "反手发球", 4: "勾手发球", 5: "下蹲发球",
    6: "正手搓球", 7: "正手挑球", 8: "正手扣球", 9: "正手拉球", 10: "正手削球",
    11: "正手放高球", 12: "正手防守", 13: "反手搓球", 14: "反手挑球", 15: "反手拧",
    16: "反手拉球", 17: "反手切", 18: "反手削球", 19: "反手放高球", 20: "反手防",
}


def probe(path):
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_frames,duration",
        "-show_entries", "format=duration", "-of", "json", str(path)], text=True))
    stream = data["streams"][0]
    return float(Fraction(stream["avg_frame_rate"])), stream


_readers = threading.local()

def decode(path, start, end, height, width, *, reuse=False):
    import decord
    short = min(height, width)
    out_h = max(160, round(height * 160 / short))
    out_w = max(160, round(width * 160 / short))
    idx = np.arange(start, end, dtype=np.int64)
    if len(idx) < 768:
        idx = np.pad(idx, (0, 768-len(idx)), constant_values=end-1)
    for attempt in range(3):
        try:
            key = (str(path), out_w, out_h)
            cached = getattr(_readers, 'entry', None)
            reader = cached[1] if reuse and cached and cached[0] == key else decord.VideoReader(str(path), width=out_w, height=out_h, num_threads=2)
            if reuse:
                _readers.entry = (key, reader)
            if len(reader) < end:
                raise ValueError(f"Decoder has {len(reader)} frames, window ends at {end}")
            frames = reader.get_batch(idx).asnumpy()
            del reader
            break
        except decord.DECORDError:
            _readers.entry = None
            if attempt == 2:
                raise
            time.sleep(.25*(attempt+1))
    top = (out_h-160)//2
    left = (out_w-160)//2
    frames = np.ascontiguousarray(frames[:, top:top+160, left:left+160])
    tensor = torch.from_numpy(frames).permute(3, 0, 1, 2).unsqueeze(0).unsqueeze(0)
    mask = (torch.arange(768) < end-start).unsqueeze(0)
    return tensor, mask


def as_rows(items, task):
    out = []
    for i, item in enumerate(items, 1):
        label = item["label"]
        class_id = int(label.split("_")[1]) if task == "action" else None
        out.append(dict(index=i, start_s=round(item["segment"][0], 3),
                        end_s=round(item["segment"][1], 3),
                        duration_s=round(item["segment"][1]-item["segment"][0], 3),
                        label=label, name=NAMES[class_id] if class_id else "回合",
                        score=round(item["score"], 6)))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=ROOT.parent / "weights/ftt_dual_adapter_seed42_epoch35_trainable.pth")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument('--decoder-mode', choices=['fresh','reuse','prefetch'], default='fresh')
    parser.add_argument('--decode-workers', type=int, default=1)
    parser.add_argument('--prefetch-depth', type=int, default=2)
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--shard-count', type=int, default=1)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    args.video = args.video.resolve()
    fps, meta_stream = probe(args.video)
    import decord
    # Model is imported before Decord to match the working training loader.
    reader = decord.VideoReader(str(args.video), num_threads=2)
    frame_count = len(reader)
    del reader
    height, width = video_dimensions(str(args.video))
    windows = frame_windows(frame_count, length=768, stride=384)
    global_windows = len(windows)
    from window_partition import select_windows
    windows = select_windows(windows, args.shard_index, args.shard_count)
    print("VIDEO", json.dumps(dict(fps=fps, frames=frame_count, seconds=frame_count/fps,
                                   width=width, height=height, windows=len(windows))), flush=True)

    cfg = Config.fromfile(str(OPENTAD / "configs/custom/e2e_thumos_vm2g_vj_prefusion_adapters_8gpu_20261030.py"))
    weights_root = Path(os.environ.get("WEIGHTS_ROOT", str(ROOT.parent / "weights"))).resolve()
    cfg.model.backbone.branches[0].custom.pretrain = str(weights_root / "vit-giant-p14_videomaev2-hybrid_pt_1200e_k710_ft_my.pth")
    cfg.model.backbone.branches[1].backbone.ckpt = str(weights_root / "vjepa2_1_vit_g_kdbd_encoder.pt")
    os.chdir(OPENTAD)
    device = torch.device(args.device)
    torch.cuda.set_device(device)
    model = SportsDualAdapterTriDet(cfg.model.backbone, 1, 20).to(device)
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if (ckpt.get("format"), ckpt.get("dataset"), ckpt.get("seed"), ckpt.get("epoch")) != ("trainable_only_v1", "ftt", 42, 34):
        raise ValueError("Checkpoint is not the final 35-epoch FTT seed42 model")
    trainable = {name for name, p in model.named_parameters() if p.requires_grad}
    if set(ckpt["model_trainable"]) != trainable:
        raise ValueError("Model and checkpoint trainable keys differ")
    model.load_state_dict(ckpt["model_trainable"], strict=False)
    model.eval()
    del ckpt
    torch.cuda.reset_peak_memory_stats(device)

    merged = {"coarse": [], "fine": []}
    began = time.time()
    def decode_item(bounds):
        return decode(args.video, *bounds, height, width, reuse=args.decoder_mode != 'fresh')
    if args.decoder_mode == 'prefetch':
        from window_decode import ordered_prefetch
        decoded = ordered_prefetch(windows, decode_item, args.decode_workers, args.prefetch_depth)
    else:
        decoded = ((bounds, decode_item(bounds)) for bounds in windows)
    with torch.inference_mode():
        for i, ((start, end), (frames, mask)) in enumerate(decoded, 1):
            frames = frames.to(device, non_blocking=True)
            mask = mask.to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                _, coarse_pred, fine_pred = model(frames, mask)
            meta = dict(start_frame=start, end_frame=end, fps=fps)
            merged["coarse"].extend(decode_window(model.coarse_head, coarse_pred, meta, topk=200))
            merged["fine"].extend(decode_window(model.fine_head, fine_pred, meta, topk=500))
            if i == 1 or i % 10 == 0 or i == len(windows):
                print("INFER_WINDOW", i, len(windows), "seconds", round(time.time()-began, 1),
                      "max_gib", round(torch.cuda.max_memory_allocated(device)/2**30, 2), flush=True)

    if args.shard_count > 1:
        (args.output / "raw_predictions.json").write_text(json.dumps(merged))
    ann = ROOT / "data/ftt/sgp_bmp_vm2_20class_v1"
    parent_names = (ann / "coarse_class_map.txt").read_text().splitlines()
    action_names = (ann / "fine_class_map.txt").read_text().splitlines()
    parents = finish_predictions({"video": merged["coarse"]}, parent_names, max_segments=200)["results"]["video"]
    actions = finish_predictions({"video": merged["fine"]}, action_names, max_segments=500)["results"]["video"]
    parents.sort(key=lambda x: x["segment"][0])
    actions.sort(key=lambda x: x["segment"][0])
    rows = {"rallies": as_rows(parents, "rally"), "actions": as_rows(actions, "action")}
    for task, items in rows.items():
        with (args.output / f"{task}_all.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["index", "start_s", "end_s", "duration_s", "label", "name", "score"])
            writer.writeheader()
            writer.writerows(items)
        with (args.output / f"{task}_score_ge_0.3.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["index", "start_s", "end_s", "duration_s", "label", "name", "score"])
            writer.writeheader()
            writer.writerows(x for x in items if x["score"] >= .3)
    summary = dict(video=str(args.video), fps=fps, frames=frame_count,
                   duration_s=frame_count/fps, width=width, height=height,
                   windows=len(windows), global_windows=global_windows,
                   shard_index=args.shard_index, shard_count=args.shard_count, checkpoint=str(args.checkpoint), epoch=35,
                   validation_only_model_selection=True, no_ground_truth=True,
                   decoder_mode=args.decoder_mode, decode_workers=args.decode_workers, prefetch_depth=args.prefetch_depth,
                   inference_seconds=round(time.time()-began, 2),
                   peak_gpu_gib=round(torch.cuda.max_memory_allocated(device)/2**30, 2),
                   counts={task: {"all": len(items), "score_ge_0.3": sum(x["score"] >= .3 for x in items),
                                  "score_ge_0.5": sum(x["score"] >= .5 for x in items)}
                           for task, items in rows.items()}, **rows)
    (args.output / "predictions.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("INFERENCE_DONE", json.dumps({k: summary[k] for k in ("duration_s", "windows", "inference_seconds", "peak_gpu_gib", "counts")}), flush=True)


if __name__ == "__main__":
    main()

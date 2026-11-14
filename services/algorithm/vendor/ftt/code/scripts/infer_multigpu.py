#!/usr/bin/env python3
"""Run original global windows on reserved GPUs; perform one ordered global NMS."""

import argparse
import importlib.util
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def collect_output(children, logs):
    from collections import deque

    lines = queue.Queue()
    tails = [deque(maxlen=32) for _ in children]
    progress = [0] * len(children)
    totals = [None] * len(children)
    threads = []
    failed_at = None

    def read(index, stream):
        for line in stream:
            lines.put((index, line))

    for index, child in enumerate(children):
        thread = threading.Thread(target=read, args=(index, child.stdout), daemon=True)
        thread.start()
        threads.append(thread)
    while (
        any(c.poll() is None for c in children)
        or any(t.is_alive() for t in threads)
        or not lines.empty()
    ):
        if failed_at is None and any(c.poll() not in (None, 0) for c in children):
            failed_at = time.monotonic()
            for child in children:
                if child.poll() is None:
                    child.terminate()
        if failed_at is not None and time.monotonic() - failed_at > 10:
            for child in children:
                if child.poll() is None:
                    child.kill()
        try:
            index, line = lines.get(timeout=0.1)
        except queue.Empty:
            continue
        tails[index].append(line)
        logs[index].write(line)
        logs[index].flush()
        match = re.match(r"INFER_WINDOW\s+(\d+)\s+(\d+)", line)
        if match:
            progress[index], totals[index] = map(int, match.groups())
            if all(t is not None for t in totals):
                print("INFER_WINDOW", sum(progress), sum(totals), flush=True)
    if any(child.returncode for child in children):
        for tail in tails:
            print("".join(tail), flush=True)
        # Always forward the structured cause last, beyond peer traceback noise.
        if any("out of memory" in "".join(tail).lower() for tail in tails):
            print("FTT_FAILURE gpu_out_of_memory: CUDA out of memory", flush=True)
        raise RuntimeError("TAD shard failed; no partial result published")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--devices", required=True)
    parser.add_argument("--decode-workers", type=int, default=4)
    parser.add_argument("--prefetch-depth", type=int, default=4)
    parser.add_argument(
        "--decoder-mode", default="prefetch", choices=["fresh", "reuse", "prefetch"]
    )
    args = parser.parse_args()
    devices = args.devices.split(",")
    if (
        len(devices) != len(set(devices))
        or not devices
        or any(not device for device in devices)
    ):
        parser.error("Select distinct reserved GPUs")
    # isort: off
    import torch  # noqa: F401 - load before Decord, matching the validated loader
    import decord
    # isort: on

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sports_e2e_pair_data import frame_windows

    reader = decord.VideoReader(str(args.video), num_threads=2)
    count = len(frame_windows(len(reader), length=768, stride=384))
    del reader
    devices = devices[:count]
    args.output.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name("infer_ftt_single_video_20261110.py")
    children, logs = [], []
    start = time.monotonic()

    def interrupted(*_):
        raise InterruptedError("Multi-GPU inference interrupted")

    signal.signal(signal.SIGTERM, interrupted)

    try:
        for index, device in enumerate(devices):
            directory = args.output / f"shard-{index}"
            command = [
                sys.executable,
                str(script),
                "--video",
                str(args.video),
                "--output",
                str(directory),
                "--checkpoint",
                str(args.checkpoint),
                "--shard-index",
                str(index),
                "--shard-count",
                str(len(devices)),
                "--decoder-mode",
                args.decoder_mode,
                "--decode-workers",
                str(args.decode_workers),
                "--prefetch-depth",
                str(args.prefetch_depth),
            ]
            # Inherit the caller's process group so lease loss kills the entire tree.
            child = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=dict(os.environ, CUDA_VISIBLE_DEVICES=device),
            )
            children.append(child)
            logs.append((args.output / f"shard-{index}.log").open("w"))
        collect_output(children, logs)
        spec = importlib.util.spec_from_file_location("ftt_merge", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        summaries = [
            json.loads((args.output / f"shard-{i}/predictions.json").read_text())
            for i in range(len(devices))
        ]
        summary = summaries[0]
        if len(devices) == 1:
            merged = summary
        else:
            if sum(s["windows"] for s in summaries) != summary["global_windows"]:
                raise RuntimeError("Incomplete global window set")
            raw = [
                json.loads(
                    (args.output / f"shard-{i}/raw_predictions.json").read_text()
                )
                for i in range(len(devices))
            ]
            merged = {
                k: v for k, v in summary.items() if k not in ("rallies", "actions")
            }
            for task, kind, limit in [
                ("rallies", "coarse", 200),
                ("actions", "fine", 500),
            ]:
                rows = [row for shard in raw for row in shard[kind]]
                names = (
                    (
                        module.ROOT
                        / f"data/ftt/sgp_bmp_vm2_20class_v1/{kind}_class_map.txt"
                    )
                    .read_text()
                    .splitlines()
                )
                result = module.finish_predictions(
                    {"video": rows}, names, max_segments=limit
                )["results"]["video"]
                result.sort(key=lambda r: r["segment"][0])
                merged[task] = module.as_rows(
                    result, "rally" if task == "rallies" else "action"
                )
        merged.update(
            windows=sum(s["windows"] for s in summaries),
            shard_count=len(devices),
            inference_seconds=round(time.monotonic() - start, 3),
        )
        temporary = args.output / "predictions.partial"
        temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
        os.replace(temporary, args.output / "predictions.json")
        print(
            "INFERENCE_DONE",
            json.dumps(
                {
                    "windows": merged["windows"],
                    "shards": len(devices),
                    "wall_s": time.monotonic() - start,
                }
            ),
            flush=True,
        )
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            if child.stdout:
                child.stdout.close()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()

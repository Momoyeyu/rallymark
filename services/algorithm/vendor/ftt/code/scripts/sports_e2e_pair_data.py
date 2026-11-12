"""Paired hierarchy metadata and frame-exact windows for sports E2E TAD.

This module does not decode video or expose the held-out test split to training.
It keeps parent IDs attached to child instances after temporal cropping.
"""

from __future__ import annotations

import json
import hashlib
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np


@lru_cache(maxsize=2048)
def video_dimensions(path: str) -> tuple[int, int]:
    """Read dimensions without decoding an extra full-resolution frame."""
    output = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", path,
    ], text=True)
    stream = json.loads(output)["streams"][0]
    return int(stream["height"]), int(stream["width"])


@dataclass(frozen=True)
class PairedVideo:
    video_id: str
    split: str
    fps: float
    frame_count: int
    coarse: tuple[dict, ...]
    fine: tuple[dict, ...]
    media: str | None = None


def load_pair(root: str | Path, *, allowed_splits=("training", "validation")) -> dict[str, PairedVideo]:
    root = Path(root)
    coarse_db = json.loads((root / "coarse_annotations.json").read_text())["database"]
    fine_db = json.loads((root / "fine_annotations.json").read_text())["database"]
    if coarse_db.keys() != fine_db.keys():
        raise ValueError("Coarse and fine video ID sets differ")

    result = {}
    for video_id, c in coarse_db.items():
        f = fine_db[video_id]
        def nframes(row):
            if "frame" in row:
                return int(row["frame"])
            return int(row["source_end_frame_exclusive"] - row["source_start_frame"])

        if c["subset"] != f["subset"] or nframes(c) != nframes(f):
            raise ValueError(f"Inconsistent paired metadata: {video_id}")
        if c["subset"] not in allowed_splits:
            continue
        if c["fps"] <= 0 or nframes(c) <= 0:
            raise ValueError(f"Invalid video timing: {video_id}")
        parents = {a["instance_id"] for a in c["annotations"]}
        if len(parents) != len(c["annotations"]):
            raise ValueError(f"Duplicate parent instance ID: {video_id}")
        for a in f["annotations"]:
            if a.get("parent_instance_id") not in parents:
                raise ValueError(f"Missing parent for {video_id}/{a['instance_id']}")
        result[video_id] = PairedVideo(
            video_id, c["subset"], float(c["fps"]), nframes(c),
            tuple(c["annotations"]), tuple(f["annotations"]),
            c.get("media"),
        )
    return result


def frame_windows(frame_count: int, length: int = 768, stride: int = 384) -> list[tuple[int, int]]:
    if length <= 0 or stride <= 0:
        raise ValueError("Window length and stride must be positive")
    if frame_count <= length:
        return [(0, frame_count)]
    starts = list(range(0, frame_count - length + 1, stride))
    last = frame_count - length
    if starts[-1] != last:
        starts.append(last)
    return [(s, min(s + length, frame_count)) for s in starts]


def crop_pair(video: PairedVideo, start_frame: int, end_frame: int) -> dict:
    """Clip both levels to a window, retaining IDs and truncation flags.

    Segments are returned in window-local frame units; the model can scale them
    to its temporal feature grid. Parent links are retained even when a parent
    overlaps the window only partially. Zero-overlap instances are excluded.
    """
    if not (0 <= start_frame < end_frame <= video.frame_count):
        raise ValueError("Invalid window bounds")
    start_time, end_time = start_frame / video.fps, end_frame / video.fps

    def clip(annotations):
        out = []
        for ann in annotations:
            left, right = map(float, ann["segment"])
            if min(right, end_time) <= max(left, start_time):
                continue
            item = dict(ann)
            item["segment"] = [
                max(0.0, (max(left, start_time) - start_time) * video.fps),
                min(float(end_frame - start_frame),
                    (min(right, end_time) - start_time) * video.fps),
            ]
            item["truncated_left"] = left < start_time
            item["truncated_right"] = right > end_time
            out.append(item)
        return out

    coarse, fine = clip(video.coarse), clip(video.fine)
    parent_ids = {a["instance_id"] for a in coarse}
    if any(a["parent_instance_id"] not in parent_ids for a in fine):
        raise ValueError(f"Window broke a parent-child link: {video.video_id}")
    return {
        "video_id": video.video_id,
        "split": video.split,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "fps": video.fps,
        "coarse": coarse,
        "fine": fine,
    }


class SportsE2EWindowDataset:
    """Decode a paired 768-frame window at native frame cadence.

    Returned tensor is uint8 RGB in [C,T,H,W]. Normalization belongs to the
    two existing backbone wrappers. The last short window repeats its last
    decoded frame and marks padded positions invalid. Test is never indexed.
    """

    def __init__(self, annotation_root, split, *, media_root=None,
                 length=768, stride=384, image_size=160):
        if split not in ("training", "validation"):
            raise ValueError("Only training and validation may be indexed")
        self.videos = load_pair(annotation_root)
        self.split = split
        self.length = length
        self.image_size = image_size
        self.media_root = Path(media_root) if media_root else None
        self.index = [
            (video_id, start, end)
            for video_id, video in self.videos.items() if video.split == split
            for start, end in frame_windows(video.frame_count, length, stride)
        ]

    def __len__(self):
        return len(self.index)

    def __getitem__(self, idx):
        return self._read_window(*self.index[idx])

    def _read_window(self, video_id, start, end):
        import torch
        # In the OpenTAD environment Decord loaded before PyTorch can abort
        # during torch import (std::random_device); keep this order explicit.
        import decord

        video = self.videos[video_id]
        if video.media:
            path = Path(video.media)
        elif self.media_root:
            path = self.media_root / f"{video_id}.mp4"
        else:
            raise ValueError(f"Missing video path: {video_id}")
        if not path.is_file():
            raise FileNotFoundError(path)

        # Probe metadata without decoding a full-resolution frame. A Decord
        # probe[0] intermittently hit EOF on valid long FTT videos under DDP.
        height, width = video_dimensions(str(path))
        short = min(height, width)
        out_h = max(self.image_size, round(height * self.image_size / short))
        out_w = max(self.image_size, round(width * self.image_size / short))
        indices = np.arange(start, end, dtype=np.int64)
        if len(indices) < self.length:
            indices = np.pad(indices, (0, self.length - len(indices)),
                             mode="constant", constant_values=end - 1)
        for attempt in range(3):
            reader = None
            try:
                reader = decord.VideoReader(str(path), width=out_w, height=out_h,
                                            num_threads=2)
                if len(reader) < end:
                    raise ValueError(
                        f"Decoded {len(reader)} frames but metadata expects {end}: {video_id}")
                frames = reader.get_batch(indices).asnumpy()
                break
            except decord.DECORDError:
                if attempt == 2:
                    raise
                time.sleep(0.25 * (attempt + 1))
            finally:
                del reader
        top = (out_h - self.image_size) // 2
        left = (out_w - self.image_size) // 2
        frames = np.ascontiguousarray(
            frames[:, top:top + self.image_size, left:left + self.image_size])
        window = crop_pair(video, start, end)
        coarse = window["coarse"]
        fine = window["fine"]
        mask = torch.arange(self.length) < (end - start)

        def tensors(items):
            segments = torch.tensor([a["segment"] for a in items], dtype=torch.float32).reshape(-1, 2)
            labels = torch.tensor([a["label_id"] for a in items], dtype=torch.long)
            return segments, labels

        coarse_segments, coarse_labels = tensors(coarse)
        fine_segments, fine_labels = tensors(fine)
        return {
            "frames": torch.from_numpy(frames).permute(3, 0, 1, 2),
            "mask": mask,
            "coarse_segments": coarse_segments,
            "coarse_labels": coarse_labels,
            "fine_segments": fine_segments,
            "fine_labels": fine_labels,
            "parent_ids": [a["instance_id"] for a in coarse],
            "fine_parent_ids": [a["parent_instance_id"] for a in fine],
            "coarse_truncated": torch.tensor([
                a["truncated_left"] or a["truncated_right"] for a in coarse],
                dtype=torch.bool),
            "fine_truncated": torch.tensor([
                a["truncated_left"] or a["truncated_right"] for a in fine],
                dtype=torch.bool),
            "fine_parent_index": torch.tensor([
                [p["instance_id"] for p in coarse].index(a["parent_instance_id"])
                for a in fine], dtype=torch.long),
            "video_id": video_id,
            "start_frame": start,
            "end_frame": end,
            "fps": video.fps,
        }


class RandomSportsE2EWindowDataset(SportsE2EWindowDataset):
    """Four reproducible train windows per source clip each epoch by default.

    Two windows center on fine instances, one on a parent instance, and one
    samples the entire video. This preserves coarse supervision in long FOB
    rallies while retaining action and real-background coverage.
    """

    def __init__(self, annotation_root, *, media_root=None, length=768,
                 windows_per_video=4, seed=42, image_size=160):
        super().__init__(annotation_root, "training", media_root=media_root,
                         length=length, stride=length, image_size=image_size)
        self.video_ids = [k for k, v in self.videos.items() if v.split == "training"]
        self.windows_per_video = windows_per_video
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch):
        self.epoch = int(epoch)

    def __len__(self):
        return len(self.video_ids) * self.windows_per_video

    def __getitem__(self, idx):
        return self._read_window(*self.window_at(idx))

    def window_at(self, idx):
        video_id = self.video_ids[idx // self.windows_per_video]
        slot = idx % self.windows_per_video
        video = self.videos[video_id]
        digest = hashlib.blake2b(
            f"{self.seed}:{self.epoch}:{video_id}:{slot}".encode(),
            digest_size=8).digest()
        rng = np.random.default_rng(int.from_bytes(digest, "little"))
        last_start = max(0, video.frame_count - self.length)
        if slot % 4 in (0, 1) and video.fine:
            ann = video.fine[int(rng.integers(len(video.fine)))]
            center = (ann["segment"][0] + ann["segment"][1]) * video.fps / 2
            jitter = rng.uniform(-.25, .25) * self.length
            start = int(np.clip(round(center - self.length / 2 + jitter), 0, last_start))
        elif slot % 4 == 2 and video.coarse:
            ann = video.coarse[int(rng.integers(len(video.coarse)))]
            center = (ann["segment"][0] + ann["segment"][1]) * video.fps / 2
            jitter = rng.uniform(-.25, .25) * self.length
            start = int(np.clip(round(center - self.length / 2 + jitter), 0, last_start))
        else:
            start = int(rng.integers(last_start + 1))
        end = min(video.frame_count, start + self.length)
        return video_id, start, end


def collate_sports_e2e(batch):
    import torch

    return {
        "frames": torch.stack([row["frames"] for row in batch]).unsqueeze(1),
        "masks": torch.stack([row["mask"] for row in batch]),
        "coarse_segments": [row["coarse_segments"] for row in batch],
        "coarse_labels": [row["coarse_labels"] for row in batch],
        "fine_segments": [row["fine_segments"] for row in batch],
        "fine_labels": [row["fine_labels"] for row in batch],
        "fine_parent_index": [row["fine_parent_index"] for row in batch],
        "coarse_truncated": [row["coarse_truncated"] for row in batch],
        "fine_truncated": [row["fine_truncated"] for row in batch],
        "meta": [{k: row[k] for k in ("video_id", "start_frame", "end_frame", "fps")}
                 for row in batch],
    }

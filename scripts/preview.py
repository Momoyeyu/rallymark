#!/usr/bin/env python3
"""Export a self-contained, read-only demo dataset without experimental diagnostics."""

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path


def export(source, destination):
    review = source / "review"
    manifest = json.loads((review / "manifest.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    items = []
    for row in manifest["videos"]:
        identifier = row["id"]
        if not re.fullmatch(r"[a-z0-9_-]+", identifier):
            raise ValueError("Unsafe demo ID")
        metadata = json.loads((review / f"{identifier}.json").read_text())
        video = source / "videos" / f"{identifier}.mp4"
        # Experiments may store videos directly at the dataset root.
        if not video.is_file():
            video = source / f"{identifier}.mp4"
        digest = hashlib.sha256()
        with video.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        checksum = digest.hexdigest()
        if (
            checksum != metadata["source_sha256"]
            or video.stat().st_size != metadata["source_size_bytes"]
        ):
            raise ValueError("Demo video and metadata mismatch: " + identifier)
        filename = f"{identifier}.{checksum[:12]}.mp4"
        target = destination / filename
        if not target.exists():
            temporary = target.with_suffix(".partial")
            shutil.copyfile(video, temporary)
            os.replace(temporary, target)
        analysis = dict(
            id=identifier,
            video_id=identifier,
            status="succeeded",
            progress=None,
            rallies=metadata["rallies"],
            warnings=metadata.get("warnings", []),
            error=None,
            created_at="",
            config_hash="",
            algorithm_version=metadata["algorithm_version"],
        )
        public = dict(
            id=identifier,
            title=metadata["title"],
            duration_s=metadata["duration_s"],
            width=0,
            height=0,
            size_bytes=video.stat().st_size,
            created_at="",
            expires_at="",
            latest_analysis=analysis,
        )
        items.append(dict(video=public, media="/demos/" + filename))
    if len(items) != 6:
        raise ValueError("The preview release requires exactly six demos")
    temporary = destination / "manifest.partial"
    temporary.write_text(
        json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":"))
    )
    os.replace(temporary, destination / "manifest.json")
    print(f"Exported {len(items)} verified demos to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.source, args.destination)

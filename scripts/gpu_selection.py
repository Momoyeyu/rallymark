"""Deployment-only GPU visibility; inference scheduling remains in the worker."""

import csv
import os
import re
import subprocess


def selectors(value, count=0):
    count = int(count)
    if count < 0:
        raise ValueError("GPU_COUNT must be nonnegative")
    if value == "all":
        if count:
            raise ValueError(
                "Run make gpu-config to resolve GPU_COUNT against the host inventory"
            )
        return []
    ids = [part.strip() for part in value.split(",")]
    if not ids or any(
        not re.fullmatch(r"(?:[0-9]+|GPU-[a-fA-F0-9-]+)", item) for item in ids
    ):
        raise ValueError("GPU_DEVICE must contain GPU indices or UUIDs")
    if len(ids) != len(set(ids)) or count > len(ids):
        raise ValueError("GPU_COUNT exceeds the selection or devices are duplicated")
    return ids[:count] if count else ids


def resolve(output, value, count):
    rows = list(csv.reader(output.strip().splitlines(), skipinitialspace=True))
    if not rows or any(len(row) != 3 for row in rows):
        raise ValueError("Invalid GPU inventory")
    known = {key: row[1] for row in rows for key in row[:2]}
    requested = [row[1] for row in rows] if value == "all" else selectors(value)
    try:
        uuids = [known[key] for key in requested]
    except KeyError as e:
        raise ValueError("Selected GPU is unavailable") from e
    return selectors(",".join(uuids), count)


def override(root):
    ids = selectors(
        os.environ.get("GPU_DEVICE") or "all", os.environ.get("GPU_COUNT") or 0
    )
    if not ids:
        return None
    if any(identifier.isdigit() for identifier in ids):
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,uuid,name", "--format=csv,noheader"],
            text=True,
            timeout=10,
        )
        ids = resolve(
            output, os.environ["GPU_DEVICE"], int(os.environ.get("GPU_COUNT") or 0)
        )
    path = root / ".runtime" / "gpu-selection.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "services:\n  algorithm-worker:\n    devices: !override\n"
        + "".join("      - nvidia.com/gpu=" + identifier + "\n" for identifier in ids)
        + "    environment:\n      GPU_DEVICE: "
        + ",".join(ids)
        + "\n"
    )
    return path


def configure(ops):
    output = ops.run(
        ["nvidia-smi", "--query-gpu=index,uuid,name", "--format=csv,noheader"],
        capture=True,
    )
    ids = resolve(
        output,
        os.environ.get("GPU_DEVICE") or "all",
        int(os.environ.get("GPU_COUNT") or 0),
    )
    values = {"GPU_DEVICE": ",".join(ids), "GPU_COUNT": str(len(ids))}
    ops.backup()
    lines = [
        line
        for line in ops.ENV.read_text().splitlines()
        if line.split("=", 1)[0] not in values
    ]
    ops.ENV.write_text(
        "\n".join(lines + [key + "=" + value for key, value in values.items()]) + "\n"
    )
    ops.ENV.chmod(0o600)
    os.environ.update(values)
    print("Configured GPU pool:", ",".join(ids), "count:", len(ids))
    print("Apply with make config-apply or make deploy VERSION=<version>")

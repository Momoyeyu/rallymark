"""Conservative admission and session-scoped reservations for a shared GPU host."""

import csv
import hashlib
import subprocess
from dataclasses import dataclass

from sqlalchemy import text


@dataclass(frozen=True)
class Device:
    index: str
    uuid: str
    name: str
    total_mib: int
    free_mib: int
    utilization: int
    compute_mib: int = 0
    used_mib: int = 0


def parse_devices(output, allowlist, compute):
    allowed = None if allowlist == "all" else set(allowlist.split(","))
    devices = []
    matched = set()
    for row in csv.reader(output.strip().splitlines(), skipinitialspace=True):
        if len(row) != 7:
            raise ValueError("Invalid GPU telemetry")
        index, uuid, name, total, free, used, utilization = row
        total, free, used, utilization = int(total), int(free), int(used), int(utilization)
        if total <= 0 or not 0 <= free <= total or not 0 <= used <= total or not 0 <= utilization <= 100:
            raise ValueError("Invalid GPU capacity")
        if allowed is None or index in allowed or uuid in allowed:
            devices.append(Device(index, uuid, name, total, free, utilization, compute.get(uuid, 0), used))
            matched.update((index, uuid))
    if not devices or allowed and not allowed <= matched:
        raise ValueError("Configured GPU allowlist is unavailable")
    return devices


def discover(allowlist):
    def query(fields, kind="gpu"):
        return subprocess.run(
            ["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout

    compute = {}
    for row in csv.reader(
        query("gpu_uuid,used_memory", "compute-apps").strip().splitlines(), skipinitialspace=True
    ):
        if not row:
            continue
        if len(row) != 2:
            raise ValueError("Invalid compute process telemetry")
        compute[row[0]] = compute.get(row[0], 0) + int(row[1])
    return parse_devices(
        query("index,uuid,name,memory.total,memory.free,memory.used,utilization.gpu"), allowlist, compute
    )


def choose_devices(devices, reserved, maximum, queued, minimum_gib, max_utilization):
    available = [
        d
        for d in devices
        if d.uuid not in reserved
        and d.free_mib >= minimum_gib * 1024
        and d.utilization <= max_utilization
        and d.compute_mib < 512
        and d.used_mib < 512
    ]
    available.sort(key=lambda d: (-d.free_mib, d.utilization, d.uuid))
    count = min(maximum or len(available), max(1, len(available) // max(1, queued)))
    return available[:count]


def lock_key(uuid):
    return int.from_bytes(hashlib.sha256(("rallymark:gpu:" + uuid).encode()).digest()[:8], "big", signed=True)


class Reservation:
    def __init__(self, engine, candidates):
        self.connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        self.devices = []
        try:
            for device in candidates:
                if self.connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key(device.uuid)}
                ).scalar():
                    self.devices.append(device)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            for device in self.devices:
                self.connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key(device.uuid)}
                )
        finally:
            self.devices.clear()
            self.connection.close()

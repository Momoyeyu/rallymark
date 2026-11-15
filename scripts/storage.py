"""Verified, reversible migration of video-heavy Docker storage to a mounted disk."""

import json
import os
from pathlib import Path


def validate_mount():
    required = os.environ.get("STORAGE_MOUNT")
    if not required:
        return
    mount = Path(required).resolve()
    if not mount.is_mount() or mount == Path("/"):
        raise RuntimeError(
            "STORAGE_MOUNT must be an available separate filesystem mount"
        )
    for key in ("MEDIA_STORAGE", "ALGORITHM_STORAGE", "PREVIEW_DATA_PATH"):
        value = Path(os.environ.get(key, ""))
        if (
            not value.is_absolute()
            or not value.resolve().is_relative_to(mount)
            or not value.is_dir()
        ):
            raise RuntimeError(key + " must be an existing directory on STORAGE_MOUNT")


def migrate_storage(ops):
    mount = Path(os.environ.get("STORAGE_MOUNT", "")).resolve()
    root = Path(os.environ.get("STORAGE_ROOT", "")).resolve()
    if (
        not mount.is_mount()
        or mount == Path("/")
        or not root.is_relative_to(mount)
        or root == mount
    ):
        raise RuntimeError(
            "Set STORAGE_MOUNT to a mounted data filesystem and STORAGE_ROOT below it"
        )
    if root.exists():
        raise RuntimeError(
            "STORAGE_ROOT already exists; inspect the previous migration before retrying"
        )
    containers = {}
    for service, destination in (
        ("api", "/data/media"),
        ("algorithm-worker", "/data/work"),
    ):
        identifier = ops.compose("ps", "-q", service, capture=True).strip()
        if not identifier:
            raise RuntimeError("Start the existing deployment before migrating")
        info = json.loads(ops.run(["docker", "inspect", identifier], capture=True))[0]
        containers[service] = (
            info["Config"]["Image"],
            next(
                m["Source"] for m in info["Mounts"] if m["Destination"] == destination
            ),
        )
    preview = Path(os.environ.get("PREVIEW_DATA_PATH", "../.runtime/preview-data"))
    if not preview.is_absolute():
        preview = (ops.ROOT / "deploy" / preview).resolve()
    if not (preview / "manifest.json").is_file():
        raise RuntimeError("Existing preview manifest is required")
    ops.backup()
    original_env = ops.ENV.read_text()
    ops.drain()
    ops.compose("stop", "web", "api", "algorithm-worker", "algorithm")
    changed = False
    try:
        program = """import hashlib,json,os,shutil,sys
from pathlib import Path
source=Path('/source');target=Path('/disk')/sys.argv[1]
if target.exists(): raise RuntimeError('Migration target already exists')
def inventory(root):
 result={}
 for p in root.rglob('*'):
  if p.is_symlink(): raise RuntimeError('Unexpected storage symlink')
  if p.is_file():
   h=hashlib.sha256()
   with p.open('rb') as f:
    for block in iter(lambda:f.read(4194304),b''): h.update(block)
   result[str(p.relative_to(root))]={'bytes':p.stat().st_size,'sha256':h.hexdigest()}
 return result
before=inventory(source)
shutil.copytree(source,target)
after=inventory(target)
assert before==after,'Storage verification mismatch'
os.chown(target,int(sys.argv[2]),int(sys.argv[3]))
print(json.dumps({'files':before,'total_bytes':sum(x['bytes'] for x in before.values())}))
"""
        receipts = {}
        sources = [
            ("media", *containers["api"]),
            ("algorithm-work", *containers["algorithm-worker"]),
            ("preview", containers["api"][0], str(preview)),
        ]
        for name, image, source in sources:
            relative = str((root / name).relative_to(mount))
            data = ops.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--mount",
                    f"type=bind,src={source},dst=/source,readonly",
                    "--mount",
                    f"type=bind,src={mount},dst=/disk",
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    program,
                    relative,
                    str(os.getuid()),
                    str(os.getgid()),
                ],
                capture=True,
            )
            receipts[name] = json.loads(data)
        values = {
            "MEDIA_STORAGE": str(root / "media"),
            "ALGORITHM_STORAGE": str(root / "algorithm-work"),
            "PREVIEW_DATA_PATH": str(root / "preview"),
            "STORAGE_MOUNT": str(mount),
        }
        lines = [
            line
            for line in original_env.splitlines()
            if line.split("=", 1)[0] not in values
        ]
        ops.ENV.write_text(
            "\n".join(lines + [k + "=" + v for k, v in values.items()]) + "\n"
        )
        os.environ.update(values)
        changed = True
        validate_mount()
        ops.compose("up", "-d", "--wait", "--wait-timeout", "180")
        ops.business("undrain")
        output = ops.RUNTIME / "storage-migration.json"
        output.write_text(
            json.dumps({"storage": values, "verification": receipts}, indent=2) + "\n"
        )
        output.chmod(0o600)
        print("Storage migrated and SHA-256 verified:", root)
    except Exception:
        if changed:
            ops.ENV.write_text(original_env)
            for key in (
                "MEDIA_STORAGE",
                "ALGORITHM_STORAGE",
                "PREVIEW_DATA_PATH",
                "STORAGE_MOUNT",
            ):
                os.environ.pop(key, None)
            ops.load_env()
        ops.compose("up", "-d", "--wait", "--wait-timeout", "180")
        ops.business("undrain")
        raise

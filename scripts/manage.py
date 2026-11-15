#!/usr/bin/env python3
"""Operator commands shared by Makefile and deployment automation."""

import csv
import json
import math
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
RUNTIME = ROOT / ".runtime"
ENV = ROOT / (os.environ.get("ENV_FILE") or ".runtime/deploy.env")


def forward_remote(action):
    if os.environ.get("RALLYMARK_LOCAL") == "1":
        return False
    target = {}
    file = Path(os.environ.get("TARGET_FILE") or RUNTIME / "target.env")
    if file.exists():
        for line in file.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key not in ("DEPLOY_HOST", "DEPLOY_DIR"):
                    raise ValueError("Unknown deployment target setting: " + key)
                target[key] = value.strip()
    host = os.environ.get("DEPLOY_HOST") or target.get("DEPLOY_HOST")
    if not host:
        return False
    directory = (
        os.environ.get("DEPLOY_DIR") or target.get("DEPLOY_DIR") or "projects/rallymark"
    )
    path = PurePosixPath(directory)
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host):
        raise ValueError("DEPLOY_HOST must be an SSH host alias")
    if (
        path.is_absolute()
        or ".." in path.parts
        or "~" in path.parts
        or str(path) == "."
    ):
        raise ValueError(
            "DEPLOY_DIR must be a nonempty path relative to the SSH user's home"
        )
    forwarded = ["RALLYMARK_LOCAL=1"]
    for key in (
        "VERSION",
        "LOCAL_BUILD",
        "RALLYMARK_MODE",
        "ENV_FILE",
        "REGISTRY",
        "VIDEO_ID",
        "APPLY",
        "SERVICE",
        "BACKUP",
        "RESTORE_VERSION",
        "CONFIG_FILE",
        "WEB_PORT",
        "BIND_ADDRESS",
        "GPU_DEVICE",
        "WEIGHTS_PATH",
        "MIN_GPU_MEMORY_GIB",
        "GPU_MODE",
        "GPU_POOL_FILE",
        "GPU_CDI_DEVICE",
        "CONFIG_SCOPE",
        "MEDIA_STORAGE",
        "ALGORITHM_STORAGE",
        "STORAGE_MOUNT",
        "STORAGE_ROOT",
        "PREVIEW_PORT",
        "PREVIEW_DATA_PATH",
    ):
        if os.environ.get(key):
            forwarded.append(key + "=" + os.environ[key])
    command = (
        "cd -- "
        + shlex.quote(str(path))
        + " && exec "
        + shlex.join(["env", *forwarded, "make", action])
    )
    ssh = ["ssh"]
    if action == "config-edit" and sys.stdin.isatty():
        ssh.append("-t")
    run([*ssh, "--", host, command])
    return True


def run(args, *, capture=False, input=None, binary=False):
    return subprocess.run(
        [str(x) for x in args],
        cwd=ROOT,
        check=True,
        text=not binary and (input is None or isinstance(input, str)),
        input=input,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def load_env():
    if not ENV.is_file():
        raise RuntimeError("Run make setup first, then edit .runtime/deploy.env")
    for line in ENV.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if not os.environ.get(key):
                os.environ[key] = value.strip()


def compose(*args, capture=False, binary=False):
    os.environ.setdefault("DOCKER_BUILDKIT", "1")
    files = ["-f", ROOT / "deploy/compose.yaml"]
    if os.environ.get("RALLYMARK_MODE") == "dev":
        files += ["-f", ROOT / "deploy/compose.dev.yaml"]
    elif os.environ.get("GPU_MODE", "enabled") == "disabled":
        files += ["-f", ROOT / "deploy/compose.unavailable.yaml"]
    return run(
        [
            "docker",
            "compose",
            "--project-name",
            "rallymark-dev"
            if os.environ.get("RALLYMARK_MODE") == "dev"
            else "rallymark",
            "--env-file",
            ENV,
            *files,
            *args,
        ],
        capture=capture,
        binary=binary,
    )


def business(*args, capture=False):
    return compose(
        "exec", "-T", "api", "python", "-m", "rallymark_api.ops", *args, capture=capture
    )


def setup():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if ENV.exists():
        print("Existing environment retained:", ENV)
        return
    template = (ROOT / "deploy/.env.example").read_text()
    template = template.replace("generated-by-make-setup", "{}")
    template = template.format(*[secrets.token_hex(24) for _ in range(4)])
    ENV.write_text(template)
    ENV.chmod(0o600)
    print(
        "Created",
        ENV,
        "with unique credentials. Set REGISTRY and WEIGHTS_PATH before deploying.",
    )


def migrate():
    compose("up", "-d", "--wait", "postgres")
    for service, package in [
        ("api", "rallymark_api"),
        ("algorithm", "rallymark_algorithm"),
    ]:
        compose(
            "run", "--rm", "--no-deps", service, "python", "-m", package + ".migrate"
        )


def drain():
    if not compose("ps", "-q", "api", capture=True).strip():
        return
    business("drain")
    deadline = time.monotonic() + 3000
    while time.monotonic() < deadline:
        status = json.loads(business("status", capture=True))
        if status["running"] == 0:
            return
        time.sleep(2)
    raise RuntimeError("Tasks did not drain in 50 minutes; deployment stopped")


def version_directory():
    return RUNTIME / "dev" if os.environ.get("RALLYMARK_MODE") == "dev" else RUNTIME


def gpu_preflight(*, require_free=True):
    if os.environ.get("RALLYMARK_MODE") == "dev":
        return
    device = os.environ.get("GPU_DEVICE") or "0"
    minimum = float(os.environ.get("MIN_GPU_MEMORY_GIB") or "12")
    if not math.isfinite(minimum) or minimum <= 0:
        raise ValueError("MIN_GPU_MEMORY_GIB must be a positive finite number")
    output = run(
        [
            "nvidia-smi",
            *(["--id=" + device] if device != "all" else []),
            "--query-gpu=name,uuid,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture=True,
    )
    rows = list(csv.reader(output.strip().splitlines(), skipinitialspace=True))
    if not rows or any(len(row) != 4 for row in rows):
        raise RuntimeError("GPU_DEVICE selects no usable GPU telemetry")
    capable = [row for row in rows if float(row[2]) / 1024 >= minimum]
    if not capable:
        raise RuntimeError(f"Assigned GPU pool needs at least one card with {minimum:g} GiB total memory")
    if require_free and not any(float(row[3]) / 1024 >= minimum for row in capable):
        raise RuntimeError(f"Assigned GPU pool needs {minimum:g} GiB free memory")
    for name, identifier, total, free in capable:
        print(json.dumps({"gpu": name, "uuid": identifier, "free_gib": float(free) / 1024}))


def deploy(version, *, build=False, pull=False):
    if not version:
        raise RuntimeError("Specify VERSION=<immutable image tag>")
    previous_file = version_directory() / "current-version"
    previous = previous_file.read_text().strip() if previous_file.exists() else None
    os.environ["VERSION"] = version
    from storage import validate_mount
    validate_mount()
    compose("config", "--quiet")
    if os.environ.get("GPU_MODE", "enabled") != "disabled":
        gpu_preflight(require_free=False)
    else:
        print("Deploying with analysis disabled; business and media remain available")
    if build:
        compose("build")
    elif pull:
        compose("pull")
    else:
        rendered = json.loads(compose("config", "--format", "json", capture=True))
        for name in ("api", "algorithm", "algorithm-worker", "web"):
            run(
                ["docker", "image", "inspect", rendered["services"][name]["image"]],
                capture=True,
            )
    drain()
    try:
        migrate()
        compose("up", "-d", "--wait", "--wait-timeout", "180")
        business("undrain")
    except Exception:
        if previous and previous != version:
            os.environ["VERSION"] = previous
            compose("up", "-d", "--wait", "--wait-timeout", "180")
            business("undrain")
            print("Previous application version restored:", previous, file=sys.stderr)
        raise
    previous_file.parent.mkdir(mode=0o700, exist_ok=True)
    if previous:
        (version_directory() / "previous-version").write_text(previous + "\n")
    previous_file.write_text(version + "\n")
    print("Deployed", version)


def config_check():
    compose("config", "--quiet")
    compose(
        "run",
        "--rm",
        "--no-deps",
        "api",
        "python",
        "-m",
        "rallymark_api.ops",
        "config-check",
    )
    compose(
        "run",
        "--rm",
        "--no-deps",
        "--volume",
        str(gpu_pool_path()) + ":/app/gpu-pool.yaml:ro",
        "--env",
        "GPU_POOL_PATH=/app/gpu-pool.yaml",
        "algorithm",
        "python",
        "-c",
        "from rallymark_algorithm.settings import Settings; "
        "Settings.load(); print('Algorithm configuration valid')",
    )


def gpu_pool_path():
    path = Path(os.environ.get("GPU_POOL_FILE") or "./gpu-pool.yaml")
    return path if path.is_absolute() else ROOT / "deploy" / path


def configured_path():
    if os.environ.get("RALLYMARK_MODE") == "dev":
        return ROOT / "deploy/config.dev.yaml"
    path = Path(os.environ.get("CONFIG_FILE") or "./config.yaml")
    return path if path.is_absolute() else ROOT / "deploy" / path


def backup():
    target = ROOT / "backups" / time.strftime("%Y%m%d-%H%M%S")
    target.mkdir(parents=True, mode=0o700)
    result = compose(
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        "rallymark",
        "-Fc",
        capture=True,
        binary=True,
    )
    (target / "database.dump").write_bytes(result)
    shutil.copy2(ENV, target / "deploy.env")
    config = configured_path()
    shutil.copy2(config, target / "config.yaml")
    if gpu_pool_path().exists():
        shutil.copy2(gpu_pool_path(), target / "gpu-pool.yaml")
    if (version_directory() / "current-version").exists():
        shutil.copy2(version_directory() / "current-version", target / "version")
    for file in target.iterdir():
        file.chmod(0o600)
    print(target)


def restore():
    source = Path(os.environ.get("BACKUP", "")).resolve()
    if not (source / "database.dump").is_file():
        raise RuntimeError(
            "BACKUP must name a backup directory containing database.dump"
        )
    for name in ("config.yaml", "deploy.env", "version"):
        if not (source / name).is_file():
            raise RuntimeError("Backup is incomplete: missing " + name)
    database_dump = (source / "database.dump").read_bytes()
    restored_config = (source / "config.yaml").read_bytes()
    deployment_environment = (source / "deploy.env").read_text()
    version_file = source / "version"
    backup_version = version_file.read_text().strip()
    if not backup_version:
        raise RuntimeError("Backup application version is empty")
    restore_version = (os.environ.get("RESTORE_VERSION") or backup_version).strip()
    if not restore_version:
        raise RuntimeError("Restore application version is empty")
    # Resolve all requirements before stopping services or replacing the database.
    previous_version = os.environ["VERSION"]
    os.environ["VERSION"] = restore_version
    rendered = json.loads(compose("config", "--format", "json", capture=True))
    for name in ("api", "algorithm", "algorithm-worker", "web"):
        run(
            ["docker", "image", "inspect", rendered["services"][name]["image"]],
            capture=True,
        )
    os.environ["VERSION"] = previous_version
    backup_env = {}
    for line in deployment_environment.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            backup_env[key] = value
    for key in ("POSTGRES_PASSWORD", "BUSINESS_DB_PASSWORD", "ALGORITHM_DB_PASSWORD"):
        if backup_env.get(key) != os.environ.get(key):
            raise RuntimeError(
                "Database credentials changed since backup; reconcile credentials before restore"
            )
    drain()
    compose("stop", "api", "algorithm", "algorithm-worker")
    container = compose("ps", "-q", "postgres", capture=True).strip()
    if not container:
        raise RuntimeError("PostgreSQL must be running")
    run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            "rallymark",
            "--clean",
            "--if-exists",
            "--exit-on-error",
            "--single-transaction",
        ],
        input=database_dump,
    )
    config = configured_path()
    config.write_bytes(restored_config)
    if (source / "gpu-pool.yaml").is_file():
        gpu_pool_path().write_bytes((source / "gpu-pool.yaml").read_bytes())
    os.environ["VERSION"] = restore_version
    compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180")
    version_directory().mkdir(parents=True, mode=0o700, exist_ok=True)
    (version_directory() / "current-version").write_text(restore_version + "\n")
    business("undrain")
    (version_directory() / "last-restore.json").write_text(
        json.dumps(
            {"backup_version": backup_version, "application_version": restore_version}
        )
        + "\n"
    )
    print("Restored database/configuration. Media volumes were retained.")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action == "help":
        print(
            "setup dev check test build deploy rollback status logs doctor config-edit config-check config-apply data-clean smoke smoke-gpu backup restore sync preview-export preview-deploy preview-status preview-logs"
        )
        print(
            "deploy/rollback VERSION=tag; logs SERVICE=api; data-clean [VIDEO_ID=id] [APPLY=1]; restore BACKUP=directory"
        )
        return
    if action == "setup":
        setup()
        return
    if action == "sync":
        run(["git", "push", "origin", "HEAD"])
        run(["git", "push", "github", "HEAD"])
        return
    if forward_remote(action):
        return
    requested_version = os.environ.get("VERSION")
    load_env()
    current = version_directory() / "current-version"
    os.environ["VERSION"] = requested_version or (
        current.read_text().strip()
        if current.exists()
        else os.environ.get("VERSION") or "local"
    )
    if action in ("preview-deploy", "preview-status", "preview-logs"):
        command = [
            "docker",
            "compose",
            "--project-name",
            "rallymark-preview",
            "--env-file",
            ENV,
            "-f",
            ROOT / "deploy/compose.preview.yaml",
        ]
        if action == "preview-deploy":
            data = Path(os.environ.get("PREVIEW_DATA_PATH", "../.runtime/preview-data"))
            if not data.is_absolute():
                data = ROOT / "deploy" / data
            manifest = json.loads((data / "manifest.json").read_text())
            if len(manifest["items"]) != 6:
                raise RuntimeError("Export all six demos before deploying preview")
            run([*command, "build"])
            run([*command, "up", "-d", "--wait", "--wait-timeout", "120"])
        else:
            run(
                [*command, "ps"]
                if action == "preview-status"
                else [*command, "logs", "--tail", "100", "--follow"]
            )
    elif action == "dev":
        os.environ["RALLYMARK_MODE"] = "dev"
        os.environ["VERSION"] = "local"
        deploy("local", build=True)
    elif action == "build":
        os.environ["VERSION"] = (
            requested_version or run(["git", "rev-parse", "HEAD"], capture=True).strip()
        )
        compose("build")
    elif action in ("deploy", "rollback"):
        version = requested_version
        if action == "rollback" and not version:
            version = (version_directory() / "previous-version").read_text().strip()
        local_build = (os.environ.get("LOCAL_BUILD") or "1") == "1"
        deploy(
            version,
            build=action == "deploy" and local_build,
            pull=action == "deploy" and not local_build,
        )
    elif action == "status":
        compose("ps")
        business("status")
    elif action == "logs":
        compose("logs", "--follow", "--tail", "200", os.environ.get("SERVICE") or "api")
    elif action == "storage-migrate":
        from storage import migrate_storage
        migrate_storage(sys.modules[__name__])
    elif action == "doctor":
        from storage import validate_mount
        validate_mount()
        run(["docker", "version"])
        run(["docker", "compose", "version"])
        compose("config", "--quiet")
        if os.environ.get("GPU_MODE", "enabled") != "disabled":
            gpu_preflight()
        print("Free disk bytes:", shutil.disk_usage(ROOT).free)
    elif action == "config-edit":
        path = gpu_pool_path() if os.environ.get("CONFIG_SCOPE") == "algorithm" else configured_path()
        run([*shlex.split(os.environ.get("EDITOR", "vi")), path])
    elif action == "config-check":
        config_check()
    elif action == "config-apply":
        from storage import validate_mount
        validate_mount()
        config_check()
        drain()
        compose(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "api",
            "algorithm",
            "algorithm-worker",
            "web",
        )
        business("undrain")
    elif action == "data-clean":
        args = ["cleanup"]
        if os.environ.get("VIDEO_ID"):
            args += ["--video-id", os.environ["VIDEO_ID"]]
        if os.environ.get("APPLY") == "1":
            args.append("--apply")
        business(*args)
        compose(
            "exec", "-T", "algorithm", "python", "-m", "rallymark_algorithm.ops", *args
        )
    elif action == "backup":
        backup()
    elif action == "restore":
        restore()
    else:
        raise RuntimeError("Unknown operation: " + action)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print("Operation failed:", error, file=sys.stderr)
        sys.exit(1)

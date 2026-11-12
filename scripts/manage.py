#!/usr/bin/env python3
"""Operator commands shared by Makefile and deployment automation."""

import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
ENV = ROOT / (os.environ.get("ENV_FILE") or ".runtime/deploy.env")


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
    files = ["-f", ROOT / "deploy/compose.yaml"]
    if os.environ.get("RALLYMARK_MODE") == "dev":
        files += ["-f", ROOT / "deploy/compose.dev.yaml"]
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


def deploy(version, *, build=False, pull=False):
    if not version:
        raise RuntimeError("Specify VERSION=<immutable image tag>")
    previous_file = version_directory() / "current-version"
    previous = previous_file.read_text().strip() if previous_file.exists() else None
    os.environ["VERSION"] = version
    compose("config", "--quiet")
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
    restore_version = version_file.read_text().strip()
    if not restore_version:
        raise RuntimeError("Backup application version is empty")
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
    os.environ["VERSION"] = restore_version
    compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180")
    version_directory().mkdir(parents=True, mode=0o700, exist_ok=True)
    (version_directory() / "current-version").write_text(restore_version + "\n")
    business("undrain")
    print("Restored database/configuration. Media volumes were retained.")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action == "help":
        print(
            "setup dev check test build deploy rollback status logs doctor config-edit config-check config-apply data-clean smoke smoke-gpu backup restore sync"
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
    requested_version = os.environ.get("VERSION")
    load_env()
    current = version_directory() / "current-version"
    os.environ["VERSION"] = requested_version or (
        current.read_text().strip()
        if current.exists()
        else os.environ.get("VERSION") or "local"
    )
    if action == "dev":
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
    elif action == "doctor":
        run(["docker", "version"])
        run(["docker", "compose", "version"])
        compose("config", "--quiet")
        if os.environ.get("GPU_DEVICE"):
            run(["nvidia-smi", "--query-gpu=name,uuid,memory.used", "--format=csv"])
        print("Free disk bytes:", shutil.disk_usage(ROOT).free)
    elif action == "config-edit":
        run([*shlex.split(os.environ.get("EDITOR", "vi")), configured_path()])
    elif action == "config-check":
        config_check()
    elif action == "config-apply":
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
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print("Operation failed:", error, file=sys.stderr)
        sys.exit(1)

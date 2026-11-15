#!/usr/bin/env python3
"""Run the same maintained checks locally and in CI."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, directory):
    subprocess.run(args, cwd=directory, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", action="store_true")
    args = parser.parse_args()
    if args.tests:
        run(
            [
                "uv", "run", "--project", "services/api", "python", "-m",
                "unittest", "discover", "-s", "tests", "-p", "test_*.py",
            ],
            ROOT,
        )
    for service in ["api", "algorithm"]:
        directory = ROOT / "services" / service
        run(["uv", "sync", "--frozen"], directory)
        if args.tests:
            run(["uv", "run", "pytest", "-q"], directory)
        else:
            run(["uv", "run", "ruff", "check", "."], directory)
            run(["uv", "run", "ruff", "format", "--check", "."], directory)
    web = ROOT / "apps/web"
    algorithm_python = ROOT / "services/algorithm/.venv/bin/python"
    if args.tests:
        run([str(algorithm_python), "-m", "pytest", "scripts/experiments/tests", "-q"], ROOT)
    else:
        ruff = str(ROOT / "services/algorithm/.venv/bin/ruff")
        run([ruff, "check", "scripts/experiments"], ROOT)
        run([ruff, "format", "--check", "scripts/experiments"], ROOT)
    run(["pnpm", "install", "--frozen-lockfile"], web)
    run(["pnpm", "test" if args.tests else "check"], web)
    if not args.tests:
        run(["pnpm", "build"], web)
    run(["python3", "scripts/contracts.py", "--check"], ROOT)


if __name__ == "__main__":
    main()

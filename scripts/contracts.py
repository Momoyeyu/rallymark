#!/usr/bin/env python3
"""Export the API contract and regenerate its frontend types."""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        schema, types = temp / "api.openapi.json", temp / "api.generated.ts"
        env = dict(os.environ, DATABASE_URL="sqlite:///:memory:", INTERNAL_TOKEN="contract-export-not-a-secret", MEDIA_ROOT=str(temp / "media"))
        subprocess.run(
            ["uv", "run", "--project", str(ROOT / "services/api"), "python", "-m",
             "rallymark_api.ops", "export-schema", "--out", str(schema)],
            cwd=ROOT, env=env, check=True,
        )
        subprocess.run(
            ["pnpm", "exec", "openapi-typescript", str(schema), "--output", str(types)],
            cwd=ROOT / "apps/web", check=True,
        )
        for source, destination in (
            (schema, ROOT / "contracts/api.openapi.json"),
            (types, ROOT / "apps/web/src/api.generated.ts"),
        ):
            if args.check:
                if not destination.exists() or source.read_bytes() != destination.read_bytes():
                    raise SystemExit("Contract drift: run python3 scripts/contracts.py")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()

"""Provision the GPU worker's pinned model assets on the deployment host."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

MANIFEST = Path("services/algorithm/vendor/ftt/SHA256_MANIFEST.json")
MODEL_RELEASE = "https://www.modelscope.ai/models/momoyeyu/rallymark/resolve/ftt-weights-v1"
BLOCK_SIZE = 8 * 1024 * 1024


def verify_weight(file, expected):
    if not file.is_file() or file.stat().st_size != expected["bytes"]:
        raise RuntimeError(f"Model asset size mismatch: {file}")
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_SIZE), b""):
            digest.update(block)
    if digest.hexdigest() != expected["sha256"]:
        raise RuntimeError(f"Model asset checksum mismatch: {file}")


def download_weight(name, destination, expected):
    print(f"Downloading {destination.name} from the RallyMark ModelScope release", flush=True)
    # A verified file becomes visible in one step. A concurrent download can
    # win the race without either process replacing an existing local weight.
    with NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.") as temporary:
        received = 0
        with urlopen(f"{MODEL_RELEASE}/{name}", timeout=60) as response:
            for block in iter(lambda: response.read(BLOCK_SIZE), b""):
                received += len(block)
                if received > expected["bytes"]:
                    raise RuntimeError(f"Model asset size mismatch: {destination}")
                temporary.write(block)
        temporary.flush()
        verify_weight(Path(temporary.name), expected)
        try:
            os.link(temporary.name, destination)
        except FileExistsError:
            verify_weight(destination, expected)


def prepare_weights(root):
    setting = os.environ.get("WEIGHTS_PATH")
    if not setting:
        raise RuntimeError("Set WEIGHTS_PATH in the deployment environment")
    directory = root / "deploy" / setting
    directory = directory.resolve()
    manifest = json.loads((root / MANIFEST).read_text())
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name, expected in manifest.items():
            if not name.startswith("weights/"):
                continue
            filename = name.split("/", 1)[1]
            destination = directory / filename
            if destination.exists():
                verify_weight(destination, expected)
            else:
                download_weight(name, destination, expected)
    except OSError as error:
        raise RuntimeError(f"Cannot prepare model weights in {directory}: {error}") from error

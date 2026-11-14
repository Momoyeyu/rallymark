import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import time
import unittest

spec = importlib.util.spec_from_file_location(
    "supervision",
    Path(__file__).resolve().parents[1] / "code/scripts/infer_multigpu.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ShardSupervisionTests(unittest.TestCase):
    def test_exited_shards_last_oom_line_is_forwarded_and_peer_is_stopped(self):
        self.assertTrue(hasattr(module, "collect_output"))
        bad = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "print('CUDA out of memory',flush=True);raise SystemExit(1)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        bad.wait()
        peer = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = io.StringIO()
        started = time.monotonic()
        try:
            with contextlib.redirect_stdout(output), self.assertRaises(RuntimeError):
                module.collect_output([bad, peer], [io.StringIO(), io.StringIO()])
            self.assertIn("FTT_FAILURE gpu_out_of_memory", output.getvalue())
            self.assertIsNotNone(peer.poll())
            self.assertLess(time.monotonic() - started, 5)
        finally:
            for child in [bad, peer]:
                if child.poll() is None:
                    child.kill()
                child.wait()
                child.stdout.close()

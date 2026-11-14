import importlib.util
from pathlib import Path

import pytest

from rallymark_algorithm.runner import AnalysisFailure, validate_rallies

FTT = Path(__file__).resolve().parents[1] / "vendor/ftt"
spec = importlib.util.spec_from_file_location("postprocess", FTT / "code/postprocess_rallies.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_result_validation_rejects_overlap_and_nonfinite():
    with pytest.raises(AnalysisFailure):
        validate_rallies([{"start_s": 0, "end_s": 5}, {"start_s": 3, "end_s": 6}], 10)
    with pytest.raises(AnalysisFailure):
        validate_rallies([{"start_s": 0, "end_s": float("nan")}], 10)
    assert validate_rallies([], 10) == []


def test_vendor_top_k_and_ocr_end():
    tad = [{"start_s": 1, "end_s": 8, "score": 0.8}, {"start_s": 10, "end_s": 11, "score": 0.1}]
    ocr = [{"start_s": 3, "end_s": 5, "score": 0.7}]
    result = module.postprocess(tad, ocr, top_k=1)
    assert [(x["start_s"], x["end_s"]) for x in result["rallies"]] == [(1, 5)]


def test_score_constraints_are_part_of_product_fusion():
    ocr = [
        {
            "start_s": 1,
            "end_s": 4,
            "score": 0.99,
            "pre_score_kuai_nina": "0:0",
            "post_score_top_bottom": [0, 1],
        },
        {
            "start_s": 20,
            "end_s": 24,
            "score": 0.99,
            "pre_score_kuai_nina": "1:0",
            "post_score_top_bottom": [1, 1],
        },
    ]
    tad = [{"start_s": 10, "end_s": 12, "score": 0.9}]
    result = module.postprocess(tad, ocr, top_k=200, protect_top_m=100, score_filter=True)
    assert len(result["rallies"]) == 2
    assert result["score_constraints"]["discarded"][0]["drop_reason"] == "closed_score_gap"


def test_vendored_score_problem_set():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(FTT / "tests"), "-v"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ran " in result.stderr and "Ran 0 tests" not in result.stderr


def test_parallel_branches_overlap_and_keep_result_order():
    from threading import Barrier

    from rallymark_algorithm.runner import parallel_branches

    barrier = Barrier(2, timeout=2)

    def branch(value):
        def run(check):
            check()
            barrier.wait()
            return value

        return run

    assert parallel_branches(branch("tad"), branch("ocr"), lambda: None) == ("tad", "ocr")


def test_parallel_failure_cancels_peer_and_preserves_root_error():
    from threading import Event

    from rallymark_algorithm.runner import parallel_branches

    entered = Event()

    def fail(check):
        assert entered.wait(2)
        raise AnalysisFailure("tad_failed", "Root failure")

    def peer(check):
        entered.set()
        while True:
            check()
            entered.wait(0.01)

    with pytest.raises(AnalysisFailure, match="Root failure"):
        parallel_branches(fail, peer, lambda: None)


def test_gpu_ocr_failure_retries_cpu_without_losing_scoreboard(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from rallymark_algorithm import runner

    providers = []
    expected = [{"start_s": 1, "end_s": 4, "score": 0.99}]

    def process(command, log, deadline, check, progress=None, env=None):
        if command[0] == "ffmpeg":
            return
        provider = command[command.index("--execution-provider") + 1]
        providers.append(provider)
        if provider == "cuda":
            raise AnalysisFailure("inference_failed", "CUDA runtime failed")
        output = tmp_path / "ocr"
        (output / "predictions.json").write_text(json.dumps({"rallies": expected}))
        (output / "observations.json").write_text("[]")

    monkeypatch.setattr(runner, "process", process)
    settings = SimpleNamespace(ftt_root=tmp_path)
    config = {
        "ocr_width": 1920,
        "ocr_height": 1080,
        "ocr_crop": "540:120:85:915",
        "ocr_execution_provider": "cuda",
    }
    rows, observations, warnings = runner.run_ocr(
        tmp_path / "input.mp4", tmp_path, {"width": 1920, "height": 1080}, settings, config, 1, lambda: None
    )
    assert providers == ["cuda", "cpu"]
    assert rows == expected and observations == []
    assert warnings == ["OCR accelerator unavailable; used CPU fallback"]

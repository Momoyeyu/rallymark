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

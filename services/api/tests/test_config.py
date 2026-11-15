from types import SimpleNamespace

from rallymark_api.app import new_analysis
from rallymark_api.config import Config


def test_ocr_lookback_is_frozen_in_each_analysis_snapshot():
    config = Config()
    video = SimpleNamespace(id="video")
    previous = new_analysis(video, config)
    config.algorithm.ocr_lookback_seconds = 5.25
    current = new_analysis(video, config)
    assert previous.config["ocr_lookback_seconds"] == 4.5
    assert current.config["ocr_lookback_seconds"] == 5.25
    assert previous.config_hash != current.config_hash

from rallymark_algorithm.scores import enrich_scores


def test_observed_and_unique_interpolation():
    rallies = [{"id": str(i)} for i in range(4)]
    fused = [{"ocr_indices": [1]}, {}, {}, {"ocr_indices": [2]}]
    ocr = [{"start_s": 0, "pre_score_kuai_nina": "2:1"}, {"start_s": 30, "pre_score_kuai_nina": "5:1"}]
    result = enrich_scores(rallies, fused, ocr)
    assert [x["score"] for x in result] == ["2:1", "3:1", "4:1", "5:1"]
    assert result[1]["score_status"] == "inferred"


def test_mixed_winners_and_score_resets_are_ambiguous():
    for end in ["3:2", "0:0", "9:1"]:
        result = enrich_scores(
            [{}] * 3,
            [{"ocr_indices": [1]}, {}, {"ocr_indices": [2]}],
            [{"start_s": 0, "pre_score_kuai_nina": "2:1"}, {"start_s": 20, "pre_score_kuai_nina": end}],
        )
        assert result[1]["score"] is None
        assert result[1]["score_status"] == "unknown"


def test_missing_scores_stay_unknown_and_first_anchor_is_used():
    assert enrich_scores([{}], [{}], [])[0]["score"] is None
    result = enrich_scores(
        [{}],
        [{"ocr_indices": [2, 1]}],
        [{"start_s": 1, "pre_score_kuai_nina": "4:2"}, {"start_s": 5, "pre_score_kuai_nina": "5:2"}],
    )
    assert result[0]["score"] == "4:2"


def test_algorithm_score_decision_is_authoritative():
    fused = [
        {"ocr_indices": [1], "score_label": "1:0", "score_status": "observed"},
        {"ocr_indices": [1], "score_label": None, "score_status": "unknown"},
        {"score_label": "2:0", "score_status": "inferred"},
    ]
    result = enrich_scores([{}] * 3, fused, [{"start_s": 1, "pre_score_kuai_nina": "0:0"}])
    assert [r["score"] for r in result] == ["1:0", None, "2:0"]
    assert result[1]["score_status"] == "unknown"

import itertools
import re


def score_pair(value):
    if isinstance(value, str) and re.fullmatch(r"\d+:\d+", value):
        return tuple(int(part) for part in value.split(":"))
    return None


def enrich_scores(rallies, fused_rows, ocr_rows):
    result = [dict(row, score=None, score_status="unknown") for row in rallies]
    for row, fused in zip(result, fused_rows, strict=True):
        observations = [
            ocr_rows[index - 1] for index in fused.get("ocr_indices", []) if 1 <= index <= len(ocr_rows)
        ]
        observations.sort(key=lambda item: item["start_s"])
        for observation in observations:
            pair = score_pair(observation.get("pre_score_kuai_nina"))
            if pair is not None:
                row.update(score=f"{pair[0]}:{pair[1]}", score_status="observed")
                break
    anchors = [i for i, row in enumerate(result) if row["score"] is not None]
    for left, right in itertools.pairwise(anchors):
        a, b = score_pair(result[left]["score"]), score_pair(result[right]["score"])
        delta = (b[0] - a[0], b[1] - a[1])
        if min(delta) < 0 or sum(delta) != right - left or all(delta):
            continue
        side = 0 if delta[0] else 1
        for index in range(left + 1, right):
            score = list(a)
            score[side] += index - left
            result[index].update(score=f"{score[0]}:{score[1]}", score_status="inferred")
    return result

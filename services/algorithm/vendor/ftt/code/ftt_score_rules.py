"""Point-scoring constraints; no video annotations or player identities."""

import math
import re
from collections import deque


def score_pair(value):
    if isinstance(value, str) and re.fullmatch(r"\d{1,3}:\d{1,3}", value):
        value = tuple(map(int, value.split(":")))
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(
            isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in value
        )
    ):
        return tuple(value)
    return None


def valid_score(pair):
    pair = score_pair(pair)
    if pair is None:
        return False
    high, low = max(pair), min(pair)
    return (
        high <= 10
        or (low >= 10 and high - low <= 1)
        or (high == 11 and low <= 9)
        or (low >= 10 and high - low == 2)
    )


def is_terminal(pair):
    pair = score_pair(pair)
    return bool(
        pair is not None
        and valid_score(pair)
        and max(pair) >= 11
        and abs(pair[0] - pair[1]) >= 2
    )


def legal_step(before, after):
    before, after = score_pair(before), score_pair(after)
    return bool(
        before is not None
        and after is not None
        and valid_score(before)
        and valid_score(after)
        and not is_terminal(before)
        and (after[0] - before[0], after[1] - before[1]) in {(1, 0), (0, 1)}
    )


def _transition(row, confidence):
    pre = score_pair(row.get("pre_score", row.get("pre_score_kuai_nina")))
    post = score_pair(row.get("post_score"))
    if post is None:
        screen = score_pair(row.get("post_score_top_bottom"))
        post = screen[::-1] if screen is not None else None
    q = row.get("score", 0)
    if (
        isinstance(q, bool)
        or not isinstance(q, (float, int))
        or not math.isfinite(q)
        or not confidence <= q <= 1
        or not legal_step(pre, post)
    ):
        return None
    return dict(
        pre=pre,
        post=post,
        change_s=row.get("score_change_s", row["end_s"]),
        first=bool(row.get("first_appearance")),
    )


def _merge(target, fragment):
    target["start_s"] = min(target["start_s"], fragment["start_s"])
    target["end_s"] = max(target["end_s"], fragment["end_s"])
    for key in ["tad_indices", "ocr_indices", "original_indices"]:
        target.setdefault(key, []).extend(fragment.get(key, []))
    for key in ["score", "tad_score", "ocr_score"]:
        values = [
            r.get(key)
            for r in [target, fragment]
            if isinstance(r.get(key), (int, float))
        ]
        if values:
            target[key] = max(values)
    target["source"] = (
        "tad_ocr"
        if target.get("tad_indices") and target.get("ocr_indices")
        else ("ocr_only" if target.get("ocr_indices") else "tad_only")
    )


def _absorb(section, left, right, gap, merges):
    section = deque(section)
    while section:
        options = []
        if left is not None and section[0].get("tad_indices"):
            options.append((section[0]["start_s"] - left["end_s"], 0, left))
        if right is not None and section[-1].get("tad_indices"):
            options.append((right["start_s"] - section[-1]["end_s"], -1, right))
        if not options:
            break
        distance, index, anchor = min(options, key=lambda v: (v[0], v[1]))
        if distance > gap:
            break
        piece = section.popleft() if index == 0 else section.pop()
        anchor_index = anchor["original_indices"][0]
        _merge(anchor, piece)
        merges.append(
            dict(
                original_indices=piece["original_indices"],
                into=[anchor_index],
                gap_s=distance,
            )
        )
    return list(section)


def _infer(rows, start, target=None):
    if start is None:
        return
    count = len(rows)
    if target is None:
        if count == 1:
            rows[0].update(
                score_label=f"{start[0]}:{start[1]}", score_status="inferred"
            )
        return
    delta = (target[0] - start[0], target[1] - start[1])
    if min(delta) < 0 or sum(delta) != count:
        return
    for j, row in enumerate(rows):
        total = sum(start) + j
        low = max(start[0], target[0] - (count - j), total - target[1])
        high = min(target[0], start[0] + j, total - start[1])
        if total <= 20:
            low, high = max(low, total - 10), min(high, 10)
        else:
            low, high = max(low, total // 2), min(high, (total + 1) // 2)
        if low == high:
            row.update(score_label=f"{low}:{total - low}", score_status="inferred")


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_inputs(rallies, ocr_rows, observations):
    if not all(isinstance(v, list) for v in [rallies, ocr_rows, observations]):
        raise ValueError("Inputs must be lists")
    if len(rallies) > 10000 or len(ocr_rows) > 10000 or len(observations) > 300000:
        raise ValueError("Input exceeds documented problem limits")
    previous_end = 0
    references = set()
    for row in rallies:
        start, end = row.get("start_s"), row.get("end_s")
        if (
            not _finite(start)
            or not _finite(end)
            or start < previous_end
            or end <= start
        ):
            raise ValueError(
                "Fused intervals must be finite, sorted and non-overlapping"
            )
        previous_end = end
        for key in ["tad_indices", "ocr_indices"]:
            values = row.get(key, [])
            if not isinstance(values, list) or any(
                not isinstance(i, int) or isinstance(i, bool) or i <= 0 for i in values
            ):
                raise ValueError("Source references must be positive integer lists")
            if len(set(values)) != len(values):
                raise ValueError("Duplicate source references")
        for i in row.get("ocr_indices", []):
            if i > len(ocr_rows) or i in references:
                raise ValueError(
                    "Each OCR reference must exist and have one fused owner"
                )
            references.add(i)
    previous_time = -1
    for row in observations:
        time = row.get("t_s")
        if not _finite(time) or time < 0 or time < previous_time:
            raise ValueError("OCR observations must have sorted finite times")
        previous_time = time
    for row in ocr_rows:
        start, end = row.get("start_s"), row.get("end_s")
        change = row.get("score_change_s", end)
        if (
            not _finite(start)
            or not _finite(end)
            or start < 0
            or end <= start
            or not _finite(change)
            or change < end
        ):
            raise ValueError("OCR evidence timestamps are invalid")


def filter_scores(
    rallies,
    ocr_rows,
    *,
    fragment_gap_s=1.0,
    confidence_min=0.8,
    edge_window_s=30,
    video_duration_s=None,
    score_observations=None,
):
    for value, limit in [
        (fragment_gap_s, 5),
        (confidence_min, 1),
        (edge_window_s, 120),
    ]:
        if not _finite(value) or not 0 <= value <= limit:
            raise ValueError("Invalid score-constraint parameters")
    if video_duration_s is not None and (
        not _finite(video_duration_s) or video_duration_s <= 0
    ):
        raise ValueError("Video duration must be finite and positive")
    _validate_inputs(rallies, ocr_rows, score_observations or [])
    observations = [
        (r["t_s"], score_pair(r.get("score"))) for r in score_observations or []
    ]
    observations = [(t, pair) for t, pair in observations if pair and valid_score(pair)]
    observation_index = 0
    rows = []
    anchors = []
    warnings = []
    for i, original in enumerate(rallies):
        row = dict(
            original, original_indices=[i + 1], score_label=None, score_status="unknown"
        )
        for key in ["tad_indices", "ocr_indices"]:
            row[key] = list(original.get(key, []))
        transitions = [
            _transition(ocr_rows[j - 1], confidence_min)
            for j in row.get("ocr_indices", [])
            if 1 <= j <= len(ocr_rows)
        ]
        observed = [t for t in transitions if t and not t["first"]]
        unique = {(t["pre"], t["post"]) for t in observed}
        if len(unique) == 1:
            t = observed[-1]
            row["_anchor"] = t
            row.update(
                score_label=f"{t['pre'][0]}:{t['pre'][1]}",
                score_status="observed",
                score_evidence=dict(
                    pre=list(t["pre"]), post=list(t["post"]), change_s=t["change_s"]
                ),
            )
            anchors.append(i)
        elif len(unique) > 1:
            row["_conflict"] = True
            warnings.append(
                "Multiple score transitions share one fused interval; uncertain context retained"
            )
        rows.append(row)
    if not anchors:
        return dict(
            rallies=[
                {k: v for k, v in r.items() if not k.startswith("_")} for r in rows
            ],
            discarded=[],
            merged_fragments=[],
            warnings=["No reliable score transitions; intervals unchanged"],
        )
    discarded = []
    merges = []
    output = []
    first = rows[anchors[0]]
    prefix = rows[: anchors[0]]
    prefix = _absorb(prefix, None, first, fragment_gap_s, merges)
    budget = sum(first["_anchor"]["pre"])
    previous_read = any(
        t < first["start_s"] and sum(pair) > budget for t, pair in observations
    )
    if (
        edge_window_s
        and first["start_s"] <= edge_window_s
        and not previous_read
        and not any(r.get("_conflict") for r in prefix)
    ):
        ranked = sorted(
            prefix,
            key=lambda r: (
                -(r.get("tad_score") or 0),
                -(r["end_s"] - r["start_s"]),
                r["start_s"],
            ),
        )
        keep = {id(r) for r in ranked[:budget]}
        for row in prefix:
            if id(row) not in keep:
                discarded.append(
                    dict(row, drop_reason="prefix_score_budget", point_budget=budget)
                )
        prefix = [r for r in prefix if id(r) in keep]
        _infer(prefix, (0, 0), first["_anchor"]["pre"])
    output.extend(prefix)
    output.append(first)
    for left_index, right_index in zip(anchors, anchors[1:]):
        left, right = rows[left_index], rows[right_index]
        section = rows[left_index + 1 : right_index]
        after, before = left["_anchor"]["post"], right["_anchor"]["pre"]
        delta = (before[0] - after[0], before[1] - after[1])
        reset_evidence = False
        while (
            observation_index < len(observations)
            and observations[observation_index][0] < right["start_s"]
        ):
            t, pair = observations[observation_index]
            # Raw OCR uses screen top:bottom; anchors use bottom:top.
            pair = pair[::-1]
            if t > left["_anchor"]["change_s"] and any(
                not after[k] <= pair[k] <= before[k] for k in (0, 1)
            ):
                reset_evidence = True
            observation_index += 1
        consistent = (
            not reset_evidence
            and min(delta) >= 0
            and not is_terminal(after)
            and not any(r.get("_conflict") for r in section)
        )
        if consistent:
            section = _absorb(section, left, right, fragment_gap_s, merges)
            budget = sum(delta)
            if budget == 0:
                discarded.extend(
                    dict(
                        r,
                        drop_reason="closed_score_gap",
                        point_budget=0,
                        left_post=list(after),
                        right_pre=list(before),
                    )
                    for r in section
                )
                section = []
            else:
                _infer(section, after, before)
        else:
            warnings.append(
                "Score reset or contradiction: intervening candidates retained"
            )
        output.extend(section)
        output.append(right)
    last = rows[anchors[-1]]
    tail = rows[anchors[-1] + 1 :]
    after = last["_anchor"]["post"]
    change = last["_anchor"]["change_s"]
    later_reset = any(
        t > change and sum(pair) < sum(after) - 2 for t, pair in observations
    )
    if not later_reset:
        tail = _absorb(tail, last, None, fragment_gap_s, merges)
    closed = (
        edge_window_s
        and is_terminal(after)
        and video_duration_s is not None
        and 0 <= video_duration_s - change <= edge_window_s
        and not later_reset
    )
    if closed:
        discarded.extend(
            dict(r, drop_reason="confirmed_game_end", final_score=list(after))
            for r in tail
        )
        tail = []
    else:
        # Without an end score, separate close TAD pieces but keep all possible points.
        clusters = []
        for row in tail:
            if (
                not later_reset
                and not is_terminal(after)
                and clusters
                and row.get("tad_indices")
                and clusters[-1].get("tad_indices")
                and row["start_s"] - clusters[-1]["end_s"] <= fragment_gap_s
            ):
                _merge(clusters[-1], row)
            else:
                clusters.append(row)
        tail = clusters
        if not later_reset and not is_terminal(after):
            _infer(tail, after)
    output.extend(tail)

    def clean(r):
        out = {k: v for k, v in r.items() if not k.startswith("_")}
        for key in ["tad_indices", "ocr_indices", "original_indices"]:
            out[key] = sorted(set(out.get(key, [])))
        return out

    return dict(
        rallies=[clean(r) for r in output],
        discarded=[clean(r) for r in discarded],
        merged_fragments=merges,
        warnings=list(dict.fromkeys(warnings)),
    )

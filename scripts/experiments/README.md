# Offline fusion parameter evaluation

Run from the repository root after raw TAD/OCR predictions exist for all videos:

```sh
services/algorithm/.venv/bin/python scripts/experiments/evaluate_grid.py \
  --experiment .runtime/experiments/20261113-001 \
  --output .runtime/experiments/20261113-001/results/evaluation
```

This CPU-only script imports the production postprocessor and score enrichment directly. It never changes deployment settings or passes ground truth to inference. Default search is every integer Top K from 30 through 200 and every 0.25 seconds from 1 through 10 inclusive: 6,327 configurations per video, 37,962 evaluations for six videos. Identical output intervals share cached metric calculations, while every configuration still runs the postprocessor.

Inputs use `{ "rallies": [{ "start_s": 1, "end_s": 5, "score": ... }] }` (a bare list also works). Ground-truth score labels are ignored. Files are `gt/<video>.json`, `raw/<video>/tad/predictions.json`, and `raw/<video>/ocr/predictions.json`. Default IDs are `nina sun harimoto hayata wang chen`. Use `--videos` to override; at least two IDs are required. `--interval-step 1` supports a quicker integer-only search. `--top-k-min` and `--top-k-max` are useful for smoke checks. Baseline `(200,5)` is evaluated even when outside a custom search.

Metrics use continuous seconds with no rasterization or tolerance padding. Manual labels have one-second precision. Duration TP is the intersection of interval unions; FP and FN are the remaining prediction and GT union duration. Event matches use maximum cardinality one-to-one bipartite matching at IoU ≥0.3 and ≥0.5. Thus a single merged interval cannot match several GT rallies. Coverage recall counts GT rallies whose interval is at least 50% covered by the prediction union. `coverage_zero_missed_rounds` counts completely missed GT rallies with exactly zero temporal intersection; this is distinct from under-50% coverage and event IoU≥0.5 false negatives. `coverage_90_recall` reports the fraction with at least 90% temporal coverage to expose replay truncation. Aggregate JSON includes the pooled total completely missed rounds and pooled ≥90% recall; policy comparison CSV includes both metrics. Coverage is deliberately reported beside event precision/F1 because coverage alone rewards giant merged predictions. Both sets empty means P/R/F=1; only one empty means P/R/F=0.

Selection maximizes the video macro average of `(duration F2 + event IoU≥0.5 F2)/2`, then the equivalent mean F1, event F1, and coverage recall. F2 weights recall more strongly; the event term guards overmerging. Remaining ties prefer distance to nearby=5, then distance to Top K=200, then smaller nearby and Top K. This policy is declared before inspecting results. The summary also includes the best-F1 alternative and the non-dominated macro recall/precision frontier, retaining parameter ties. A recall-priority alternative requires macro selection F1 at least 90% of the best macro selection F1, then minimizes coverage-missed rounds, minimizes event IoU≥0.5 missed rounds, maximizes duration recall, and maximizes F1, followed by the same parameter tie breaks. F2, F1, and constrained recall policies each receive a separate leave-one-video-out estimate. The F1 floor is recomputed using only the five training videos in every fold.

Each leave-one-video-out fold selects only from the other videos' metric rows and then evaluates its held-out video. The held-out predictions in `selected/` use that fold's training-selected parameters. Six videos provide an exploratory estimate with considerable uncertainty; shared player, broadcast, or source conditions can limit independence. In-sample and per-video oracle results are optimistic diagnostics and must not be interpreted as held-out performance.

Outputs:

- `grid.csv`: all video/configuration/metric rows.
- `comparison.csv`: per-video baseline, global in-sample selections, held-out selections, and per-video oracle comparison.
- `policy_comparison.csv`: seven aggregate rows comparing baseline and F2/F1/constrained-recall in-sample and held-out policies, including total missed rounds and FN duration.
- `summary.json`: policy, metric definitions, input/code SHA256 provenance, baseline, in-sample best, best-F1 alternative, Pareto frontier, six held-out folds and macro/pooled metrics.
- `complete.json`: success marker written last, containing the summary hash and evaluated row count. A new run removes any prior marker before loading inputs. Wait for this marker before consuming results.
- `selected/<video>.json`: fold-selected parameters, metrics, score-enriched rallies, full fusion result and input provenance. Confidence stays in the fusion result; enriched rally `score` is the OCR-derived score label.

Nina’s full 6,327-point grid took about 2.1 CPU seconds in the current environment (200 TAD proposals, 15 OCR and 15 GT rallies, 146 distinct interval outputs). Timing depends on source interval counts; the default six-video search should be practical on a laptop. Inference must finish before evaluation starts. Keep all generated artifacts under ignored `.runtime/`. Run focused analytic checks with:

```sh
services/algorithm/.venv/bin/python -m pytest scripts/experiments/tests -q
services/algorithm/.venv/bin/ruff check scripts/experiments
services/algorithm/.venv/bin/ruff format --check scripts/experiments
```

## Scoreboard layout calibration

The frozen OCR expects a particular 1920×1080 broadcast layout. Its horizontal crop can be calibrated from video pixels, without GT:

```sh
services/algorithm/.venv/bin/python scripts/experiments/ocr_layout.py \
  <video.mp4> --output <layout.json>
```

This optional command requires the algorithm GPU extras (OpenCV and NumPy); CUDA itself is not used. It samples 12 bin centers over the first 60 seconds, searches horizontal offsets −85…150 for the existing 53px magenta games column, uses the original 0.5 occupancy predicate, and requires at least three consistent visible samples. Absent overlays do not vote on location. Unsupported dimensions fail explicitly; uncertain layouts use the old X=85 crop with a warning. Vertical relocation and different scoreboard designs remain unsupported. Freeze this rule before evaluating GT.

After the original inference is complete, retain its fixed-crop outputs and rerun only OCR:

```sh
services/algorithm/.venv/bin/python scripts/experiments/ocr_layout.py \
  <video.mp4> --rerun-ocr <raw/video> \
  --ocr-script services/algorithm/vendor/ftt/ocr/run_scoreboard_ocr.py
```

The wrapper preserves `ocr_fixed/`, writes calibrated `ocr/` and `layout.json`, and publishes `ocr/layout_calibration.json` last with source hashes, crop, timings and exit status. It is resumable after that marker. The original OCR CSV writer fails for zero rallies after writing valid JSON; the wrapper records that nonzero status and permits an empty result only when the JSON exists. Other nonempty failed results raise an error. Keep the executed wrapper source as well as hashes when copying a running experiment between machines.

## Export and visualize

Export all videos with one common selected configuration, rather than the different per-fold configurations in `selected/`:

```sh
services/algorithm/.venv/bin/python scripts/experiments/export_review.py \
  --experiment .runtime/experiments/20261113-001 \
  --evaluation .runtime/experiments/20261113-001/results/evaluation \
  --policy recall_priority_alternative
```

`review/` contains six score-enriched JSON files, the common parameters, and a relative video/metadata manifest. The exporter verifies evaluation completion, input hashes and fusion/score code hashes. GT contributes display titles only, never predicted intervals or scores. Metadata includes original size, SHA-256 and duration; [local review](../../apps/web/LOCAL_REVIEW.md) validates size and duration when pairing files. Changing the chosen policy requires an explicit export command; deployment YAML is not silently changed.

A separate, pinned plotting environment avoids adding scientific plotting libraries to product services:

```sh
uv run scripts/experiments/plot_grid.py \
  --evaluation .runtime/experiments/20261113-001/results/evaluation \
  --output .runtime/experiments/20261113-001/results/parameter-grid.png
```

Before releasing rented compute, verify video checksums and all raw/calibrated completion markers locally, archive raw predictions, sources, GT, grid, selected parameters and exported metadata, then drain and release the instance. Video files and generated raw data remain outside Git; curated reports belong under `docs/<date>-<sequence>/`.

An explicitly chosen operating point from the completed grid can also be exported with `--policy custom --top-k 200 --nearby-seconds 2`. Both values must belong to the evaluated grid. This is a manual, potentially post-hoc choice; it is not a new held-out policy estimate. Preserve alternate exports in separate directories before overwriting `review/`.

## Omission-first expanded search

The follow-up [six-match study](../../docs/20261113-002/report.md) separates the unchanged-rule search from an experimental protected-orphan rule. Production postprocessing and deployment defaults are not changed.

```sh
services/algorithm/.venv/bin/python scripts/experiments/search_extended.py \
  --input .runtime/experiments/20261113-001 \
  --output .runtime/experiments/20261113-002/unchanged

services/algorithm/.venv/bin/python scripts/experiments/search_guarded.py \
  --input .runtime/experiments/20261113-001 \
  --output .runtime/experiments/20261113-002/guarded
```

`search_extended.py` uses the same production merge helpers, broadens Top-N to1…200 and distance to1…30s, and ranks misses before false rallies. It caches interval-equivalent metric calculations. The original 37,962 rows were checked against the old grid, with all metrics equal within1e-12.

`search_guarded.py` adds a minimum duration for TAD-only orphans and protection for merged orphans containing any global top-M TAD member. Protected orphans bypass nearby exclusion, after the duration check. OCR and mixed intervals are unchanged. Inputs never include GT inside either fusion function. The selection constraint requires every previously covered GT-positive second to remain covered and each video's IoU0.3/0.5 FN not to increase. Among feasible configurations, omissions/FN precede FP in the ranking. These constraints apply only to evaluation/selection, not to inference on a new video.

Use `--refine` for the declared local N/M/duration grid, then `--confirm` for N200, every M0…200, quarter-second distances1…30 plus45/60/600, and quarter-second minimum durations0…2. The600s sentinel tests suppression of all unprotected orphans in these videos. Each phase writes all rows, its protocol and input/source hashes, a summary with training-only selection folds, and score-enriched metadata. Completion is published after exports.

The omission-first operational comparison fixes the minimum duration to0.5s and uses integer distances. It reuses confirmation rows rather than rerunning fusion:

```sh
services/algorithm/.venv/bin/python scripts/experiments/search_guarded.py \
  --input .runtime/experiments/20261113-001 \
  --output .runtime/experiments/20261113-002/conservative \
  --conservative-from .runtime/experiments/20261113-002/confirmation/grid.csv
```

This validates completion and identical input provenance before rescreening. Phase modes are mutually exclusive. Metadata directories `review-no_regression/`, `review-long_gap/`, and `review-counts_only/` are written beside each phase's output directory; preserve prior exports before the next phase overwrites them. The study keeps final operational metadata in `review/` and the more aggressive duration filter in `review-fewer-false/`.

Do not interpret the fixed-rule leave-one-video-out checks as an untouched test set: method design and refinement ranges have already been informed by these six matches. The report records the observed failure of aggressive duration tuning and the conservative restriction adopted afterward.

## FTT 比分约束结果导入

算法题库与参数搜索在独立 FTT 仓库完成后，用以下命令导入并逐字段验证产品适配器（不需要 GPU）：

```sh
services/algorithm/.venv/bin/python scripts/experiments/import_ftt_results.py \
  --source ../ftt-demo/results/20261113-003 \
  --output .runtime/experiments/20261113-003
```

导入会校验原片 SHA-256、保留原始数据并生成六份可离线播放的 review metadata。研究指标和边界见 [本次实验报告](../../docs/20261113-003/report.md)。

# FTT source snapshot

Source repository https://github.com/Momoyeyu/ftt-demo at commit c836c83bbbfa0327a25f6cb6077cafa83bb69f10 (score-constrained postprocessing, OCR, layout calibration and configuration); unchanged backbone/inference snapshot 540cc9fb903698d57658dbd7bd98a758ede577e0.

Includes inference modules, matching configs/class maps, scoreboard OCR and postprocessing,
OpenTAD/V-JEPA2 and the bundled timm compatibility snapshot. Video, GT and weights are excluded.
SHA256_MANIFEST.json records the upstream asset hashes. Code in this directory is a vendor
snapshot and retains its original third-party licenses. OpenTAD, V-JEPA2 and timm license files
are included in their respective trees. No overall relicensing is asserted.

Local adaptation in infer_ftt_single_video_20261110.py sets both backbone paths from
WEIGHTS_ROOT before loading. The inference math, sampling, NMS and checkpoint are unchanged.
Updates should replace this snapshot explicitly and run the sample GPU acceptance test.

The score stage was evaluated first in FTT across six matches and 11,653 configurations.
See docs/20261113-003/report.md and the FTT source commit for the development metrics and limitations.
No model weights, sampling or GPU math changed in this update.

The synthetic score problem fixtures and independent oracle tests are included from this same source commit and run in product CI. Their authority remains the FTT repository.

Performance update: FTT commit a5143b9 adds optional per-thread decoder reuse and bounded ordered prefetch, retaining the 768/384 global windows, frame tensors, inference math and global NMS. All 33 sample-window tensor hashes and all 200 rally / 500 action outputs match the baseline. OCR adds explicit CPU/CUDA selection and provider validation. The product runs the two subprocess branches in parallel with independent logs and cancellation; CUDA OCR failures retry on CPU. See FTT docs/20261114-002 for measured ablations. NumPy 1.26.4 and ORT GPU 1.16.3 are pinned in the product GPU lock; the CPU ORT distribution is excluded on Linux to avoid overwriting the shared module.

Multi-GPU update: FTT commit 4781dc8 partitions unchanged global 768/384 windows contiguously across reserved GPUs, concatenates raw window predictions in original order and runs global NMS once. No video segmentation or re-encoding occurs. Hardware allocation is recorded per attempt, separately from immutable inference hyperparameters. See FTT docs/20261114-004 for measured allocation experiments and limits.

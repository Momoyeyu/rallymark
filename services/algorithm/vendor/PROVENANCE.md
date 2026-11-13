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

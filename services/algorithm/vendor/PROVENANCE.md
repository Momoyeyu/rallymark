# FTT source snapshot

Source repository https://github.com/Momoyeyu/ftt-demo at commit 540cc9fb903698d57658dbd7bd98a758ede577e0.

Includes inference modules, matching configs/class maps, scoreboard OCR and postprocessing,
OpenTAD/V-JEPA2 and the bundled timm compatibility snapshot. Video, GT and weights are excluded.
SHA256_MANIFEST.json records the upstream asset hashes. Code in this directory is a vendor
snapshot and retains its original third-party licenses. OpenTAD, V-JEPA2 and timm license files
are included in their respective trees. No overall relicensing is asserted.

Local adaptation in infer_ftt_single_video_20261110.py sets both backbone paths from
WEIGHTS_ROOT before loading. The inference math, sampling, NMS and checkpoint are unchanged.
Updates should replace this snapshot explicitly and run the sample GPU acceptance test.

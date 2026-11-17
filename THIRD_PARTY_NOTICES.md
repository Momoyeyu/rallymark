# Third-party sources and model assets

RallyMark's original source is licensed under Apache License 2.0. This does not
relicense third-party code, pretrained weights or supplied evaluation videos.

The verified algorithm snapshot derives from
https://www.modelscope.ai/models/yubodata/ftt-dual-adapter-tad-ocr-15raw.
Its repository metadata specifies Apache 2.0 and explicitly preserves upstream
licenses. Source revisions and adaptations are recorded in
[algorithm provenance](services/algorithm/vendor/PROVENANCE.md). Included OpenTAD,
V-JEPA2 and timm trees retain their own license files and copyright notices.

Required assets include the FTT trainable checkpoint, VideoMAEv2 backbone,
V-JEPA2 encoder and RapidOCR ONNX models. Their upstream terms continue to apply;
copying the files into a ModelScope project does not change those terms. Asset
hashes are recorded in the deployment manifest and snapshot inventory.

Match videos and ground-truth annotations are supplied evaluation material.
No additional rights in that material are asserted by the source-code license.

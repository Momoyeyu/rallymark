# Third-party sources and model assets

## FTT

The RallyMark algorithm snapshot derives from
[yubodata/ftt-dual-adapter-tad-ocr-15raw](https://www.modelscope.ai/models/yubodata/ftt-dual-adapter-tad-ocr-15raw),
published by yubodata. The FTT release identifies its license as Apache 2.0 and
preserves the original terms for third-party code and pretrained weights.
The [Apache License 2.0 text](LICENSE) accompanies this distribution.
[Algorithm provenance](services/algorithm/vendor/PROVENANCE.md) records source
revisions and RallyMark's changes. Modified FTT inference and OCR files carry
change notices. The bundled upstream license and copyright notices remain with
their respective source trees.

## Model artifacts

| Component | Source and terms |
| --- | --- |
| FTT dual-adapter trainable checkpoint, seed 42, epoch 35 | Distributed by [yubodata in the FTT release](https://www.modelscope.ai/models/yubodata/ftt-dual-adapter-tad-ocr-15raw) under its Apache 2.0 license designation. It contains trainable adapter, fusion, detection and relation layers and requires both backbones. |
| VideoMAEv2-G backbone | OpenGVLab's [VideoMAEv2 project](https://github.com/OpenGVLab/VideoMAEv2). This distribution carries the specific backbone file packaged by FTT. Consult the upstream terms applicable to that artifact. |
| V-JEPA 2.1 ViT-G KDBD encoder | Meta FAIR's [V-JEPA 2 project](https://github.com/facebookresearch/vjepa2). This distribution carries the specific encoder file packaged by FTT. Consult the upstream terms applicable to that artifact. |
| Three RapidOCR ONNX models | The PP-OCR detection, recognition and orientation models supplied by FTT come from [RapidOCR](https://github.com/RapidAI/RapidOCR#-license), which attributes the original PaddleOCR models to Baidu and the respective rights holders and documents Apache 2.0 for the converted models. |

Model files ship through the [RallyMark ModelScope release](https://www.modelscope.ai/models/momoyeyu/rallymark). The [FTT asset manifest](services/algorithm/vendor/ftt/SHA256_MANIFEST.json) records their upstream SHA-256 hashes.

## Bundled source

- [OpenTAD](services/algorithm/vendor/ftt/code/third_party/OpenTAD/LICENSE) ships with its Apache 2.0 license.
- [V-JEPA2](services/algorithm/vendor/ftt/code/third_party/vjepa2/LICENSE) ships with its MIT license. Separately licensed source files retain their notices.
- [timm](services/algorithm/vendor/ftt/code/env_pack/pylib_opentad/timm-1.0.29.dist-info/licenses/LICENSE) ships with its bundled license and notices.

## Evaluation materials

Match videos and ground-truth annotations are supplied for evaluation. Rights
in this material remain with the respective rights holders. RallyMark's
Apache 2.0 grant covers its source and Apache-licensed FTT adaptations.

# Original-input deployment — 2026-11-15

Application and preview images: `df59cc9`. Operator scripts: `3db3215`.
The target is selected through `.runtime/target.env`; application source does
not select the host or GPU model.

- Application: http://10.106.131.204:8080/
- Six-match static preview: http://10.106.131.204:8081/

## Active policy and preset

Do not apply the experimental frame-rate, resolution or bitrate compression.
Keep compatible H.264 MP4 input unchanged. Retain necessary MOV remuxing and
HEVC/rotation/HDR/timestamp compatibility preparation described in
[media ingestion](../media-ingestion.md).

| Parameter | Value |
|---|---:|
| TAD Top-N | 195 |
| Nearby exclusion | 9 s |
| Protected candidates | 100 |
| Minimum duration | 0.5 s |
| Fragment gap | 1 s |
| Score confidence | 0.9 |
| Edge window | 60 s |
| OCR lookback | 5.25 s |

Score filtering and parallel TAD/OCR remain enabled. OCR uses CUDA; GPU
discovery and assignment remain inside the algorithm service. Legacy task
snapshots without the new OCR lookback field retain their previous behavior.
The research comparison is in
[FTT report 009](http://gitlab.local/sujunjie/ftt-demo/-/blob/master/docs/009-frame-rate-ablation.md).

## Verification

- `make check` passed, including both frontend builds and generated contracts.
- `make test` passed: API 34, algorithm 35, experiment 21, frontend 22 and
  operator/preview 19 tests. Local database/environment-specific skips: API 2,
  algorithm 4. After the deployment script fix, all 20 operator/preview tests
  passed, including the new proxy refresh regression.
- API and algorithm configuration snapshots match. Running the product adapter
  against the six frozen original-input TAD/OCR outputs reproduces the FTT
  reference rally arrays exactly: 24, 20, 24, 15, 19 and 19, totaling 121.
  This is cached-output parity, not six fresh GPU runs.
- The deployed preview manifest matches the local export. All six original
  videos return HTTP 206 with correct content lengths; both frontend roots
  return HTTP 200. Preview metadata uses this preset and retains original files.
- A fresh `make smoke-gpu` upload completed real inference with 15 rallies,
  no warnings, working Range playback and anonymous ownership isolation.
  Video ID: `1ca92403-c146-4276-bef1-b8cc442d9b36`.
  Analysis ID: `213f3f5a-9b96-4a14-987c-212092136276`.
- Its immutable configuration hash is
  `1ed75219d314d2ad29b3919a1a2b6b0377bcc9cdb0b95571c7d335c9a9e81821`.
  TAD processed 33 global windows and all 13,001 frames at 1920×1080. The worker
  assigned two available GPUs dynamically. All three OCR sessions reported
  CUDAExecutionProvider. This smoke is not a single-GPU benchmark.

### Input preservation audit

The Nina source has a `.mp4` filename but QuickTime (`qt`) container branding,
so business preparation remuxed it to MP4 with video stream copy. Original and
prepared files have **identical hashes for every ordered encoded video packet**
and the same 13,001 frames. No video re-encoding, frame removal or downscaling
occurred. Container hashes and reported average frame rate can change during
remuxing; this alone does not imply compression.

| Artifact | SHA-256 |
|---|---|
| Uploaded source | `7ca9a05e2f68284412519c18192154f8af5ce0e142a5c039417269ca04a5bf83` |
| Prepared MP4 / algorithm input | `a15367aab872c32a54656b131bcefa289323e2b69851d60674854e370a99a902` |

Business media and downloaded algorithm input hashes match. Detailed sanitized
receipts and raw attempt metadata are retained locally under
`.runtime/validation/original-input/`; videos, model weights and secrets stay
outside Git.

## Deployment recovery

Database/configuration checkpoint: `backups/20261115-205954/` on the target,
also copied to local `backups/kuanguang-204-20261115-205954/`. Previous images
and persistent volumes were retained. The new image was first deployed with
the old configuration before applying the new preset, since the previous
release does not understand the new lookback field.

Configuration application exposed a stale Nginx upstream IP after API
recreation. Operator scripts now recreate the web proxy together with services;
the fixed operation passed with external session and capacity requests.

Rollback to the previous image requires its compatible configuration:

```sh
make rollback VERSION=01556b1 CONFIG_FILE=../backups/20261115-205954/config.yaml
```

See [operations](../operations.md) for configuration, deployment and data safety.

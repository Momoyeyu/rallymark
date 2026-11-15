# RallyMark

RallyMark identifies rallies in table-tennis match videos and lets viewers jump between them while playing the original video. The interface prioritizes mobile screens and requires no login.

## First release

Upload an MP4/MOV video using H.264 or HEVC, up to 500 MB and 15 minutes. Local format and size checks run before transfer; necessary media preparation runs in the business service before analysis. Then review rally markers. Previous/next buttons seek and play in one action. Automatic skipping is enabled by default, pauses after the final rally, and turns off when the viewer manually scrubs. The same browser retains anonymous history for seven days.

TAD is the primary detector. Scoreboard OCR assists boundaries where the supported broadcast layout is recognized; other layouts receive a TAD-only result with a warning. Algorithm parameters live in deployment YAML, not user-facing controls. Experimental tuning continues in the independent FTT demo repository.

See [media ingestion](docs/media-ingestion.md) for supported formats, conversion and recovery.

Production analyzes compatible original video bytes without experimental frame-rate,
resolution or bitrate compression. The deployed original-input preset uses Top-195,
a nine-second neighborhood, protected Top-100 and a 5.25-second OCR lookback.
Necessary MOV/HEVC compatibility preparation follows the media-ingestion policy.

## Development

~~~sh
make setup
make dev
make check
make test
~~~

The development Compose stack uses a fake algorithm runner. It requires Docker Compose 2.24.4 or newer. Run make help for commands. Choose the SSH deployment target in .runtime/target.env and the target's GPU and paths in its .runtime/deploy.env. Use make deploy VERSION=<commit-sha> to build and deploy on that host. Follow [operations](docs/operations.md) for setup, migration, cleanup, backup and rollback.

For playback with existing original videos and analysis JSON, use [local review](apps/web/LOCAL_REVIEW.md). Only the web application runs; no API or GPU is required. [Offline evaluation](scripts/experiments/README.md) documents reproducible parameter searches.

The [score-constrained follow-up](docs/20261113-003/report.md) records the FTT-first implementation, 11,653 configurations, six-match results and the maintained algorithm problem set.

The [omission-first follow-up](docs/20261113-002/report.md) tests longer exclusion distances with protected TAD candidates and preserves GPU-free review metadata.

The [six-match parameter experiment](docs/20261113-001/report.md) records recall/F1 tradeoffs, held-out parameter selection, known boundary failures, and the local review data layout.

## Structure

| Directory | Responsibility |
| --- | --- |
| apps/web | React, TypeScript and mobile playback |
| services/api | FastAPI sessions, uploads, tasks and media |
| services/algorithm | Internal FastAPI job API, GPU worker and algorithm adapter |
| contracts | API schema and generated client types |
| deploy | Docker images, Compose and configuration |
| scripts | Shared development and operator commands |

See [architecture](docs/architecture.md) for service and persistence boundaries. [AGENTS.md](AGENTS.md) summarizes repository conventions. GitLab is the primary internal repository; GitHub is a private auxiliary remote. The default branch is master.

只读六场预览：`make preview-export`、`make preview-build`、
`make preview-deploy VERSION=<commit>`。正式站与预览站共用播放器和 UI，预览站
没有上传入口，也不依赖算法服务。[部署与 GPU 维护模式](docs/operations.md#gpu-maintenance-and-static-preview)。

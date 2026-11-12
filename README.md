# RallyMark

RallyMark identifies rallies in table-tennis match videos and lets viewers jump between them while playing the original video. The interface prioritizes mobile screens and requires no login.

## First release

Upload an MP4/H.264 video up to 500 MB and 15 minutes, wait for analysis, then review rally markers. Previous/next buttons seek and play in one action. Automatic skipping is enabled by default, pauses after the final rally, and turns off when the viewer manually scrubs. The same browser retains anonymous history for seven days.

TAD is the primary detector. Scoreboard OCR assists boundaries where the supported broadcast layout is recognized; other layouts receive a TAD-only result with a warning. Algorithm parameters live in deployment YAML, not user-facing controls. Experimental tuning continues in the independent FTT demo repository.

## Development

~~~sh
make setup
make dev
make check
make test
~~~

The development Compose stack uses a fake algorithm runner. It requires Docker Compose 2.24.4 or newer. Run make help for commands. Use make deploy VERSION=<commit-sha> LOCAL_BUILD=1 on a host without a configured image registry. Follow [operations](docs/operations.md) for real GPU deployment, configuration, cleanup, backup and rollback.

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

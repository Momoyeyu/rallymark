# Static preview and GPU maintenance deployment — 2026-11-13

Application images: `4c1f148`. Deployment target: `kuanguang-gpu` (selected via
operator configuration, not embedded in application source).

- Formal application: http://10.106.128.145:8080/
- Six-match read-only preview: http://10.106.128.145:8081/

The GPU repair task confirmed that hardware remains unavailable after a full
power reset. Production therefore uses `GPU_MODE=disabled`. Web, business API,
algorithm API, PostgreSQL and the explicit unavailable worker are deployed.
The preview runs in a separate Compose project and has no API dependency.

## Verification

- `make check` passed, including both production frontend builds and generated
  contract consistency. Formal web assets still exclude development importers.
- `make test` passed: business API 22, algorithm 18, experiment evaluation 21,
  frontend 21; PostgreSQL/GPU-specific tests were skipped locally. Operator and
  preview-export tests: 19 passed. No GPU inference success is claimed.
- Browser suite: 8 passed. Includes six independent preview selections, playback,
  zero upload controls or API requests, mobile boundaries, and unavailable
  preflight preventing video transfer.
- Actual deployed preview: all six originals loaded and played after one click
  on the next-round button. All six media endpoints returned HTTP 206 for
  `bytes=0-127`, with exactly 128 bytes and correct total lengths. Deployment
  checksums matched all six exported content-hash filenames.
- Actual deployed pages: 390×844 mobile and 1920×1080 desktop inspected; no
  horizontal overflow. Maintained browser coverage also checks 320px and 844px.
- Actual production upload preflight: HTTP 503 `analysis_unavailable`, concise
  Chinese message, zero upload POST requests. Its request ID appeared in both
  `analysis_unavailable` and `http_request` backend log records. No model paths,
  credentials, driver details or traceback were sent to the browser.
- Rejected algorithm-result errors also carry the same problem identifier in
  the dispatcher log and the public error; a regression test verifies correlation.
- Existing owned video remained readable: HTTP 206, `bytes 0-127/143459068`.
- Healthy busy-worker capacity is tested independently: accepted as `busy`, not
  rejected as unavailable. Missing, stale and incompatible workers are excluded.
- `make doctor` passed in configured maintenance mode. Database/API/web/preview
  health checks passed; the maintenance worker publishes unavailable heartbeats.

| Match | Duration (s) | Rallies | Video bytes |
|---|---:|---:|---:|
| chen | 522.02 | 24 | 302438078 |
| harimoto | 462.02 | 20 | 260263653 |
| hayata | 548.02 | 24 | 307579910 |
| nina | 260.04 | 15 | 143459068 |
| sun | 411.02 | 19 | 240306036 |
| wang | 312.02 | 19 | 167559207 |

## Recovery and operations

Before changing the deployment, database dump, deployment environment, old
version, source commit and volume mapping were saved in the target checkout at
`.runtime/backups/pre-preview-20261113/`. Existing media/database volumes were
retained. Current formal version is `4c1f148`; previous maintenance-capable
version is `c7c35d8`. No GPU driver or firmware changes were made by this task.

See [operations](../operations.md#gpu-maintenance-and-static-preview) for preview
export/deployment commands and switching back to real GPU execution after repair.
Local screenshots and verbose verification logs stay under `.runtime/`.

# Adaptive GPU deployment implementation plan

**Goal:** Deploy the current product and six-match preview on the configured final host, using measured, load-aware multi-GPU execution.

**Architecture:** Preserve original global TAD windows and perform NMS once after ordered shard collection. Compare per-job sharding against independent jobs before selecting the default. Discover allowed GPUs at runtime; reserve by stable UUID in PostgreSQL before claiming work. Busy external devices remain untouched; queued jobs wait without consuming attempts. All host settings remain outside Git.

**Constraints:** Preserve input video bytes, inference window context, scores/postprocessing, anonymous ownership, task snapshots and durable leases. No input compression. Never preempt another user's workload. Keep raw experiment evidence locally. GitLab primary / GitHub secondary.

## Tasks

- [x] FTT: benchmark 1/2/4 GPUs (three repeats), separate OCR placement, batch throughput and reduced-capacity cases. Compare all predictions and six-match evaluation; select policy from latency, throughput and contention data.
- [x] Algorithm: tests first for partition union/order, device filtering, stale observations, reservation exclusion/release and queue fairness; implement bounded sharding and adaptive reservation. Cancellation terminates all process groups before releasing cards.
- [x] Deploy: expose configured pool to worker, update doctor/settings/docs; preserve disabled/fake modes and rollback. Run maintained CPU checks and PostgreSQL tests.
- [x] Accept: build immutable release, deploy business+algorithm+web and independent preview, real GPU upload smoke, browser E2E (mobile/desktop playback), busy-GPU and recovery checks. Back up configuration/database and mirror experiment data before publishing report and both remotes.

## Review focus

External jobs starting after admission; all cards busy; malformed/failed telemetry; two workers racing for the same card; fatal shard/lease loss. Each must fail closed or queue safely, never silently publish partial predictions. Existing device allowlist and single-card deployment remain supported.

## Decisions

The user delegated allocation and deployment decisions. The plan is executed in this session on the existing product feature branch; FTT changes are checkpointed on its maintained branch. Experimental harnesses are isolated from production until validated. No additional design approval gate is needed under the authorized implementation request.

## Acceptance evidence

- 27 successful FTT timing runs; separate controlled allocation and six-match real product regression. Report is maintained in FTT docs/20261114-004.
- Fresh review identified lease recovery under saturation, lost final OOM diagnostics and reservation/transaction connection contention. Each fixed with focused regression coverage; real PostgreSQL tests pass (4).
- Maintained check/test commands pass; browser E2E passes (8). GitLab pipeline 10556 for application release 014000c passed Python and web jobs, including Linux fullscreen validation.
- Real GPU smoke and full deployed mobile/desktop upload/playback + six static previews pass. Final source-only UI fix releases Linux fullscreen gutter; the algorithm source files match the tested backend; the final image tag receives its own GPU smoke.
- No compression; same-machine multi-GPU outputs match. Cross-machine strict F1 difference is documented rather than hidden.

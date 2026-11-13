# Working in RallyMark

Read README.md for setup, docs/architecture.md for service boundaries, and docs/operations.md before deployment work.

- apps/web owns browser interactions. services/api owns sessions, media and orchestration. services/algorithm owns inference and its durable jobs. Keep service database schemas and Python dependencies separate.
- Keep generated contract types derived from the API. Run scripts/contracts.py after public API changes and commit the generated result.
- Preserve task idempotency, per-task configuration snapshots and ownership checks. Algorithm execution never reads ground truth.
- Playback navigation is a state machine. User scrubbing turns automatic skipping off; programmatic seeks do not. Cover changed transitions with focused tests.
- Use make check and make test. GPU inference runs on the deployment machine through make smoke-gpu; CPU CI uses the fake runner.
- Runtime files, secrets, model weights, video data, caches and outputs stay outside Git. Use relative repository paths in documentation and configuration templates.
- Deployment uses immutable version tags. Retain previous versions and drain running work before changing services. Do not remove data volumes to troubleshoot.
- Select hosts through .runtime/target.env and GPU devices through the target's .runtime/deploy.env. Never restrict inference to a GPU model name or commit a machine's GPU UUID. Verify real CUDA inference after hardware changes.
- Add abstractions only for an actual repeated behavior. Keep comments for non-obvious constraints, and keep a single source of truth for documentation.

- Reuse web UI primitives in apps/web/src/ui. Icon controls keep accessible names and at least 44px touch targets. Scores and counters use stable dimensions and tabular numbers; inferred/unknown states use graphics and compact labels rather than changing-length prose.
- Local import and experiment preloading are development-only. Keep their lazy entry behind import.meta.env.DEV; pnpm build must verify no debug UI or data endpoint leaks into production assets.

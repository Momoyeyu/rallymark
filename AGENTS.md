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

- Follow docs/design/interface.md for the UI language. Visible selectors, file pickers, progress and tooltips use the shared custom components; preserve semantic keyboard controls underneath. Verify expanded controls and viewport edges, not only collapsed screenshots.
- Create reversible Git checkpoints for stable UI milestones and push both remotes. ui-baseline-20261113 records the pre-workspace version.

- `apps/web/src/site`, `/preview` and `/admin` share one production web image.
  The six-match preview reuses the player and has no upload/import/API dependency.
  Keep management entry points out of public navigation. See docs/administration.md.
- Admin authentication never substitutes for the anonymous demo owner cookie.
  Video.user_id remains nullable until product account integration is explicitly
  enabled. Preserve existing owner hashes and do not bulk-assign old videos.
- Passwords use salted hashes, sessions use hashed opaque tokens, and account
  changes revoke sessions. Keep the last active administrator and reversible
  video trash protections. Never return password/session hashes to the browser.
- Selects inside a native dialog must portal into that dialog, not the inert body.
- Configure video bind paths through the target environment. STORAGE_MOUNT must
  be mounted before deploy/config-apply; do not silently create data on the SSD.
- GPU maintenance uses `GPU_MODE=disabled`, not a fake runner. API database
  readiness and authenticated worker capacity are distinct. Public errors must
  be sanitized and correlated with backend logs; busy workers accept queues.
- GPU discovery, admission, UUID reservations and allocation policy belong only to
  the algorithm service. Business code consumes generic capacity/task state.
  Resource settings live in `deploy/gpu-pool.yaml`; zero caps mean runtime auto.
- Keep only the latest local preview and canonical original inputs. Preserve GT,
  metadata, metrics, screenshots and source provenance; prune superseded encoded
  videos and duplicate release copies after verification. This local policy does
  not authorize deleting remote deployment volumes or rollback images.

- Media compatibility and CPU normalization belong to the business service. Keep
  browser preflight aligned with the public upload policy; never trust filename
  extensions as codec/container validation. `preparing` must stay protected by
  drain/cleanup and excluded from algorithm submission until hashes are updated.
- Production uses original-input analysis; keep compatible MP4 bytes, frame rate
  and dimensions intact. See docs/media-ingestion.md for the required compatibility
  preparation and docs/operations.md for the validated original-input preset.

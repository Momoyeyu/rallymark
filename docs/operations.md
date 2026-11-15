# Operations

## Bootstrap

Requirements are Docker 28 or newer with daemon access and CDI support, Docker Compose 2.24.4 or newer, and an NVIDIA driver plus NVIDIA Container Toolkit with generated CDI devices on the GPU host. Python 3 runs the operator scripts. The source tree and .runtime/deploy.env must be available on the host.

~~~sh
make setup
make config-edit
# Edit .runtime/deploy.env: REGISTRY, WEIGHTS_PATH, GPU_DEVICE and WEB_PORT.
make doctor
make build VERSION=<commit-sha>
make config-check VERSION=<commit-sha>
make deploy VERSION=<commit-sha>
~~~

make setup generates unique credentials and leaves an existing file intact. Keep the environment file private. REGISTRY is currently the local image-name prefix rallymark. make deploy VERSION=<commit-sha> builds images on the deployment host before draining work; make rollback reuses the recorded previous images without rebuilding them. When a registry becomes available, configure REGISTRY and use LOCAL_BUILD=0 to pull published images. Use the API and algorithm database roles created by the PostgreSQL initialization script. Initialization runs once on a new database volume; changing a password in the environment file does not rotate an existing database role.

Weights are mounted read-only through WEIGHTS_PATH, which must contain the files recorded in services/algorithm/vendor/ftt/SHA256_MANIFEST.json. Relative mount paths resolve from deploy/. Set GPU_DEVICE to `all` (automatic) or a comma-separated allowlist of indices/UUIDs. Set GPU_CDI_DEVICE to `nvidia.com/gpu=all` or a CDI device name supplied by the target host. MIN_GPU_MEMORY_GIB sets the minimum memory threshold (default 12 GiB). Deployment checks total capacity so existing jobs can drain; make doctor and new worker startup also check free memory. Admission does not depend on the model name. The algorithm dispatcher adapts to the eligible pool and queue depth; busy cards are skipped, without preempting external work. Device numbers are not fixed in application code. A new GPU still requires a real sample smoke test. Only the frontend port is exposed. The first deployment is for the lab network/VPN and HTTP; set secure cookies and terminate HTTPS before using a public HTTPS endpoint.

## Choosing a deployment machine

Deployment host names and site settings stay outside Git. Clone the repository and check out the intended source commit on the target machine first. Run make setup there, then configure its .runtime/deploy.env for GPU_DEVICE, WEIGHTS_PATH and WEB_PORT. Select VERSION to match that source checkout; local builds execute on the selected host.

To operate that checkout from another machine, copy deploy/target.env.example to .runtime/target.env and set DEPLOY_HOST to an SSH alias and DEPLOY_DIR to the repository path relative to that SSH user's home. The SSH alias owns connection details such as user, address and port. Makefile deployment, configuration, status, logs, cleanup and backup commands then run through SSH using the target's own environment file. This forwards operations, not source files, credentials, images or data. Update the target checkout before deploying a new commit.

~~~sh
make deploy VERSION=<commit-sha>
make status
make logs SERVICE=algorithm-worker
# One operation on another configured SSH host:
make doctor DEPLOY_HOST=<ssh-alias> DEPLOY_DIR=projects/rallymark
# Explicitly operate on the current machine:
RALLYMARK_LOCAL=1 make status
~~~

Checks and tests stay local. Smoke commands use BASE_URL for the HTTP endpoint; SMOKE_VIDEO points to a local sample file. Changing the SSH target does not copy PostgreSQL, videos, outputs or model weights. For migration, keep the original deployment intact, transfer a consistent database/config backup plus media and algorithm-work volumes, copy the manifest's weights and verify their hashes, then restore on the new machine. Before initializing the new database, configure its database credentials to match the backup environment; adjust GPU and mount settings for the new host. If the backed-up application does not support the new hardware, first build a schema-compatible version there, then run make restore BACKUP=backups/<timestamp> RESTORE_VERSION=<compatible-version>. This explicit override starts the compatible version, preserves the backup's recorded version, and records both in .runtime/last-restore.json. Default restore still starts the backed-up version. Older versions that restricted GPU models cannot be used as a rollback baseline on a newly supported GPU.

## Local development

~~~sh
make setup
make dev
~~~

The development override selects the fake runner, uses a separate Compose project, and does not request a GPU. Development version records live under .runtime/dev/; production version records remain under .runtime/. For subsequent development operations, set RALLYMARK_MODE=dev; also set WEB_PORT=8181 when running beside production. It exercises upload, durable task processing and playback through the same API. make check and make test run the maintained validation commands. Production validation uses make smoke with BASE_URL pointing at a fake development deployment; make smoke-gpu additionally requires SMOKE_VIDEO pointing to the validated real sample.

## Update and recovery

make deploy VERSION=... builds versioned local images, validates Compose, rejects new analysis submissions and drains all existing queued and active work, runs versioned migrations and updates containers. If health checks fail, the previous recorded application version is restored. Schema migrations must remain backward-compatible because rollback does not run database downgrade operations. make rollback VERSION=... can explicitly select a previous version.

make config-check validates YAML before deployment. make config-apply drains active
work and recreates the API, algorithm services and web proxy. Recreating the proxy
refreshes its Docker DNS upstream after the API address changes. New jobs receive
the new configuration; existing jobs retain their snapshots. View service status
with make status and correlated logs with make logs SERVICE=api or
SERVICE=algorithm-worker.

A changed model snapshot requires a real GPU smoke run before promotion. CI verifies CPU behavior, but a GPU inference test is a deployment check. Model weights are not part of container image layers or Git history.

## Data cleanup and backups

make data-clean previews expired business media and algorithm scratch data. Add APPLY=1 to execute, or VIDEO_ID=<uuid> to target a specific terminal video. The business cleanup command preserves ownership and task consistency and skips active work. Cleanup never removes the database, model weights or whole volumes.

make backup stores a PostgreSQL archive, deployment configuration, environment file and current version under backups/. Backup directories contain credentials and are private. Media and model volumes are not duplicated by this operation; back them up independently if required. make restore BACKUP=backups/<timestamp> drains work, restores the database and configuration, then starts services again against the retained media volume. Restore checks backup completeness, database credentials and locally available images for the recorded version before stopping services. It restores PostgreSQL within one transaction, writes the backed-up YAML to the active CONFIG_FILE path, and starts the recorded application version. Restore expects the same database role names and matching credentials from the backup environment file. Test restore on a separate deployment before relying on it operationally.

## CI

GitLab is the primary source and CI system. Merge requests and master run Python/frontend checks, PostgreSQL integration tests, contract drift checks and focused browser tests. CI currently neither builds images nor deploys. Makefile scripts build and deploy locally on the GPU machine. Registry publication can be added later without changing service boundaries. The project Docker runner is scoped to RallyMark.

make sync pushes the current branch to origin (GitLab), then github (private auxiliary repository), failing if either push fails. It does not rewrite or delete remote history.

The project runner uses the system service rallymark-gitlab-runner.service under a dedicated account with Docker group access. It starts at boot and restarts on failure. Check it with systemctl status rallymark-gitlab-runner and journalctl -u rallymark-gitlab-runner on the configured runner host. The runner can live on a different host from the application. Registration credentials stay in the account's private GitLab Runner configuration, outside this repository. Do not start a second nohup runner for the same registration.

## GPU maintenance and static preview

Set `GPU_MODE=disabled` in the selected target's private `.runtime/deploy.env`
when hardware is unavailable. `make deploy VERSION=<commit>` then builds a
lightweight maintenance worker, with no GPU reservation or model mount. The
business API, algorithm API, database and web remain online. This is production
maintenance mode, not simulated inference. New uploads and retries check worker
capacity and return a public unavailable message with a request ID; existing
media stays accessible. Busy healthy workers accept queued jobs. After hardware
repair, set `GPU_MODE=enabled`, run `make doctor`, redeploy, then `make smoke-gpu`.
API readiness checks database connectivity; authenticated algorithm capacity
checks fresh, matching-version worker heartbeats separately.

The read-only demo lives in `apps/preview`, sharing the web toolchain and the
player, controls and styles in `apps/web`. It contains no importer or upload
flow. Build with `make preview-build`. Export the six verified video/metadata
pairs with `make preview-export EXPERIMENT=.runtime/experiments/<experiment>`.
The export includes only public metadata and videos, never GT or raw diagnostics.
Copy `.runtime/preview-data/` to the selected server at the same relative path.
Deploy with `make preview-deploy VERSION=<commit>`; use `make preview-status` or
`make preview-logs` to inspect it. `PREVIEW_PORT` defaults to 8081, separate from
`WEB_PORT` 8080; `PREVIEW_DATA_PATH` is relative to `deploy/` unless absolute.
Preview Compose uses its own project, image and read-only data mount. Exported
video names contain content hashes; metadata is published atomically. Keep old
video files until existing browser sessions have expired.

## Performance configuration

New algorithm snapshots include `parallel_inference`, `decoder_mode`,
`decode_workers`, `prefetch_depth`, and `ocr_execution_provider`. The validated
4090 D configuration uses parallel branches, four ordered CPU decode workers,
depth four and CUDA OCR. CPU fallback is recorded in the attempt's `ocr.log` and
result warning. TAD logs are separate in `tad.log`. Keep source/version and both
service configurations synchronized; existing jobs retain their saved settings.

Linux GPU dependencies deliberately install `onnxruntime-gpu` instead of the CPU
distribution, which shares the same import path. The uv override excludes the CPU
distribution on Linux. CUDA OCR subprocesses find CUDA 11/cuDNN 8 libraries from
the pinned PyTorch environment. Rebuild the worker image when updating this lock;
validate actual CUDA provider execution and a real sample, not only the GPU name.

## Original-input preset

The selected production path analyzes compatible original media without lowering
its frame rate, resolution or bitrate. The six-match FTT comparison is recorded
in [report 009, section 7](http://gitlab.local/sujunjie/ftt-demo/-/blob/master/docs/009-frame-rate-ablation.md#7-与未压缩最佳配置的多维比较).
The preset is Top-195, neighborhood nine seconds, protection Top-100, minimum
orphan duration 0.5 seconds, fragment gap one second, score-confidence 0.9,
edge evidence 60 seconds and `algorithm.ocr_lookback_seconds: 5.25`.
It preserved all previously covered GT seconds on the six development matches;
it is not a guarantee for new videos. Recall remains the primary evaluation goal.

The lookback changes only the start of an existing OCR proposal, clamped at zero.
The raw OCR observations and proposal file remain available, and the effective
lookback is saved in each job snapshot and `postprocessed.json`. Existing task
snapshots without the field retain their old behavior; the schema fallback is
4.5 seconds. All new deployment snapshots use the explicit YAML value.

Older images reject the new YAML key. On the first promotion, take `make backup`
before updating the target checkout. Deploy the new image with the backed-up
configuration first, so automatic image fallback can still read that configuration:

~~~sh
make deploy VERSION=<commit> CONFIG_FILE=../backups/<checkpoint>/config.yaml
make config-check VERSION=<commit>
make config-apply VERSION=<commit>
~~~

The last two commands use the new default YAML. They validate both services,
drain active tasks and recreate the configured services. To roll back to a version
that predates the field, pass its backed-up configuration explicitly:
`make rollback VERSION=<old-version> CONFIG_FILE=../backups/<checkpoint>/config.yaml`.
Keep the checkpoint and old images until the new release is accepted.

## Adaptive algorithm resources

`deploy/gpu-pool.yaml` is read only by the algorithm worker. Override its mount
with `GPU_POOL_FILE` in the target environment, or use
`make config-edit CONFIG_SCOPE=algorithm`, then `make config-check` and
`make config-apply`. Zero caps mean automatic GPU count / concurrency; optional
positive caps constrain a shared host. The business service has no GPU policy
configuration. Admission checks free memory (14 GiB by default), utilization
(<=20%) and existing compute process memory (<512 MiB). These margins are
configurable except the conservative small-context exemption. Scheduling is
cooperative: another user's process can still start after admission. OOM errors
are logged internally, trigger the existing bounded retry, and never publish a
partial shard result.

Run `nvidia-ctk cdi list` on the host before deploying; regenerate CDI descriptions
after changing drivers/devices. Production uses CDI rather than the legacy
`--gpus` hook to retain device access through container/cgroup updates. The FTT
multi-GPU report records a controlled before/after container-update reproduction.
Fake development and GPU-disabled maintenance modes do not request CDI devices.
The allowlist is runtime configuration, not a committed host UUID.

`make backup` includes the algorithm resource YAML. Restore keeps compatibility
with older backups that did not include this optional file. GPU reservation
decisions and their job IDs appear in algorithm JSON logs; per-attempt
`allocation.json` records the exact devices and resource policy. Public capacity
returns only ready/busy/unavailable and queue length.

GPU admission also checks device-wide `memory.used`, independently of the process
list: container PID namespaces can hide host process details from NVML. A card
with >=512 MiB allocated remains excluded even if no foreign PID is listed. The
worker container health check requires a fresh, compatible dispatcher heartbeat,
so deployment cannot pass merely because a crashing worker process was started.

Expired job leases are recovered on every dispatcher iteration, even with no
eligible GPU. GPU advisory-lock connections use a separate unpooled engine so
long-running reservations do not consume transactional connection-pool capacity.
For unusually large installations, provision PostgreSQL connection limits and
use the optional concurrency cap to fit the database and host RAM budget.

## Local experiment retention

Keep one canonical copy of each original video and its ground truth, the latest
preview manifest, analysis metadata, metrics, reports and quality screenshots.
After a rejected compression/playback experiment has been evaluated, remove its
generated video variants and unused local release builds. Original aliases that
are still referenced may be hardlinks to the canonical file after SHA-256 checks.
Retain unique source/configuration and database backups before retiring an older
machine archive; model assets are deduplicated by checksum, not dropped by date.
This policy applies locally. Remote media cleanup still goes through `make
data-clean`, and deployed rollback images/volumes remain governed by the release
procedure.

The default preview export reads the single current `.runtime/preview-source`
dataset. Its `review/` metadata is paired by SHA-256 with canonical `.runtime/inputs`
originals; `videos` is a relative alias. Use `EXPERIMENT=...` explicitly to export
a historical experiment, rather than silently replacing the latest preview.

## Media preparation

The business API accepts MP4/MOV H.264/HEVC and normalizes only when needed.
See [media ingestion](media-ingestion.md) for the bounded CPU path. Preparation
uses durable `preparing` analyses and is included in drain/cleanup protection;
review `media_preparation_started/completed/failed` and `media_rejected` events
with video/request IDs in API logs. `application.conversion_timeout_seconds`
(default 900) and `application.max_normalized_bytes` (default 1000000000) control
conversion bounds through the usual config commands. Rollback should follow the
normal drain procedure so old versions never receive pending preparation work.
The shipped YAML uses code defaults for the new optional preparation settings,
remaining readable by the preceding release. If adding custom preparation keys,
restore the older version's configuration before rolling back to that version.

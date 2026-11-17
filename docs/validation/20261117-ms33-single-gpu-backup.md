# ms33 single-GPU startup and complete project-data backup — 2026-11-17

The operator target now uses SSH alias `ms33`. Host inventory is four RTX 4080
SUPER devices and one RTX 4090. This deployment uses **only the RTX 4090**, one
GPU per task and one concurrent task. Device UUIDs live in the target's private
startup environment, not committed source/configuration defaults.

`make gpu-config GPU_DEVICE=<list> GPU_COUNT=<count>` persists a host-specific
selection, converting host indices to UUIDs before container device renumbering.
Compose overrides both CDI visibility and the algorithm worker allowlist from
the startup settings. The private algorithm pool YAML sets per-job/concurrent
limits. No business-service GPU scheduling was added. See
[deployment selection](../operations.md#selecting-gpus-at-deployment).

## Verification

- 27 operator/storage/preview/GPU-selection tests passed. Coverage includes UUID
  resolution, index renumbering, duplicate/missing cards, count limits, and matching
  container/worker pools. No other cards were used for an inference experiment.
- Actual worker `nvidia-smi` reports only the selected 4090. Settings report one
  GPU per job and one concurrent job; `make doctor` passed.
- Real GPU smoke passed: video `2cac0b0c-5ee5-406b-992d-6b1292d94fba`, analysis
  `5b16a2b8-3de9-42af-ac65-69052ff6db2d`, 15 rallies, no warnings. Its allocation
  contains exactly one device; TAD has one shard, 33 windows and 13,001 frames.
- The host rebooted unexpectedly during backup transfer. After reboot the same
  single-GPU restriction remained effective and all application services were
  healthy. Web returned 200. The completed backup uses a frozen pre-reboot copy,
  not a mixture of live files from before and after restart.

## Backup on mac-studio

Destination, relative to the backup account's home:
`Backups/rallymark/ms33/20261117-093039/`.

A consistent checkpoint was made with related writers and PostgreSQL stopped.
Frozen copies were then made on the data disk, and services resumed before network
transfer. The checkpoint covers related project/deployment data as of approximately
09:30 Asia/Shanghai, not unrelated users or a bootable host image. Post-checkpoint
uploads are outside this frozen backup.

The 13 verified archives total **38,435,503,715 bytes** (about 35.8 GiB):

- Complete source-user projects directory: RallyMark, FTT, Git histories, runtime
  videos, GT, experimental outputs, deployment environments and database dumps.
- Model directory and active data-disk videos, sources, thumbnails, algorithm
  scratch/results and six-match preview.
- Legacy media/algorithm volumes retained for rollback and an offline PostgreSQL
  17 physical volume, alongside the logical database checkpoint.
- Six exported Docker images and six frozen container log/metadata archives.

`manifest.json` has `complete: true`, per-archive sizes and SHA-256. Every completed
archive was re-read for checksum verification and its gzip/tar structure checked.
The projects archive contains 48,306 members. Docker image manifests reference
existing configuration/layer members for all six images. This is archive-level
validation; no full deployment restore rehearsal is claimed.

`RESTORE.md` is stored beside the archives. Linux files stay inside archives to
preserve case, permissions and symlinks on the macOS destination. Files and the
parent directory are private because configuration/container metadata contain
credentials. No private SSH key was copied for transport. Temporary authentication
used only the existing local identity; the temporary agent is retired afterward.

The source data, volumes and staging snapshot were retained. Local sanitized
receipts live under `.runtime/validation/20261117-ms33/`. Later source-only changes
are saved as a checked Git bundle supplement, separate from the frozen data point.

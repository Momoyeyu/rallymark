# Data-disk storage, product entry and administration — 2026-11-16

Application images: `84078c0`. Target selection remains in the operator's private
`.runtime/target.env`; no host or disk location is embedded in application code.

| Surface | Address |
|---|---|
| Homepage | http://10.106.131.204:8080/ |
| Upload/review | http://10.106.131.204:8080/app |
| Six-match preview | http://10.106.131.204:8080/preview |
| Management | http://10.106.131.204:8080/admin |

The homepage follows the second selected visual concept. Management is absent
from public navigation. The initial `admin` / `admin` account exists; public
uploads still use anonymous ownership. Preview now belongs to the same web image
and read-only asset mount. The former preview container is stopped and port 8081
is no longer listening. No GPU driver or RAID configuration was changed.

## Storage migration

The target has a six-member healthy RAID6 XFS filesystem (approximately 14.6 TiB).
Business media, algorithm work and static preview now use its configurable bind
paths. PostgreSQL, weights and application images remain on the system SSD.
The data filesystem is present in the host's boot mount configuration.

The migration drained tasks and stopped writers before copying. Every file's
size and SHA-256 matched before switching mounts:

| Dataset | Files | Bytes |
|---|---:|---:|
| Business media, originals and thumbnails | 71 | 4,540,644,021 |
| Algorithm inputs and diagnostics | 14,717 | 4,143,707,166 |
| Static preview | 7 | 1,421,618,442 |

Migration checkpoint: `backups/20261115-235904/` on the target, copied to local
`backups/kuanguang-204-20261115-235904/`. A second pre-release checkpoint is
`backups/20261116-005607/`, also copied locally with the same host-prefixed name.
Old named volumes, old preview files and previous images remain as rollback
checkpoints; they have not been deleted to claim system-disk space savings.
New runtime video writes use the data filesystem.

The complete migration manifest is retained locally under
`.runtime/validation/20261116-storage/storage-migration.json`.
See [storage operations](../operations.md#video-storage-on-a-data-disk) for the
mount guard, configurable paths, copy verification and recovery procedure.

## Verification

- `make check` and `make test` passed. Final targeted API run: 39 passed,
  3 environment-dependent PostgreSQL tests skipped locally. All three PostgreSQL
  tests then passed against a disposable PostgreSQL 17 instance, including the
  password-reset/login race. That test instance was removed after verification.
- Operator/preview/storage tests: 23 passed. Algorithm: 35 passed, 4 skipped.
  Experiment evaluation: 21 passed. Frontend unit tests: 23 passed.
- Browser suite: 15 passed. Coverage includes product/upload navigation, no admin
  entry, 320/390/768/1440px homepage boundaries, mobile manager login and user
  forms, errors inside dialogs, six preview selections, playback, and existing
  uploader/player regressions. Other maintained player cases cover 844/1920px.
- Local browser inspection verified the actual six-match homepage showcase on
  desktop/mobile, management login, capacity layout and the user dialog. Final
  attempts to inspect the deployed page through the in-app browser timed out;
  Chrome was unavailable. No fresh production visual screenshot is claimed.
  Production HTTP, authentication, media and real GPU checks below passed.
- Independent code review found and re-checked two corrected issues: reset/login
  credential serialization and reserved upload-key conflicts after trash. The
  former has a real PostgreSQL concurrency regression; the latter was observed
  failing with 500 before the fix and passing with a non-leaking 409 afterward.
  Review ended with no outstanding important findings.
- Production `/`, `/app`, `/preview`, `/admin` returned 200. Unauthenticated
  management returned 401; admin login/storage/logout worked. Cookie flags,
  session revocation and separate anonymous ownership were verified. Storage
  reported a 16,000,468,647,936-byte media filesystem, confirming the data mount.
- All six deployed preview videos returned 206 and correct total lengths; the
  manifest exactly matched the local verified export. A pre-migration business
  video also returned a valid 206 through authenticated management playback.
- Every production application container is healthy. Only port 8080 remains
  published for these product surfaces.

## Fresh GPU upload on the data disk

`make smoke-gpu` passed with no warnings and 15 rallies:

- Video: `54e447ae-2f18-4059-a741-c42abe6208ad`
- Analysis: `92323d9b-987d-47b8-8a8c-86687163eebe`
- Configuration: `1ed75219d314d2ad29b3919a1a2b6b0377bcc9cdb0b95571c7d335c9a9e81821`

The uploaded QuickTime-branded H.264 source was remuxed, not re-encoded, following
the existing media policy. Source SHA-256:
`7ca9a05e2f68284412519c18192154f8af5ce0e142a5c039417269ca04a5bf83`.
Prepared playback SHA-256:
`a15367aab872c32a54656b131bcefa289323e2b69851d60674854e370a99a902`.
Both files exist on the data-backed business mount; the prepared checksum matches
the stored record. The prior deployment's preservation audit established that
these exact files retain every ordered encoded video packet and all 13,001 frames.
No experimental frame-rate, resolution or bitrate compression was enabled.

Sanitized HTTP/GPU receipts and raw attempt metadata are saved locally under
`.runtime/validation/20261116-storage/`. Original data, backups and credentials
are excluded from Git. [Administration](../administration.md) remains the authority
for permissions, trash, retention and future user ownership integration.

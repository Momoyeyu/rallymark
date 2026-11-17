# Restart and external access acceptance

Validated on 2026-11-17 after the deployment host returned online.

- The target selected through `.runtime/target.env` was reachable over SSH.
  Its campus address changed after reboot; the old address was not reachable.
  Resolve the SSH target again before diagnosing application port failures.
- Web, business API, algorithm API, algorithm worker and PostgreSQL containers
  were healthy. The application entry remained bound to port 8080 on all host
  IPv4 interfaces. No application restart or image change was needed.
- Browser checks ran from the maintenance machine, outside the deployment host:
  `/`, `/app`, `/preview` and `/admin` returned HTTP 200. The six-match manifest
  loaded, and a preview video reached ready state 4 and played successfully.
  A Range request returned HTTP 206 with exactly 1,024 requested bytes.
- At a 390 × 844 viewport, upload and preview pages had no horizontal overflow.
  The upload page established its anonymous session, loaded its upload policy
  and reported real algorithm capacity without browser console errors.
- A fresh upload of the 260.06-second original sample completed real inference
  in 121.82 seconds of algorithm execution: 15 rallies and no warnings. The
  public upload/status/media chain and anonymous ownership isolation passed
  `scripts/smoke.py --gpu` from the maintenance machine.
- Worker visibility remained restricted to the configured single RTX 4090.
  The allocation log contained one selected GPU; the four other cards were not
  exposed to the worker. Video storage remained on the mounted data filesystem.

Smoke identifiers:

| Object | Identifier |
|---|---|
| Video | `4e2d1b4d-227f-43b3-b329-9d3a1a5746b5` |
| Analysis | `e188a2fc-7c72-479e-98c3-48c07b48e41d` |

These checks establish access from the campus network, not a public Internet
endpoint. Host addresses and GPU identities remain private deployment settings.

## Off-host working copies and publication

The off-host machine has normal RallyMark and FTT project checkouts, with model
assets, original inputs, metadata and runtime media restored to project-relative
locations. Both trees were checked for broken symlinks; none remained. The web
project installed with its frozen pnpm lockfile and built successfully there.
Machine-specific deployment paths were adjusted locally and GPU execution was
disabled on that CPU-only copy.

The ModelScope publication is a separate sanitized snapshot preserving the
monorepo layout and required large assets. Its inventory contains 17,032 files,
20,132,133,691 bytes, with SHA-256 hashes. Credentials, private database contents,
authentication state and rebuildable dependency caches are excluded. Upload runs
as a retrying background job; publication is complete only after remote inventory
verification and the creation of `.runtime/modelscope-upload-receipt.json`.

# Data-disk storage and product entry

Goal: move video-heavy data off the system disk, provide an authenticated management
surface, and unify product/upload/preview routes without requiring public login.

Design: one existing React app and business API; `/`, `/app`, `/preview`, `/admin`.
The selected homepage is the second displayed design. Reuse the existing player,
Phosphor controls, DM Sans and court/green tokens. No public admin link.

Data: keep anonymous owner hashes unchanged. Add nullable video.user_id referencing
users, independent revocable admin sessions, salted password hashes, roles and active
state. Bootstrap admin/admin only when no users exist. Never log passwords/tokens.
Video trash is reversible; active analyses cannot be trashed. Retention cleanup
continues through the existing business operation, not arbitrary file removal.

Storage: configurable MEDIA_STORAGE and ALGORITHM_STORAGE select a named volume
(default) or target-specific bind path. PREVIEW_DATA_PATH mounts read-only on web.
Drain, back up database/config, stop writers, copy all files and verify SHA-256 before
changing mounts. Keep old volumes for rollback. Database/weights stay on SSD.

- [ ] Storage: add configurable mounts and doctor checks; regression tests; migrate
      target media/work/preview to the data filesystem with verified manifests.
- [ ] Identity and management: migration, admin auth/user/video/storage endpoints;
      test anonymous isolation, privilege/CSRF/session expiry, last-admin guard,
      trash/restore/active protection and migration idempotency.
- [ ] UI: selected homepage, route split, integrated preview, reusable form controls,
      manager login/storage/videos/users/recycle views, mobile layout.
- [ ] Verification: make check/test, browser flows and mobile viewport review;
      production deploy, old-media playback, real GPU upload, manager auth checks.
- [ ] Document routes/permissions/migration/recovery, commit stable milestones and
      push GitLab and GitHub. Retire port 8081 after same-origin preview verification.

Acceptance focus: existing anonymous cookies keep history; admin cookie never grants
public ownership; no credentials or host storage paths in public errors; no fallback
to an unmounted data directory; password resets revoke sessions; preview never gains
upload/import controls. Deployment actions already authorized by the user.

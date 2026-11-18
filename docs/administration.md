# Storage administration

Open `/admin` directly on the same origin as the product. There is no public menu
entry and no separate management service or port. The initial account is
`admin` / `admin`. Bootstrap runs once during migration and never resets an
existing password. Change credentials through the user editor when appropriate.

## Boundaries

- The public `/app` supports both guests and product accounts. Management login
  uses a separate cookie and session scope and leaves product history unchanged.
- Users have a stable UUID, normalized unique username, salted scrypt password
  hash, `admin`/`member` role and enabled state. Product login automatically
  attaches the current guest's accessible videos to that account. The existing
  `videos.user_id` foreign key supplies the owner label.
- Member accounts can authenticate but cannot use management APIs. Only active
  administrators can inspect all videos/storage/users or change them.
- Sessions are opaque random tokens, hashed in PostgreSQL, expire after 12 hours,
  and are revoked on account/password/role changes or logout. Cookies are HttpOnly,
  SameSite Strict and scoped to management API routes. HTTPS deployments enable
  secure cookies using the existing application configuration.
- Failed logins are limited persistently; the proxy additionally rate-limits the
  login endpoint. Cross-origin writes are rejected. API responses are not cached.
  Credentials, raw tokens and password hashes never appear in API output or logs.

## Operations

Storage shows the media filesystem capacity, video count, playback-file bytes,
trash count and configured retention. It does not claim that playback-file bytes
include sources, thumbnail files, algorithm inputs or previews.

Video search is paginated. Each row displays its account username or a stable,
non-credential guest reference derived from the anonymous owner. The guest reference
identifies a browser session, not a person; clearing cookies creates a new owner.
Page selection includes only terminal/actionable rows on that page. Changing pages
or search clears selection. Bulk trash/restore is atomic: missing, active or expired
(for restore) rows reject the whole request without partial updates. After counts
shrink, the server and client return to the last valid page (page one if empty).
 Administrators can view prepared video and its rally
markers. Moving a terminal video to trash hides it from the original uploader,
without immediately deleting files; restore works before its existing expiry.
Active/queued/preparing work cannot be trashed. Retention continues from the
original upload; trash does not extend it. Expired data is automatically cleaned
hourly. Manual cleanup explicitly confirms permanent removal of expired terminal
business videos/results; algorithm scratch follows its own retention process.

Users can be created, enabled/disabled, assigned a role and have their passwords
reset. At least one enabled administrator must remain. Editing the current user
revokes their session and returns to login. Successful management mutations are
recorded in `audit_events` and structured logs with actor, target and request ID.
Public errors remain short; use the problem ID to locate backend details.

For migration, deployment, cleanup and rollback use the shared
[operator entry points](operations.md). Filesystem paths and database credentials
remain deployment concerns and are not returned by management endpoints.

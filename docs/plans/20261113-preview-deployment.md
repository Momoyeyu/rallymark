# Static preview and degraded deployment

Implement the user-requested deployment in the existing monorepo. `apps/preview` owns the read-only static entry and build; it imports the same player, controls and theme as `apps/web`. Export only six videos and public result metadata, with checksums and no GT or diagnostic output. No upload, importer or backend dependency ships in the preview.

Business admission checks an authenticated algorithm capacity endpoint. Healthy busy workers accept queued work; missing workers reject new analysis with a sanitized message and request ID. Upload preflight avoids unnecessary transfers; server admission rechecks the race. Existing media remains readable. Dispatcher outages have a bounded deadline and public errors never relay internal messages.

Production GPU-disabled deployment runs a lightweight unavailable worker, real algorithm API and business API, without GPU reservations or fake inference. Deployment mode and ports live in target configuration. Preserve volumes and back up before replacement. GPU repair remains owned by the referenced task.

- [x] Test capacity, unavailable admission, queueing and error sanitization; implement service boundary.
- [x] Implement static preview export/build and reuse responsive UI; verify six matches and no API/upload.
- [x] Add configured degraded Compose mode and Make operations; verify checks and commit to both remotes.
- [x] Back up, deploy both sites, verify HTTP/Range, mobile playback and unavailable UX; record URLs and deployment evidence.

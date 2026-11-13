# Architecture

The React client uses one origin for static assets, the public API and owned video playback. Nginx forwards /api requests to the business service. PostgreSQL persists business and algorithm state in separate schemas with separate credentials. The algorithm service is accessible only on the container network.

The business API stores original videos in its media volume. After ffprobe validation, it records an analysis with immutable algorithm configuration and a content checksum. Its coordinator submits the same analysis ID to the algorithm API until acknowledged and polls durable progress. Repeated requests remain idempotent.

The algorithm API records jobs. A separate worker claims one job at a time with a renewable lease, downloads the source through the authenticated internal media endpoint, and validates its checksum. Real execution uses the pinned FTT source snapshot, TAD, optional supported-layout OCR and postprocessing. An attempt directory is published only after validation. Worker restarts recover expired leases. Source videos are accessed through HTTP, so services can be deployed on different hosts.

The browser session is an anonymous HttpOnly cookie. Video history, metadata and playback enforce session ownership. Clearing browser cookies loses access to that browser's previous history. Media and analysis outputs expire after seven days; active tasks are excluded from cleanup until terminal.

The mobile player defaults to automatic rally skipping. Manual scrubbing turns the toggle off, while previous/next buttons and automatic seeking preserve it. The last rally pauses at its end. Browsers require the first audible playback to follow a user gesture.

The validated development configuration uses 200 TAD candidates, a nine-second orphan neighborhood and protected Top-100 candidates. Score-constrained fusion merges nearby fragments and suppresses candidates only where supported by scoring evidence; see [the six-match report](20261113-003/report.md). Configuration is snapshotted per task. The model source version, weight hashes and effective configuration hash accompany tasks. Unsupported OCR layouts fall back to TAD with a warning. The experiment repository remains separate from this product.

Structured logs correlate request, video and analysis IDs. Stage progress comes from actual processing events. /health/live describes process liveness and /health/ready describes required dependencies. The readiness and worker metrics are internal operating signals; video content and credentials are never logged.

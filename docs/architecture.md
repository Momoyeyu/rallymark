# Architecture

The React client uses one origin for static assets, the public API and owned video playback. Nginx forwards /api requests to the business service. PostgreSQL persists business and algorithm state in separate schemas with separate credentials. The algorithm service is accessible only on the container network.

The business API stores original videos in its media volume. After ffprobe validation, it records an analysis with immutable algorithm configuration and a content checksum. Its coordinator submits the same analysis ID to the algorithm API until acknowledged and polls durable progress. Repeated requests remain idempotent.

The algorithm API records jobs. A separate worker claims one job at a time with a renewable lease, downloads the source through the authenticated internal media endpoint, and validates its checksum. Real execution uses the pinned FTT source snapshot, TAD, optional supported-layout OCR and postprocessing. An attempt directory is published only after validation. Worker restarts recover expired leases. Source videos are accessed through HTTP, so services can be deployed on different hosts.

The browser session is an anonymous HttpOnly cookie. Video history, metadata and playback enforce session ownership. Clearing browser cookies loses access to that browser's previous history. Media and analysis outputs expire after seven days; active tasks are excluded from cleanup until terminal.

The mobile player defaults to automatic rally skipping. Manual scrubbing turns the toggle off, while previous/next buttons and automatic seeking preserve it. The last rally pauses at its end. Browsers require the first audible playback to follow a user gesture.

The validated development configuration uses 200 TAD candidates, a nine-second orphan neighborhood and protected Top-100 candidates. Score-constrained fusion merges nearby fragments and suppresses candidates only where supported by scoring evidence; see [the six-match report](20261113-003/report.md). Configuration is snapshotted per task. The model source version, weight hashes and effective configuration hash accompany tasks. Unsupported OCR layouts fall back to TAD with a warning. The experiment repository remains separate from this product.

Structured logs correlate request, video and analysis IDs. Stage progress comes from actual processing events. /health/live describes process liveness and /health/ready describes required dependencies. The readiness and worker metrics are internal operating signals; video content and credentials are never logged.

TAD and OCR run as independent subprocess branches on one leased job. Each branch
has its own log and checks the shared deadline and cancellation signal; a fatal
TAD error cancels the peer before the attempt returns. OCR accelerator failures
retry on CPU. Older task snapshots retain their original sequential/CPU defaults.
New snapshots explicitly select four ordered decode workers and a depth of four;
only CPU decoding is parallelized within TAD, preserving global model windows and
NMS. The FTT performance report is the authority for ablations and limitations.

The shared player prewarms only the next rally through one muted metadata-preload
media element once the current player has at least two seconds buffered. It
cancels on seeking, buffering, pause, visibility loss, source changes and a
six-second deadline. Data-saving, 2G, sub-2 Mbps or <=2 GiB reported device memory
disable speculative loading. It never downloads a whole video into a JS Blob.
Native media cache memory remains browser-managed. Media responses use a private
30-second freshness window capped by expiry, vary on the session Cookie and
validate ownership/expiry before conditional 304 responses. The measured FTT
performance report records buffering and alternative approaches that were rejected.

# Architecture

The React client uses one origin for static assets, the public API and owned video playback. Nginx forwards /api requests to the business service. PostgreSQL persists business and algorithm state in separate schemas with separate credentials. The algorithm service is accessible only on the container network.

The business API validates real uploaded media, independently of filename hints. Compatible MP4 is retained; MOV/HEVC that requires normalization enters durable CPU preparation before analysis. Source files and prepared playback media share retention and ownership. See [media ingestion](media-ingestion.md) for preflight, conversion and recovery. It records an analysis with immutable algorithm configuration and a content checksum. Its coordinator submits the same analysis ID to the algorithm API until acknowledged and polls durable progress. Repeated requests remain idempotent.

The algorithm API records jobs. An algorithm dispatcher claims jobs only after reserving available GPU capacity, each with a renewable lease, downloads the source through the authenticated internal media endpoint, and validates its checksum. Real execution uses the pinned FTT source snapshot, TAD, optional supported-layout OCR and postprocessing. An attempt directory is published only after validation. Worker restarts recover expired leases. Source videos are accessed through HTTP, so services can be deployed on different hosts.

The browser session is an anonymous HttpOnly cookie. Video history, metadata and playback enforce session ownership. Clearing browser cookies loses access to that browser's previous history. Media and analysis outputs expire after seven days; active tasks are excluded from cleanup until terminal.

The mobile player defaults to automatic rally skipping. Manual scrubbing turns the toggle off, while previous/next buttons and automatic seeking preserve it. The last rally pauses at its end. Browsers require the first audible playback to follow a user gesture.

The validated development configuration uses 200 TAD candidates, a nine-second orphan neighborhood and protected Top-100 candidates. Score-constrained fusion merges nearby fragments and suppresses candidates only where supported by scoring evidence; see [the six-match report](20261113-003/report.md). Configuration is snapshotted per task. The model source version, weight hashes and effective configuration hash accompany tasks. Unsupported OCR layouts fall back to TAD with a warning. The experiment repository remains separate from this product.

Structured logs correlate request, video and analysis IDs. Stage progress comes from actual processing events. /health/live describes process liveness and /health/ready describes required dependencies. The readiness and worker metrics are internal operating signals; video content and credentials are never logged.

TAD and OCR run as independent subprocess branches within each leased job. Each branch
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

GPU management belongs exclusively to the algorithm service. Its dispatcher polls
visible, allowed devices and reserves stable GPU UUIDs with PostgreSQL session
locks before claiming a queued job. It admits only devices with sufficient free
memory, low utilization and less than 512 MiB of existing compute-process memory.
The last threshold permits small display/encoder contexts while avoiding another
training/inference process. Admission is a point-in-time check, not preemption or
an exclusive claim against unrelated host users.

With `max_gpus_per_job: 0`, a lone queued job uses all currently eligible cards;
with a backlog it receives `floor(free_cards / queued_jobs)`, at least one card.
`max_concurrent_jobs: 0` follows the discovered device count. Explicit caps are
optional and belong in the algorithm-only `deploy/gpu-pool.yaml`. Neither device
count nor scheduling policy is part of the business API or browser contract.
The current machine's four devices are an experiment condition, not a runtime
constant. Device loss or malformed telemetry prevents new claims. Saturation
keeps jobs queued without consuming attempts. Each running attempt keeps its own
renewable job lease and UUID reservation; an OOM consumes a bounded retry.

TAD shards receive contiguous subsets of the *original global* windows, preserving
overlap context and original timestamps. Raw predictions are collected in global
order, then NMS is applied exactly once. No video is cut or re-encoded. OCR shares
the first reserved device and runs concurrently. Allocation/policy are recorded
in the attempt's `allocation.json`, separate from immutable inference snapshots.

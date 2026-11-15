# Media ingestion

Production retains compatible original inputs. It does not apply the experimental
30 fps, resolution-reduction or bitrate-compression presets. Compatibility
preparation below is retained for formats that need it; it is not an upload-size
or inference-speed optimization.

The browser reads local container metadata before sending a video body. It fetches
`GET /api/v1/upload-policy` for the active limits, then checks byte size, MP4/MOV
content, H.264/HEVC codec, one video track, supported audio, duration and resolution.
Mediabunny reads bounded-cache local file slices without decoding HEVC or loading
the complete video into a JS Blob. Filenames, case and MIME hints are not evidence
of the actual container. A ten-second metadata deadline fails before upload.

The server independently probes the complete upload. Preflight cannot certify
that every compressed frame is intact; malicious clients can bypass it. Current
scope is MP4/MOV (including M4V), H.264 or HEVC, one video track and at most one
AAC or supported PCM audio track; maximum 4K, 500 MB and 15 minutes by default.
ProRes, WebM, MKV, unusual audio and multiview are not advertised as supported.

Compatible H.264 MP4 bytes are retained exactly. H.264 MOV is remuxed with copied
video and AAC audio, without changing decoded pixels. PCM is converted to AAC.
HEVC, rotated images or incompatible pixel formats are normalized to H.264
8-bit 4:2:0 MP4, with faststart and original timing. Presentation timestamps are checked against the current frame-index TAD clock.
Drift above 100 ms requires CFR preparation even for H.264; isolated sub-100ms
mux timing gaps do not force compatible H.264 into re-encoding. Encoding uses CPU libx264
veryfast/CRF18, two decoder/encoder/filter threads; it does not resize to reduce
upload cost or use algorithm GPUs. Rotation is baked into pixels; odd dimensions
are padded rather than cropped. PQ/HLG is tone-mapped to BT.709 SDR for this common
playback/analysis copy; original source bytes are retained for the retention period.

## Durable preparation

Uploads requiring conversion return an owned video and a `preparing` analysis.
The UI shows preparation and resumes polling after refresh. The business service
runs a separate CPU preparation loop; the algorithm dispatcher excludes this
state. Algorithm deadlines start at media readiness, preserving the upload creation
time separately. A PostgreSQL advisory lock bounds preparation to one job across API replicas;
leases renew every ten seconds and expired claims can be recovered. CPU concurrency
has no relationship to the algorithm GPU pool.

Outputs are private temporary files. Duration, codec and dimensions are reprobed,
then content hash and metadata are updated as the video moves to `queued`. Only
then can the algorithm obtain the normalized bytes. A crash during publication
leaves a retryable preparation rather than an accepted partial algorithm result.
On shutdown the encoder is killed and awaited; recovery waits for the lease.
Failures use a public message and request ID; FFmpeg diagnostics stay in API logs.
A retry of a failed preparation reuses its source without uploading again.

Original `.source`, normalized `.mp4` and temporary `.prepare.mp4` files belong to
the same video. Cleanup skips preparation/analysis in progress and removes all
associated files after terminal expiry. Default conversion deadline is 900 seconds;
normalized output is capped at 1 GB, matching the internal algorithm download
ceiling. The output cap can be configured downward. Both limits are business settings under
`application` in the deployment YAML. Encoding speed varies with duration, frame
rate, resolution, HDR and host load; no fixed ETA is shown.

Measurements and the remux/transcode tradeoff live in the FTT
[mobile-media experiment](http://gitlab.local/sujunjie/ftt-demo/-/blob/master/docs/008-mobile-video-compatibility.md).

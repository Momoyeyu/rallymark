# Local review without backend services

Run only the web application on the Mac (Node.js and pnpm required):

```sh
cd apps/web
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/?local=1`. No API, PostgreSQL or GPU process is required. Once dependencies are installed, the application and selected local files work without internet access. The optional web font falls back to system fonts when unavailable.

Select one or more original videos, then select each video's analysis JSON from the current-video menu. After a JSON is accepted, file settings collapse so the player and transport controls fit on a phone screen. The compact current-video selector stays visible; select an unconfigured video to reopen the form, or use the file-settings button to add/remove originals and replace JSON. Six or more videos can be loaded independently. Files stay in the browser: media uses object URLs, metadata uses File.text(), and local playback sends no API requests or tracking events. Select matching original videos; no new inference runs on the Mac. Browser-supported media such as MP4/H.264 is recommended.

Previous/next, rally selection, scores, automatic gap skipping, and manual seeking use the same player and state machine as server mode. Manual seeking disables automatic skipping. Local rally cards show scores and durations without server thumbnail requests. Loaded files and metadata are held in memory; refreshing requires selecting them again. Removing a video or leaving the page releases its object URL.

A compact metadata file is:

```json
{
  "title": "Match 1",
  "duration_s": 120,
  "warnings": [],
  "rallies": [
    { "start_s": 5.2, "end_s": 9.8, "score": "0:0", "score_status": "observed" },
    { "start_s": 15, "end_s": 18.3, "score": "1:0", "score_status": "inferred" }
  ]
}
```

Only `rallies`, `start_s`, and `end_s` are required. Times are seconds in the original video and must be finite, nonnegative, ascending, nonoverlapping, and satisfy `start_s < end_s`. Empty rally lists allow manual playback. `duration_s` is optional; playback reads the actual original duration, and intervals beyond that duration produce an error. A supplied duration must be positive and cover all rallies.

Optional `source_size_bytes` must be a positive integer and match the selected original's file size. When `duration_s` is supplied, its difference from the browser-reported original duration must be at most 0.25 seconds (to allow container rounding). A mismatch blocks playback. These lightweight checks do not read or hash the whole video. Optional `source_sha256` is retained in the exported JSON for provenance; the browser does not hash large videos or verify this field. Original filenames may be changed. Existing metadata without either field remains supported.

Each rally may provide a unique string `id`, a string or null `score`, and `score_status` (`observed`, `inferred`, or `unknown`, defaulting to `unknown`). Missing scores are displayed as rally numbers; uncertain scores are not invented. `title` and `warnings` are optional. Existing API VideoResponse exports with `latest_analysis.rallies`, and AnalysisResponse exports with top-level `rallies`, are also accepted.

The normal server-backed application remains at `/` without `?local=1`.

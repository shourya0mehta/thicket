# Thicket backend

FastAPI service that turns field audio into transparent species detections,
detection-derived metrics, acoustic indices and exportable evidence.

* Python 3.11+, FastAPI, Pydantic v2, NumPy/SciPy, SQLAlchemy 2.0 (SQLite by default)
* BirdNET v2.4 (TFLite, CC BY-NC-SA 4.0) through a typed adapter interface
* FFmpeg for decoding (WAV, MP3, M4A/AAC, FLAC, OGG)

The API contract lives in [`thicket/api/schemas.py`](thicket/api/schemas.py) (one
analysis) and [`thicket/api/platform_schemas.py`](thicket/api/platform_schemas.py)
(organizations, sites, recorders, batches, dashboards, alerts, reports), both
exported to [`shared/api.schema.json`](../shared/api.schema.json), which the
frontend turns into TypeScript types. The platform routes are specified in
[`docs/PLATFORM_API.md`](../docs/PLATFORM_API.md).

## Quick start

```bash
# from the repo root
make setup            # backend/.venv with backend[birdnet,ml,dev], plus frontend deps
make dev-backend      # API on http://127.0.0.1:8000 with auto-reload
make dev-frontend     # Vite on http://localhost:5173, proxies /api to :8000
```

Without make:

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[birdnet,ml,dev]"      # FFmpeg must be on PATH (apt install ffmpeg / brew install ffmpeg)
uvicorn thicket.main:app --reload --port 8000
# or: thicket-api   (one worker, 127.0.0.1:8000; set HOST=0.0.0.0 to listen on all interfaces)
```

Ports are defined once in `thicket/config.py`: the API uses **8000**, the Vite dev
server **5173**. Interactive docs: http://127.0.0.1:8000/api/docs.

The first BirdNET load writes a dual-output copy of the model (logits plus
1024-d embeddings) to `~/.cache/thicket` (`THICKET_CACHE_DIR`). Loading happens
in a background thread at startup; `GET /api/v1/health` reports `degraded`
until it is ready, and analyses submitted meanwhile wait for it.

### Command line (no server)

```bash
python -m thicket.cli analyze recording.wav --threshold 0.6 \
  --lat 42.44 --lon -76.50 --date 2026-05-14T06:30:00 --timezone America/New_York \
  --models birdnet --json out.json --csv out.csv
```

The CLI runs the same service and pipeline as the API, with a throwaway
in-memory database unless `--data-dir` is given. Exit code 2 means a typed
error (printed as `error [code]: message`).

Three more commands work on the configured data dir (`THICKET_DATA_DIR` or
`--data-dir`):

```bash
# Batch-ingest an SD card or folder (recursive; zips and sidecars included)
python -m thicket.cli ingest /media/SD_CARD --site "North pasture" \
  --recorder "AudioMoth 1" --make audiomoth --timezone America/New_York \
  [--org org_...]

# Run the nightly jobs once (rollups, gap checks, digests, cleanup)
python -m thicket.cli nightly

# After switching sign-in on: hand the local workspace to an organization
python -m thicket.cli adopt-local --org org_...
python -m thicket.cli adopt-local --email owner@farm.example
```

`ingest` writes to the local workspace unless `--org` names an organization.
It creates the site (and recorder) when they do not exist, runs every file
through the same ingest service as `POST /orgs/{org}/uploads`, and prints one
row per file (status, timestamp, timestamp source, species, events). File
modification times stand in for the browser's `last_modified`.

`adopt-local` is for a server that ran without sign-in and now has it: data
uploaded before lives in the implicit "Local workspace", which no signed-in
user can open. It moves every local resource (sites, recorders, deployments,
recordings with their analyses, detections and reviews, batch jobs, alerts,
reports and uploaded images) into the target organization in one transaction
and rebuilds that organization's rollups on its time zone. `--email` picks the
oldest organization the user owns, so sign in once and create the
organization first. An open alert that the target already has open under the
same key is resolved into it; the local workspace's notifications are dropped.
Running it again moves nothing.

## Configuration

All settings come from environment variables (or a `.env` file in the working
directory). [`.env.example`](.env.example) documents every one with its default.

| Variable | Default | Meaning |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `test` or `production` |
| `APP_VERSION` | package version | Reported in health and provenance |
| `THICKET_DATA_DIR` | `backend/var` | Database, temp, previews, spectrograms, retained audio |
| `DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL (Postgres-compatible schema) |
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Exact CORS origins; wildcards rejected |
| `MAX_UPLOAD_BYTES` | 52428800 (50 MB) | Enforced while streaming |
| `MAX_AUDIO_DURATION_SECONDS` | 600 | Longer files are rejected before any model runs |
| `MIN_AUDIO_DURATION_SECONDS` | 1.0 | Shorter files are rejected |
| `DEFAULT_DECISION_THRESHOLD` | 0.60 | Used when a request omits `threshold` |
| `RAW_THRESHOLD` | 0.10 | Ingestion floor: lower scores are never stored |
| `MERGE_GAP_SECONDS` | 1.0 | Consolidation gap between windows of one species |
| `HOP_SECONDS` | 3.0 | 3.0 (no overlap) or 1.5 (50% overlap) |
| `BIRDNET_ENABLED` | true | Turn BirdNET off (health becomes `degraded`) |
| `BIRDNET_MODEL_DIR` | bundled weights | Folder with the v2.4 TFLite model and labels |
| `LOCATION_FILTER` | true | Range and season plausibility for birds |
| `LOCATION_FILTER_THRESHOLD` | 0.03 | Meta-model occurrence below this marks a bird `unlikely` |
| `FROG_INSECT_ENABLED` | false | Experimental frog and insect head |
| `FROG_INSECT_MODEL_PATH` | none | `.npz` head file (model card next to it as `.json`) |
| `RETAIN_AUDIO` | false | Keep normalized audio after analysis |
| `TEMP_RETENTION_HOURS` | 1 | Janitor deletes orphaned temp folders older than this |
| `PREVIEW_TTL_MINUTES` | 60 | Previews (and their uploaded file) expire after this |
| `ANALYSIS_TIMEOUT_SECONDS` | 300 | Per-analysis deadline |
| `REQUEST_TIMEOUT_SECONDS` | 300 | Per-request deadline (plus the analysis timeout for `?wait=true`) |
| `WORKER_CONCURRENCY` | 1 | Analyses processed in parallel per process |
| `RATE_LIMIT_PER_MINUTE` | 30 | POSTs per client IP; 0 disables |
| `CLIENT_IP_HEADER` | unset | Proxy header with the client IP for rate limits (`Fly-Client-IP` on Fly; last entry if a list) |
| `SERVE_FRONTEND_DIR` | none | Serve a built frontend at `/` with SPA fallback |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | Structured JSON logs to stdout |
| `JANITOR_INTERVAL_SECONDS` | 600 | Cleanup cadence |
| `THICKET_CACHE_DIR` | `~/.cache/thicket` | Cached dual-output BirdNET model |
| `AUTH_MODE` | `disabled` | `disabled` (local owner, no login), `dev` (email form, refused in production) or `google` |
| `ALLOW_UNAUTHENTICATED` | false | Lets `ENVIRONMENT=production` run with `AUTH_MODE=disabled` (private instance behind an authenticating proxy); logs a warning |
| `SESSION_SECRET` | generated | Signs session cookies; generated once into `<data>/session_secret` when unset |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | none | Required for `AUTH_MODE=google` |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public API origin; callback URL and Secure cookies derive from it |
| `FRONTEND_URL` | `http://localhost:5173` | Web app origin for sign-in redirects, invite and alert links |
| `ALLOWED_SIGNIN_DOMAINS` | empty | Comma list of email domains allowed to sign in |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | none / 587 | Email over SMTP with STARTTLS |
| `EMAIL_FROM` | `Thicket <no-reply@thicket.local>` | Sender address |
| `RESEND_API_KEY` | none | Email through Resend when no SMTP host is set |
| `ALERTS_ENABLED` | true | Turn the alert engine off server-wide |
| `NIGHTLY_JOBS_HOUR_UTC` | 6 | Hour for the nightly jobs |
| `MAX_BATCH_FILES` / `MAX_BATCH_BYTES` | 200 / 2 GiB | Per batch upload, zip contents included |
| `REPORT_LOGO_PATH` | none | png or jpg on report covers |

## API

All endpoints are under `/api/v1`. Every error is an `ErrorResponse`
(`{"error_code", "message", "detail"}`) with a typed `error_code`.

| Method | Path | Result |
|---|---|---|
| GET | `/health` | `HealthResponse`; always 200, `status` is `degraded` until BirdNET is ready |
| GET | `/models` | `ModelsResponse` with status, taxa, license, model card, unavailable reason |
| POST | `/previews` | 201 `Preview`: file facts, signal QC and spectrogram, no model |
| GET | `/previews/{id}` | `Preview` until it expires |
| GET | `/previews/{id}/spectrogram.png` | PNG |
| DELETE | `/previews/{id}` | 204; deletes the preview's audio, spectrogram and facts now |
| POST | `/analyses` | 202 queued `Analysis` (poll it), or 201 completed with `?wait=true` |
| GET | `/analyses` | `AnalysisList`, most recent 20 (`?limit=` up to 100) |
| GET | `/analyses/{id}?threshold=` | Full `Analysis` recomputed at `threshold` (default: its own) |
| DELETE | `/analyses/{id}` | 204; removes rows, reviews, spectrogram, retained audio and a site no other recording uses |
| GET | `/analyses/{id}/spectrogram.png` | PNG, 0 to 16 kHz, low frequencies at the bottom |
| GET | `/analyses/{id}/audio` | 48 kHz mono WAV, only when `RETAIN_AUDIO=true` |
| GET | `/analyses/{id}/export.csv?threshold=` | One row per event at the threshold; `counted_in_metrics` marks the counted set |
| GET | `/analyses/{id}/export.json?threshold=` | `AnalysisExport`: the Analysis plus `export_metadata` |
| PATCH | `/events/{event_id}?threshold=` | Review an event; returns the recomputed `Analysis` |

`POST /analyses` takes `multipart/form-data`:

| Field | Notes |
|---|---|
| `file` | `.wav .mp3 .m4a .flac .ogg`; extension and magic bytes must agree |
| `preview_id` | Instead of `file`: reuse a preview's upload |
| `models` | JSON array or comma list, default `["birdnet"]`; unknown keys are rejected |
| `threshold` | Decision threshold in [`RAW_THRESHOLD`, 1], default 0.60 |
| `latitude`, `longitude` | Both or neither; [-90, 90] and [-180, 180] |
| `captured_at` | ISO 8601 date or date-time; naive values are read in `timezone` |
| `timezone` | IANA name, e.g. `America/New_York` |
| `site_name`, `recorder_type`, `notes` | Free text (200, 200 and 2000 characters) |

| `organization_id`, `site_id`, `deployment_id`, `recorder_id` | Platform links (optional). With sign-in, the caller needs the manager role in the organization; without `organization_id` the caller's only organization is used |

Unknown form fields are rejected, so a misspelled parameter is never silently ignored.
The response echoes the effective settings in `analysis.settings`.

The platform routes (accounts, organizations, sites, recorders, deployments,
batch uploads, recordings, dashboards, phenology, alerts, notifications,
recorder health, reports, files) are listed with their roles in
[`docs/PLATFORM_API.md`](../docs/PLATFORM_API.md). With `AUTH_MODE=disabled`
every route works without a login as the owner of the local workspace
(`org_000000000000000000000000`).

### curl examples

```bash
API=http://127.0.0.1:8000/api/v1

curl -s $API/health
curl -s $API/models

# Analyze and wait for the result
curl -s -X POST "$API/analyses?wait=true" \
  -F file=@tests/fixtures/soundscape_30s.flac \
  -F threshold=0.5 -F latitude=42.44 -F longitude=-76.50 \
  -F captured_at=2026-05-14T06:30:00 -F timezone=America/New_York \
  -F site_name="Sapsucker Woods"

# Or queue it and poll
ID=$(curl -s -X POST $API/analyses -F file=@recording.wav | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s $API/analyses/$ID | python -c 'import sys,json;a=json.load(sys.stdin);print(a["status"],a["stage"])'

# Same analysis at another threshold, and exports
curl -s "$API/analyses/$ID?threshold=0.3"
curl -s -OJ "$API/analyses/$ID/export.csv?threshold=0.6"
curl -s -OJ "$API/analyses/$ID/export.json?threshold=0.6"

# Preview first, then analyze without uploading again
PID=$(curl -s -X POST $API/previews -F file=@recording.wav | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s -X POST "$API/analyses?wait=true" -F preview_id=$PID -F models='["birdnet"]'

# Review an event (reject, accept, correct, or reset with "unreviewed")
curl -s -X PATCH "$API/events/evt_0123456789abcdef?threshold=0.6" \
  -H 'content-type: application/json' \
  -d '{"review_status": "corrected", "reviewed_label": "Purple Finch", "review_note": "song, not call"}'

curl -s -X DELETE $API/analyses/$ID
```

### Error codes

| `error_code` | HTTP | When |
|---|---|---|
| `unsupported_file_type` | 415 | Extension not allowed, or content does not match it |
| `file_too_large` | 413 | Over `MAX_UPLOAD_BYTES` (checked while streaming) |
| `audio_decode_failed` | 422 | FFmpeg cannot decode the file |
| `audio_too_short` | 422 | Shorter than `MIN_AUDIO_DURATION_SECONDS` |
| `audio_too_long` | 422 | Longer than `MAX_AUDIO_DURATION_SECONDS` |
| `unsupported_audio` | 422 | Sample rate below 16 kHz, or input a model cannot use |
| `unknown_model` | 422 | A `models` key that is not registered |
| `model_unavailable` | 422 / 503 | 422 for a disabled (experimental) model, 503 when a model failed to load |
| `invalid_parameter` | 422 | Any invalid field or query parameter, including thresholds below the ingestion floor |
| `analysis_not_found` | 404 | Unknown or malformed analysis id |
| `event_not_found` | 404 | Unknown event id |
| `not_found` | 404 | Unknown path, expired preview, audio not retained |
| `rate_limited` | 429 | Too many POSTs from one IP (`Retry-After` header) |
| `analysis_timeout` | 504 | The analysis exceeded `ANALYSIS_TIMEOUT_SECONDS` |
| `request_timeout` | 504 | The request exceeded `REQUEST_TIMEOUT_SECONDS` |
| `internal_error` | 500 | Unexpected failure; no internals are exposed |
| `unauthenticated` | 401 | Sign-in required (or the session expired or was revoked) |
| `forbidden` | 403 | Not a member of the organization, role too low, or missing `X-Requested-With: thicket` |
| `conflict` | 409 | Deleting a site or recorder with recordings, last owner, used or expired invite |

A completed analysis with no detections above the threshold is a valid result,
not an error.

## Architecture

```
upload (multipart stream)
  -> intake: extension + magic bytes, size cap while streaming, random name, SHA-256
  -> probe (ffprobe): decode check, duration and sample-rate limits
  -> queued analysis row, job on a bounded thread pool (WORKER_CONCURRENCY)
       normalizing     decode to 48 kHz mono; stream native-rate level stats
       quality         clipping, level, silence, low-frequency energy, DC, band, duration
       spectrogram     canonical PNG
       model:<key>     each adapter with its own model_run_id
       consolidating   renumber detections, speech QC, optional QC head, events at the threshold
       metrics         acoustic indices
  -> completed | failed   (temp dir removed in finally; audio kept only if RETAIN_AUDIO)
```

`analysis.stage` shows the current stage while running and
`stage_timings_ms` records each stage's duration.

Code map:

| Path | Role |
|---|---|
| `thicket/api/` | Schemas (the contract), routes, error handlers, middleware |
| `thicket/services/analysis.py` | The pipeline and job lifecycle |
| `thicket/services/results.py` | Derive-on-read: events, species and metrics at a threshold |
| `thicket/services/intake.py` | Streaming multipart parser and upload checks |
| `thicket/services/previews.py`, `janitor.py`, `exports.py`, `spectrogram.py` | As named |
| `thicket/domain/` | Pure logic: consolidation, metrics, quality, acoustic indices |
| `thicket/models/` | Adapter contract, BirdNET runtime and adapter, frog/insect head, registry |
| `thicket/persistence/` | SQLAlchemy schema, analysis repository, platform repository |
| `thicket/services/auth.py` | Sessions, dev sign-in, Google OpenID Connect |
| `thicket/services/ingest.py`, `filenames.py`, `telemetry.py` | Batch uploads, zips, timestamps, device metadata |
| `thicket/services/rollups.py`, `dashboard.py` | Day rollups, dashboard, phenology, accumulation, comparison |
| `thicket/services/alerts.py`, `notify.py`, `recorder_health.py` | Alert engine, notifications and email, recorder health |
| `thicket/services/nightly.py` | Nightly scheduler |
| `thicket/reports/` | Field schema, data bundle and PDF renderer |
| `thicket/cli.py` | Command line |

### One metrics path

Raw window detections at or above the ingestion floor (`RAW_THRESHOLD`) are
stored once. Events, the species table and metrics are derived on every read at
the requested threshold: `consolidate` then reviews then `counted_events` then
`species_summaries` and `compute_metrics`. The same function serves the
analysis view, list summaries, CSV and JSON exports and review responses, so
every number a user sees comes from the same event set.

Counted events exclude non-wildlife labels (human, noise, engines), events
rejected in review and birds that are `unlikely` for the location and date.
Excluded events stay listed with their status and are explained in `warnings`;
every event carries `counted_in_metrics`, true exactly for the counted set.
Metrics are detection-derived: every completed analysis carries the warning
"Metrics are based on acoustic detection events and do not estimate individual
abundance."

Review rules: `rejected` excludes the event from metrics; `corrected` moves it
to the reviewer's label when that matches a known model label (scientific,
common or raw name), otherwise excludes it; `accepted` also overrides an
`unlikely` range flag; `unreviewed` clears the review.

Reviews follow the reviewed audio, not the event id. A review stores the raw
windows of the event it was made on. At any threshold, windows of a rejected or
corrected event are set aside before consolidation and listed as that event
(same id and status), so a rejected call never comes back merged with weaker
windows at a lower threshold; windows nobody reviewed form their own,
unreviewed events. An event inherits an acceptance only when all its windows
are inside the accepted event. The full rule is in `thicket/services/results.py`.

A corrected event's row names the species it counts under (`scientific_name`,
`common_name`, `taxon`); `detected_*` keep the model's label and
`reviewed_label` the reviewer's text. Confidences and `plausibility` always
describe the detected label.

### Combined models

Each adapter run has its own `model_run_id`. Consolidation never merges across
runs and nothing is deduplicated across models: if BirdNET and the frog/insect
head both report a species, each run keeps its own events, and the species
table groups them by scientific name with every contributing run listed in
`model_run_ids`. The frog/insect head reuses BirdNET's window embeddings when
both run in one analysis, so BirdNET inference happens once.

### Models

* **BirdNET v2.4** (`birdnet`): 3 s windows at 48 kHz, sigmoid scores, labels
  parsed once in the runtime. With coordinates, BirdNET's meta model scores each
  label for the location and week (week -1 without a date); birds below
  `LOCATION_FILTER_THRESHOLD` are `unlikely`. Frogs, insects and mammals stay
  `unknown` because the meta model gives them near-zero scores everywhere.
* **Frogs and insects** (`frog_insect`, experimental, off by default): a small
  NumPy head on BirdNET embeddings (`thicket/models/frog_insect.py` documents the
  `.npz` format). It is disabled until a validated model with a benchmark and
  model card is installed.

### Audio quality

Checks: duration, sample rate (below 32 kHz warns that content above half the
sample rate is missing; below 16 kHz fails), clipping (native rate, every
channel), level, silence (50 ms frames below -60 dBFS), low-frequency energy
(wind and handling heuristic), DC offset, and speech (BirdNET "Human vocal"
at 0.5 or more, with a privacy warning). When the optional soundscape QC head
(`thicket/models/qc_head.py`) is installed it adds contamination flags such as
rain, wind or engines.

Status is `not_usable` if any check fails and `usable_with_warnings` if any
warns. The score is a transparent heuristic, not a probability:
`clamp(1 - 0.15 x warnings - 0.40 x failures, 0, 1)`, capped at 0.3 when any
check fails.

### Acoustic indices

ACI (Pieretti et al. 2011), ADI and AEI (Villanueva-Rivera et al. 2011),
BI (Boelman et al. 2007), NDSI (Kasten et al. 2012), spectral and temporal
entropy (Sueur et al. 2008). Formulas and conventions are in
`thicket/domain/acoustic_indices.py`; a test cross-checks them against
scikit-maad.

### Spectrogram

One server-side implementation: STFT with n_fft 1024 and hop 256 on 48 kHz mono,
power averaged into at most 2400 columns, 0 to 16 kHz linear
(`spectrogram_min_hz` / `spectrogram_max_hz`), 512 px tall, 80 dB range below
the 99.5th percentile, dark forest to cream colormap, no axes. Output is
byte-for-byte deterministic.

## Accounts and sign-in

Three modes, set with `AUTH_MODE`:

| Mode | Who you are | Use it for |
|---|---|---|
| `disabled` (default) | The implicit owner of the implicit organization "Local workspace". No cookies, no CSRF header. | A laptop, the CLI, tests, or a private instance behind an authenticating proxy. Refused when `ENVIRONMENT=production` unless `ALLOW_UNAUTHENTICATED=true` |
| `dev` | Whoever types an email into `POST /api/v1/auth/dev` | Local development of the multi-user app. Refused when `ENVIRONMENT=production` |
| `google` | A verified Google account | Any shared instance |

Sessions are signed cookies (`thicket_session`, itsdangerous with
`SESSION_SECRET`): HttpOnly, SameSite=Lax, Secure when `PUBLIC_BASE_URL` is
https, valid 30 days and re-issued on use once they are an hour old. Logout
puts the session id on a revocation list (pruned nightly). With sign-in
enabled every POST, PATCH, PUT and DELETE under `/api/` must carry
`X-Requested-With: thicket`; the frontend client always sends it. When the
frontend is served from another origin, list it in `ALLOWED_ORIGINS`; CORS
then allows credentials.

Roles per organization: owner (everything, members, delete), manager (sites,
recorders, uploads, alert rules, reports), reviewer (review events,
acknowledge alerts, create reports), viewer (read). Invites
(`POST /orgs/{org}/invites`) return a one-time link
`FRONTEND_URL/#/invite/<token>`, valid 7 days, for the invited email only.
`DELETE /orgs/{org}/invites/{invite_id}` revokes one that nobody accepted
(owner invites need an owner). The last owner can neither leave nor be
demoted; the check runs inside the same statement as the change, so two
owners demoting each other at once cannot both succeed.

### Google sign-in, step by step

1. Open the [Google Cloud console](https://console.cloud.google.com/) and pick or
   create a project for Thicket.
2. **APIs & Services > OAuth consent screen**: choose *External* (or *Internal*
   for a Google Workspace organization), fill in the app name, support email
   and developer contact, and add the scopes `openid`, `email` and `profile`.
   While the app is in *Testing*, add the Google accounts that may sign in as
   test users, or publish the app.
3. **APIs & Services > Credentials > Create credentials > OAuth client ID**,
   application type *Web application*.
4. Under **Authorized redirect URIs** add exactly
   `${PUBLIC_BASE_URL}/api/v1/auth/google/callback`, for example
   `https://thicket.example.org/api/v1/auth/google/callback`, and for local
   work `http://localhost:8000/api/v1/auth/google/callback`. Authorized
   JavaScript origins are not needed (the browser never talks to Google
   directly).
5. Copy the client ID and client secret into the environment:

   ```bash
   AUTH_MODE=google
   GOOGLE_CLIENT_ID=1234-abc.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-...
   PUBLIC_BASE_URL=https://thicket.example.org      # where this API is reachable
   FRONTEND_URL=https://thicket.example.org          # where the web app is served
   SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
   ALLOWED_SIGNIN_DOMAINS=farm.example.org           # optional
   ```

6. Restart the API and open `GET /api/v1/auth/config`: it reports
   `"mode": "google"` and `sign_in_url: /api/v1/auth/google/start`. The sign-in
   button sends the browser there; Google returns to the callback, which sets
   the session cookie and redirects to `FRONTEND_URL/#/` (or the `next` path).
7. The first person to sign in has no organization yet: they create one
   (`POST /orgs`, they become owner) and invite the others.

What the server checks: the authorization code flow uses PKCE (S256), with
`state`, the PKCE verifier and a `nonce` in a ten-minute signed cookie. The ID
token is verified against Google's JWKS (RS256 signature, `aud` equal to the
client id, `iss` accounts.google.com, `exp`, `nonce`), and `email_verified`
must be true. Discovery and keys are cached for an hour; an unknown key id
triggers one refetch.

## Batch ingestion

`POST /api/v1/orgs/{org}/uploads` (manager) takes many files in one
multipart request: audio (`.wav .mp3 .m4a .flac .ogg`), zips of them, Song
Meter `*_Summary.txt` and AudioMoth `CONFIG.TXT`. `site_id` and `timezone` (the
recorder clock's zone) are required; `deployment_id`, `recorder_id`, `models`,
`threshold`, `last_modified` (one millisecond timestamp per file, same order)
and `captured_at_override` are optional. It answers 202 with a `BatchJob` to
poll at `GET /uploads/{job_id}`.

* Caps: `MAX_UPLOAD_BYTES` per audio file, `MAX_BATCH_FILES` files and
  `MAX_BATCH_BYTES` per batch, zip contents included, enforced while
  streaming and while extracting.
* Zips: members with absolute paths, `..`, hidden names or `__MACOSX` are
  skipped, as are non-audio files and nested zips; corrupt members are
  skipped and listed in `settings.skipped_entries`.
* Each audio file becomes one recording and one analysis through the same
  analysis service as the single-file workspace. Batch work runs in a lower
  priority lane of the worker pool (at most half the workers, rounded up), so the
  workspace stays responsive during a 200-file upload. A failing file fails
  its item, not the job (`completed_with_errors`).
* Recorders and deployments: a device id from an AudioMoth comment, GUANO
  serial, Song Meter file prefix or `CONFIG.TXT` finds or creates the
  recorder, and a deployment at the site is found or created around the
  recording time (with the interval, clip length and gain from `CONFIG.TXT`).

Timestamp order, recorded as `captured_at_source`: the file name pattern
(`filename`), then the file's metadata (`file_metadata`: AudioMoth WAV
comment or GUANO `Timestamp`), then the browser's `last_modified`
(`browser_last_modified`), then `captured_at_override` (`user`).

| File name | Read as |
|---|---|
| `20240514_053000.WAV`, `24A1D5F3_20240514_053000.WAV`, `north_20240514_0530.wav` | AudioMoth, UTC (or the fixed offset in `CONFIG.TXT`). Prefix optional, seconds optional, case-insensitive |
| `SMA12345_20240514_053000.wav`, `SMM01234_20240514_053000.wav`, `S4A09876_20240514_053000_1.wav` | Song Meter, the recorder's local clock (the batch `timezone`) |
| `2024-05-14T05-30-00.m4a`, `2024-05-14 05.30.00.wav`, `20240514T053000.flac` | ISO style, local clock |
| `New Recording 7.m4a` | no timestamp in the name |

A recorder registered as `audiomoth` or `song_meter` overrides the pattern's
guess (a Song Meter is always local time, an AudioMoth always UTC).
Telemetry comes from the AudioMoth comment (battery, temperature, gain,
device), GUANO (temperature, serial, position) or the Song Meter summary row
within 60 seconds of the recording's local start (battery `POWER(V)`,
`TEMP(C)`, `LAT`/`LON`; header variants and separate hemisphere columns are
accepted). Every recording also gets a signal profile: band energy fractions
(0 to 1, 1 to 4, 4 to 8 and above 8 kHz, Welch PSD of the 48 kHz mono mix),
spectral centroid, per-channel RMS from the original channels, peak, DC
offset and clipping.

## Rollups and dashboards

After each completed analysis (and after each review) the recording's row in
`recording_stats` and its site-day in `site_day_stats` and
`species_day_stats` are recomputed from all of that day's analyses, each at
its own recorded threshold, through the same `results.derive` path as every
other view. Local dates use the organization's time zone (changing it
rebuilds the organization's rollups at once); a recording without a
timestamp falls on its upload date. The nightly job rebuilds all of it, one
site at a time: each site's new rows are computed and then swapped in within
one transaction, so dashboards never read an empty or half-built site.
`GET /orgs/{org}/dashboard` (default the last 90 days, ending on the
organization's local today), `/phenology` (ISO weeks by ISO year from the
Monday of week 1: presence fraction and events per minute),
`/sites/{id}/accumulation` and `/orgs/{org}/sites/compare` read these
tables. Across sites, a day's richness is the union of species and Shannon
uses the summed per-species events.

## Alerts and baselines

The engine runs after each completed analysis, on
`POST /orgs/{org}/alerts/evaluate` and nightly. Rules are per organization
(`GET/PUT /orgs/{org}/alert-rules`).

* **Comparable recordings** (ecology): same site, same hour bucket, earlier
  recordings within 21 days of the same date across years (a day-of-year
  distance, so the window is as wide at New Year as in June); if there are fewer than `min_baseline_recordings` (8), the last
  eight weeks at that site and bucket; if still too few, no ecology alert.
* **Hour buckets**: with site coordinates, from sunrise and sunset (astral):
  dawn is one hour before to two hours after sunrise, dusk one hour either
  side of sunset, day between, night the rest. Without coordinates (or with
  no sunrise, near the poles): 04 to 09 dawn, 09 to 17 day, 17 to 21 dusk,
  21 to 04 night, local time.
* **Statistics**: median and MAD (scaled by 1.4826), never the mean, with a
  small floor on the MAD so a perfectly flat history cannot turn a tiny change
  into an alert.
* **Kinds**: `richness_drop` and `activity_drop` (the last
  `consecutive_recordings` all below the median by the configured MAD
  multiple), `new_species_for_site`, `priority_species_detected` (no
  baseline needed), `expected_species_missing` (nightly; a species present in
  at least half of the comparable recordings is missing from the last six),
  `species_surge`, `low_quality_streak`, `speech_detected`; recorder checks
  per deployment: `muffled_audio` (high-band share and centroid both more than
  3 MAD below, for the consecutive run), `level_drift` (more than 6 dB from
  the deployment median for the bucket; warning above 12 dB),
  `recording_gap` (a hole *between consecutive recordings* of a deployment,
  counted only inside its recording window, longer than `gap_multiplier`
  times the declared or inferred interval and at least `gap_min_hours`; never
  measured from "now", so an SD card uploaded weeks later is not an outage),
  `upload_overdue` (`info` or `watch` only: a deployment that has uploaded
  on a routine, at least three upload spacings, has sent nothing for twice
  its median spacing; four times makes it `watch`), `clipping_increase`,
  `channel_imbalance` (more than 12 dB between channels), `dc_offset` (above
  0.02), `battery_low` (per make), `temperature_extreme`, `clock_suspect`
  (per recorder in one upload: out of order, duplicates, future times), and
  `schedule_deviation` (when an interval is declared; minutes inside the
  recording window).
* **Recording window**: a deployment records in its *active hours*, from
  `HH:MM-HH:MM` ranges in its `schedule_description` (local time, wrapping
  midnight allowed, for example `04:00-08:00, 18:30-20:00`), otherwise every
  local hour any of its recordings starts in or runs through. A dawn-only
  AudioMoth therefore has no nightly "gap", and a two-day hole in a dawn
  schedule counts as eight hours.
* **Deduplication**: `(kind, site, recorder, species)`, enforced by a unique
  index on `alerts.open_key` (one unresolved alert per key, also when two
  workers raise it at once). A repeat of an open, acknowledged or snoozed
  alert updates `last_seen_at`, the evidence and (only for new recordings)
  `occurrences`, and sends nothing new. Re-evaluating the same recordings
  never reopens an alert someone resolved; reopening one while a newer alert
  of the same key is open is a 409. Snoozed alerts reopen when due.
* Every `detail` names the observed value, the baseline and `n`, for example
  "Observed a high-band share of 5% and a spectral centroid of 600 Hz in the
  last 3 recordings; baseline medians 30% (MAD 0) and 2500 Hz (MAD 0) from n =
  12 recordings (same deployment, dawn recordings)." Each kind has a plain
  `suggested_action`.

Notifications: each new alert creates an in-app notification for every
member whose preferences match (category, minimum severity; defaults watch
and up). Email is immediate or in a daily (every night) or weekly (Mondays)
digest, through SMTP (STARTTLS), Resend, or `.eml` files in
`<data>/outbox/` when neither is configured. Email carries no audio and no
notes.

`GET /recorders/{id}/health?days=30` covers the `days` up to the recorder's
latest recording (not up to today: cards arrive late) and returns series
(battery, temperature, level, high-band share, centroid, clipping), gaps
inside the recording window, checks with their baselines, the median
interval (declared on the deployment or inferred from at least three
intervals of active minutes) and `uptime_fraction_7d`: recordings in the 7
days up to the latest one against the number the schedule expects in its
active hours.

## Reports

`POST /orgs/{org}/reports` (reviewer) queues one of five templates from
[`docs/REPORTING.md`](../docs/REPORTING.md): `evidence`, `nrcs`, `aem`,
`certification`, `credit`. `GET /reports/templates` lists their pages and
user-entered fields (`thicket/reports/field_schema.json`, section 7 of that
document with labels and help text). Rendering runs in the batch lane of the
worker pool; poll `GET /reports/{id}` until `ready`, then download
`/reports/{id}.pdf` or the data bundle `/reports/{id}.json`.

* The bundle holds every number in the PDF; each analysis is derived at the
  report's `decision_threshold` (or its own) through the same path as the API.
* Every page footer prints the report id, the software version, the platform
  schema version and the SHA-256 of the JSON bundle.
* ReportLab and matplotlib (Agg, figure API) with no system dependencies;
  forest greens on paper, no rainbow palettes.
* Blank template fields print as "not provided" and are listed in
  `missing_fields` (required ones first). Images (`deployment_photo`,
  `tract_map_image`, `project_boundary_file`) are uploaded first with
  `POST /orgs/{org}/files` and referenced by id.
* A period without recordings renders a "No recordings in this period" page.
* A test extracts the text of every template's PDF and checks that none of
  the phrases in section 8 of `docs/REPORTING.md` appear.

## Nightly jobs

One scheduler (`thicket/services/nightly.py`) wakes at
`NIGHTLY_JOBS_HOUR_UTC` and runs, each step isolated from the others: the
full rollup rebuild, gap and expected-species checks for every organization,
daily digests (and weekly ones on Mondays), pruning of the session revocation
list and the janitor's cleanup. `python -m thicket.cli nightly` runs one pass
by hand.

## Database upgrades

The schema is at version 4. A database written by the single-user build
(schema 1 or 2) is upgraded in place at startup: new nullable columns are
added with `ALTER TABLE`, new tables are created, the local workspace user
and organization are created (on the time zone most of its recordings
declare), existing sites and recordings are attached to it, missing indexes
are created and the rollups are built once. Schema 4 adds `alerts.open_key`
and its unique index; should two unresolved alerts share a key, the newer
keeps it and the older is resolved.

## Privacy, retention and security

* Uploaded audio lives only in a per-analysis temp folder and is deleted when
  the analysis ends (success or failure). Set `RETAIN_AUDIO=true` to keep a
  normalized copy. Previews keep their upload until `PREVIEW_TTL_MINUTES`, until
  an analysis takes it, or until `DELETE /previews/{id}` (the web app calls it
  on Clear and when another file replaces a previewed one).
* A janitor thread removes orphaned temp folders, expired previews and orphaned
  assets every `JANITOR_INTERVAL_SECONDS`.
* Client filenames are display metadata only; storage names are random, and ids
  are validated with strict patterns before any path is built.
* Strict CORS (exact origins), per-IP rate limiting of POSTs (keyed on
  `CLIENT_IP_HEADER` behind a proxy), request and
  analysis timeouts, security headers, and no internals in error messages.
* Logs are JSON lines with ids, stages, timings and error codes. They never
  contain audio, filenames, notes, coordinates or email addresses, and invite
  tokens are redacted from logged paths.
* With `AUTH_MODE=disabled` there is no authentication: run it for a single
  user or behind an authenticating proxy. `ENVIRONMENT=production` refuses to
  start that way unless `ALLOW_UNAUTHENTICATED=true` is set (and then logs a
  warning). Use `AUTH_MODE=google` for a shared instance (see below).
* Every platform resource belongs to one organization. A member of another
  organization gets 404 for its resources by id and 403 on its
  `/orgs/{org}/...` routes.

## Tests

```bash
cd backend && source .venv/bin/activate
pytest                          # full suite (BirdNET tests run when weights are installed)
pytest -m "not birdnet"         # fast subset
ruff check ../backend ../ml && ruff format --check .
python scripts/export_schema.py --check   # shared/api.schema.json is current
```

Synthetic fixtures (tones, noise, silence, clipping, low sample rates, corrupt
files, MP3/M4A/OGG transcodes) are generated per session; only
`tests/fixtures/soundscape_30s.flac` is committed. Platform tests run without
BirdNET: `tests/platform_helpers.py` writes synthetic analyses straight to the
database and provides a tone-driven fake adapter, WAV writers with AudioMoth
comments and GUANO chunks, and sign-in helpers; `tests/google_mock.py` serves
Google's discovery document, JWKS and token endpoint through
`httpx.MockTransport`.

## Deployment

The root `Dockerfile` builds the frontend (Node 22), installs
`backend[birdnet]` on `python:3.11-slim` with FFmpeg, bakes the BirdNET cache,
runs as a non-root user and serves the frontend at `/`:

```bash
make docker-build && make docker-run        # http://localhost:8000
docker compose up --build                    # same, with a named volume
```

`render.yaml` and `fly.toml` deploy one instance with 2 GB RAM and a volume at
`/data`, with Google sign-in on (`AUTH_MODE=google`).

**Sign-in is required in production.** With `ENVIRONMENT=production` (set by
the Dockerfile, `fly.toml` and `render.yaml`) the server refuses to start with
`AUTH_MODE=disabled`, because every visitor would be the owner of the local
workspace and could upload, change and delete everything. Before the first
deploy:

1. Create the Google OAuth client (see "Google sign-in, step by step") with the
   redirect URI `https://<your host>/api/v1/auth/google/callback`.
2. Set the required secrets (never in a committed file):
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `SESSION_SECRET` (48 random
   characters: `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
   On Fly: `fly secrets set GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
   SESSION_SECRET=...`. On Render the Blueprint lists them with `sync: false`,
   so the dashboard asks for each value.
3. Point `PUBLIC_BASE_URL` and `FRONTEND_URL` at your host (both default to the
   `*.fly.dev` / `*.onrender.com` names in the configs).

A private instance behind an authenticating proxy (or a laptop) may run
without sign-in by setting `ALLOW_UNAUTHENTICATED=true` explicitly; the server
then logs a warning at every start. `make docker-run` and `docker compose up`
do this and publish the port on `127.0.0.1` only.

Moving to sign-in later? Data uploaded without sign-in lives in the local
workspace, which no signed-in user can open. Hand it to an organization with
`python -m thicket.cli adopt-local` (see "Command line"). Run exactly one uvicorn worker per instance: the model is loaded per
worker process. Behind a proxy set `CLIENT_IP_HEADER` to the header the proxy
writes with the client IP (`Fly-Client-IP` on Fly) so rate limits see real
clients; never set `FORWARDED_ALLOW_IPS="*"`, because the left end of
`X-Forwarded-For` is whatever the client sent. Set `ALLOWED_ORIGINS` to your
public origin when the frontend is hosted separately.

Licensing: BirdNET v2.4 weights are CC BY-NC-SA 4.0 (non-commercial). Clear
commercial use with the BirdNET team before offering Thicket commercially.

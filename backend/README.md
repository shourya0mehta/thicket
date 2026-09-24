# Thicket backend

FastAPI service that turns field audio into transparent species detections,
detection-derived metrics, acoustic indices and exportable evidence.

* Python 3.11+, FastAPI, Pydantic v2, NumPy/SciPy, SQLAlchemy 2.0 (SQLite by default)
* BirdNET v2.4 (TFLite, CC BY-NC-SA 4.0) through a typed adapter interface
* FFmpeg for decoding (WAV, MP3, M4A/AAC, FLAC, OGG)

The API contract lives in [`thicket/api/schemas.py`](thicket/api/schemas.py) and is
exported to [`shared/api.schema.json`](../shared/api.schema.json), which the frontend
turns into TypeScript types.

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

Unknown form fields are rejected, so a misspelled parameter is never silently ignored.
The response echoes the effective settings in `analysis.settings`.

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
| `thicket/persistence/` | SQLAlchemy schema and repository |
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
  contain audio, filenames, notes or coordinates.
* This pilot has no authentication: deploy it for a single user or behind an
  authenticating proxy.

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
`tests/fixtures/soundscape_30s.flac` is committed.

## Deployment

The root `Dockerfile` builds the frontend (Node 22), installs
`backend[birdnet]` on `python:3.11-slim` with FFmpeg, bakes the BirdNET cache,
runs as a non-root user and serves the frontend at `/`:

```bash
make docker-build && make docker-run        # http://localhost:8000
docker compose up --build                    # same, with a named volume
```

`render.yaml` and `fly.toml` deploy one instance with 2 GB RAM and a volume at
`/data`. Run exactly one uvicorn worker per instance: the model is loaded per
worker process. Behind a proxy set `CLIENT_IP_HEADER` to the header the proxy
writes with the client IP (`Fly-Client-IP` on Fly) so rate limits see real
clients; never set `FORWARDED_ALLOW_IPS="*"`, because the left end of
`X-Forwarded-For` is whatever the client sent. Set `ALLOWED_ORIGINS` to your
public origin when the frontend is hosted separately.

Licensing: BirdNET v2.4 weights are CC BY-NC-SA 4.0 (non-commercial). Clear
commercial use with the BirdNET team before offering Thicket commercially.

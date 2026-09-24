# Thicket product specification (condensed)

Condensed from the rebuild handoff written by Shourya Mehta (September 2026).
It keeps every requirement, number and decision; long rationale is trimmed.

## 1. What Thicket is

Software-first biodiversity monitoring that turns field audio into
understandable, exportable ecological evidence.

User journey: upload a short recording, validate and normalize it, preview
audio and spectrogram, run acoustic classifiers for timestamped detections
with confidence, consolidate windows into defensible detection events, show
species composition, detection-derived metrics, a timeline and (only with real
coordinates) a map, let the user inspect uncertain detections, export CSV/JSON.

Audience: US conservation NGOs and land trusts, restoration projects,
regenerative farms and ranches, easements and mitigation banks, forest and
carbon projects documenting co-benefits, parks, watersheds and agencies.

Positioning: "Thicket is biodiversity monitoring software that turns passive
field audio into transparent species detections, acoustic biodiversity
indicators, maps, trends, and exportable evidence."

Never claim: abundance from one microphone, regulatory compliance, unvalidated
field accuracy, multi-taxa recognition before benchmarking, causation.

## 2. Principles

1. Reliability before spectacle: abstain or flag rather than force an answer.
2. Detection is not abundance. A call event is not an animal.
3. Provenance everywhere: model version, threshold, input metadata, settings.
4. Software first: phone recordings and common recorders before hardware.
5. Pretrained models first. Train only when justified and validated.
6. Modular by taxon behind a common adapter interface.
7. Modern but calm UI: environmental intelligence, not a notebook or a toy.
8. Human review is a feature.
9. Longitudinal value (repeat surveys, comparisons, maps) is the moat.

## 3. Status labels

Confirmed intent, historically built and evidenced, partially built, planned,
historical suggestion (revalidate). Never convert roadmap into capability.

## 4. Releases

* A (trustworthy local bird MVP): upload, metadata, playback, file facts,
  spectrogram, BirdNET, timestamped predictions, threshold control,
  consolidated events, species table, richness, Shannon, Pielou evenness,
  dominant species, total events, timeline, CSV/JSON, limitations and
  provenance, responsive UI, automated tests.
* B (single-user pilot): deployment, storage with retention, persistent
  analyses and sites, real map coordinates only, history, audio QC, review and
  correction, shareable read-only report, analytics and monitoring.
* C (validated multi-taxa pilot): frog/insect model with a valid benchmark,
  taxon thresholds, range/season/time plausibility, per-taxon metrics, model
  registry and model cards, repeat-survey comparisons.
* D (platform): orgs, roles, projects, sites, protocols, batch ingestion,
  trends, map layers, review queues, evidence packages, recorder integrations.

## 5. UX requirements

Header: leaf mark, "Thicket", tagline "Listen to Nature", theme toggle.

Controls: custom "Choose file" button driving one hidden input via a ref (never
a button nested in a label); filename and size; optional latitude, longitude,
recording date/time, timezone, site name; model selector (Birds BirdNET stable;
Frogs and insects experimental and feature-flagged; Combined experimental and
feature-flagged); Generate spectrogram; Run analysis; Clear/reset.

Empty state explains three steps. Processing shows explicit stages: uploading,
normalizing audio, checking audio quality, generating spectrogram, running
BirdNET, consolidating detections, computing metrics. "Crunching the
birdsongs..." may appear only as secondary copy. Spinner must be size
constrained.

Results: max-width 12-column grid. Spectrogram/audio card left, biodiversity
summary and species-frequency cards right, detections full width below, export
bar at the bottom. Tabs: Results, Timeline, Map (only with real coordinates);
later Review, Methods, Compare. Mobile stacks in the same order.

Required states: no file, unsupported extension, too large, decode failed, no
detections above threshold (a valid result, not an error), audio quality too
low, model unavailable, unsupported sample rate or band, timeout, backend
unavailable.

Design: deep forest greens, calm, rounded panels, generous whitespace, subtle
gradients and translucency, restrained motion. Tokens: forest-600 #377157
(primary), forest-700 #2f5c47 (hover), forest-800 #224235; full 50 to 950
scale. Inter (or similar). Radius 1.25rem. Soft shadows, thin borders. Light
cards ~80% white with blur; dark cards low-opacity white on deep green/charcoal.
Class-based dark mode persisted as "thicket-theme", system preference first.

Accessibility: keyboard navigation, visible focus, labeled controls, never
encode meaning by color alone, semantic headings and tables, chart
descriptions for screen readers, WCAG AA, reduced motion.

## 6. Frontend functional requirements

* File intake: .wav, .mp3, .m4a (with FFmpeg), .flac. 20 MB client guard;
  server enforces its own limits. New file clears prior results/errors.
* Playback with current time, jump to detection, highlight active detection.
* Spectrogram: one canonical implementation, dark 16:10 area, time and
  frequency labels, hover time, detection overlays in the timeline view.
* Confidence control: default 0.60, step 0.05, shows percent, updates species,
  events, charts and metrics consistently. Keep raw detections above a low
  ingestion floor; the request carries the decision threshold; all metrics
  come from the same post-threshold event set; the threshold is recorded.
* Species table: common name, italic scientific name, taxon/model, event
  count, max and mean confidence, total duration, first detection; sortable.
* Metrics: richness, Shannon, Pielou, total events, dominant species, duration,
  timestamp; later Simpson, events per minute, taxon proportions, quality
  score, review share. Each has a tooltip: derived from detections, not a
  census.
* Timeline: events on a time axis, click to seek, filter by species, taxon,
  confidence, overlapping species on separate rows.
* Map: Leaflet + OSM, only with valid real coordinates, otherwise "Location
  not provided". Never a fallback point.
* Export: CSV of the selected analysis (analysis id, recording, site, lat/lon,
  start time/timezone, taxon, names, event start/end, confidence, model and
  version, threshold, review status); JSON with full provenance.
* Local history: last three analysis summaries for the no-auth pilot.

## 7. Backend

FastAPI, Pydantic v2, NumPy, SoundFile, FFmpeg, BirdNET, SQLite first then
Postgres, storage abstraction. Pipeline: validate type and signature, stream
upload with a cap, inspect audio, flag speech/privacy risk, normalize per
adapter (BirdNET: mono 48 kHz), spectrogram, run adapters, normalize to
canonical detections, threshold and plausibility, consolidate, metrics from
that exact event set, persist provenance, clean temp files.

API: `GET /api/v1/health`, `GET /api/v1/models`, `POST /api/v1/analyses`
(multipart: file, models, threshold 0.60, latitude, longitude, captured_at,
timezone, site_name), `GET /api/v1/analyses/{id}`,
`GET /api/v1/analyses/{id}/export.csv|export.json`,
`PATCH /api/v1/events/{event_id}` (review).

## 8. Science rules

Consolidation: filter by threshold, group by species, sort, merge overlapping
or near-adjacent windows (configurable merge gap, historically 1 s), keep max
confidence and mean over contributing windows. Names: raw_detection_count,
detection_event_count, events_per_minute. Never animals, individuals,
population or abundance.

Metrics over consolidated event counts n_i, N = sum n_i, p_i = n_i / N:
richness S; Shannon H' = -sum p_i ln p_i (0 when empty); Pielou J' = H'/ln S
when S > 1 else 0; Simpson documented as 1 - sum p_i^2. These are
detection-derived acoustic indices.

Adapters implement name, version, taxon_scope, required_sample_rate_hz,
experimental, is_ready(), analyze(). Load once. Typed errors
(model_unavailable, unsupported_audio). Combined mode keeps model_run_id on
every detection and does not dedupe across unrelated taxon models.

Historical frog/insect experiment (OpenSoundscape ResNet18, 11 classes, 490
train / 116 val files, "0.849" best validation score) failed later validation
and must not be presented as accurate. Future models must output localized
windows and ship with a model card and benchmark before being enabled.

Audio QC: decode, duration, sample rate, clipping, silence, level, wind/rain/
mechanical heuristics, unsupported band. Return usable, usable_with_warnings,
not_usable. Human speech policy: inform, define retention, restrict, delete.

Validation: define targets before results; site gold sets; per-species
precision, recall, F1, PR curves, calibration, bootstrap CIs, holdout by site
and time; noise stress tests; evidence package. Evaluation scripts must check
API parameters, label-set compatibility, adapter identity, model version and
dataset manifest before computing metrics.

## 9. Security and operations

Validate signatures, stream and cap uploads, randomize names, prevent path
traversal, rate limit, timeouts, strict CORS, auth before private storage,
retention and deletion, structured logs with analysis id, per-stage latency,
never log audio. Per-analysis temp directory cleaned on success and failure,
periodic orphan cleanup.

## 10. Acceptance for the first rebuild

Upload supported short audio; reject bad files readably; playback;
non-blocking spectrogram; canonical timestamped BirdNET detections; visible
threshold used everywhere and recorded; deterministic consolidation; names,
confidence, counts and timing; correct metrics on fixtures; event click seeks
audio; CSV and JSON export; no fake map point; responsive light/dark UI;
deterministic output; provenance in JSON; never "individuals"; experimental
models only behind a badge and flag; temp cleanup; tests, build and basic a11y
pass.

## 11. Historical pitfalls to avoid

Two metric pipelines, schema drift, fake Champaign location, Tailwind installed
twice, Create React App, registry class/instance confusion, OpenSoundscape API
churn, file-path assumptions, whole-clip pseudo-events, silently ignored model
parameter, threshold inconsistency (0.3/0.5/0.6), giant spinner, label-wrapped
file button, run-directory confusion, port confusion, FFmpeg gaps, no cleanup,
unverified celebratory claims.

## 12. Out of scope for the first release

Custom hardware, live streaming, native apps, abundance, certification,
foundation-model training, bats/ultrasound, rodent or large-mammal ID, public
audio library, social features, generative conclusions, causal analysis.

## 13. Open product decisions (defaults chosen are in docs/DECISIONS.md)

Retention; auth model; max duration/size; BirdNET license for commercial use;
raw detections in UI; slider recompute location; speech detection level; pilot
geography; consent for model improvement.

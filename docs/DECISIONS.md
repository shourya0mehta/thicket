# Decision log

Choices made during the September 2026 rebuild. Each entry says what was chosen, why, and what would change it. Product questions from the spec (section 32) come first, with the conservative default Thicket ships with.

## Open product questions and the defaults chosen

| # | Question | Default shipped | Why | Revisit when |
|---|---|---|---|---|
| 1 | Are recordings retained? | No. Audio is deleted as soon as the analysis finishes (`RETAIN_AUDIO=false`); temp folders are removed on success and on failure, and a janitor clears anything older than an hour. A preview ("Generate spectrogram") keeps its upload for `PREVIEW_TTL_MINUTES` so an analysis can reuse it; once an analysis takes it, the preview's copy is deleted. Results, raw detections and the spectrogram image stay until the user deletes the analysis. | Field audio can capture voices. Keeping nothing by default is the only choice that needs no consent process. | A pilot agreement covers retention and access. |
| 2 | Anonymous, magic link, or invited? | Single user, local, no auth. | The first pilot runs on a laptop or a private instance. Auth is only useful once results are stored for more than one person. | Before any shared hosted instance. |
| 3 | Max file size and duration | 20 MB in the browser, 50 MB and 10 minutes on the server, 1 second minimum. | BirdNET runs about 25 windows per second on 2 vCPU, so 10 minutes is roughly 10 seconds of inference; larger files belong in batch ingestion. | Batch ingestion or a GPU host. |
| 4 | BirdNET package, version, license | BirdNET GLOBAL 6K v2.4 TFLite (sha256 `55f3e405...`), weights taken from the pinned `birdnetlib==0.18.1` wheel, run with `ai-edge-litert`. | Pip-installable, pinned by hash, no network download at runtime, runs on Linux and Apple Silicon. The weights are CC BY-NC-SA 4.0: fine for a non-commercial pilot, a license from the BirdNET team is needed for paid use. | Any commercial pilot. |
| 5 | Raw detections in the normal UI? | No. The UI shows events; raw windows are in the JSON export and the Methods tab shows the counts. | Windows are an implementation detail and invite double counting. | Reviewers ask for window-level audit in the UI. |
| 6 | Slider recompute: client or server? | Server. The API stores every window above the 0.10 floor and `GET /analyses/{id}?threshold=x` rebuilds events, species and metrics with the same code that produced the original result. | One implementation of the science, so the slider can never disagree with the export. The response always states the threshold it used. | Offline or very large analyses where round trips hurt. |
| 7 | Speech and privacy detection | BirdNET's `Human vocal` label at 0.5 or above in any window sets `speech_detected` and adds a privacy note. Human sounds never count as species. | Cheap, already computed, and errs toward warning. It is a flag, not a redaction tool. | Before recordings from public places or near homes. |
| 8 | Pilot geography and species | Northeastern and Midwestern US (Ithaca farm pilot; historical Champaign data). The frog and insect label set is 17 anurans and 20 Orthoptera and cicadas from that range. | Matches the active pilot and the species BirdNET does not cover (cicadas, leopard frogs, Blanchard's cricket frog). | A new pilot region. |
| 9 | Using audio and corrections to improve models | Not allowed by default. Nothing leaves the machine; there is no telemetry. | Requires explicit consent terms first. | A signed data agreement. |

## Science and product rules

* **Events, not individuals.** Consolidated events are the unit of every metric. Words like individuals, population and abundance do not appear in the UI or exports.
* **Merge gap 1.0 s**, configurable, recorded in every result. Windows exactly one gap apart merge.
* **Ingestion floor 0.10, default decision threshold 0.60.** The floor is the lowest threshold the slider can reach; anything lower would need a re-run, and the API says so instead of silently clamping.
* **Metrics exclude**: human, noise, engine, siren, dog and environmental labels; reviewer-rejected events; birds flagged unlikely for the place and week. All are still listed.
* **Range and season filter only for birds.** BirdNET's meta model was trained on eBird data and returns about 0.00002 for every frog and insect label (for example Spring Peeper in Ithaca in May). Applying it to non-birds would delete every frog and insect detection, so those stay `unknown`.
* **No fallback location.** Missing coordinates mean no map and no range check, and the analysis says so.
* **Combined mode** gives each adapter its own model run id and never deduplicates across runs. If two runs name the same species, the species table merges them by scientific name while each event keeps its run id.
* **Experimental models** are off by default, need an environment flag on the server and another in the frontend, and carry a badge and a warning in every result.

## Engineering choices and deviations from the spec's suggestions

* **Package name `thicket`** instead of `app`, so `ml/` scripts can import the same BirdNET runtime and audio decoder without a generic top-level name.
* **Embeddings without a second model.** The stock BirdNET TFLite graph only outputs logits, and with the XNNPACK delegate intermediate tensors cannot be read. Thicket rewrites the flatbuffer once so the graph also outputs the 1024-d `GLOBAL_AVG_POOL` tensor, caches it by source hash, and keeps XNNPACK (about 10 times faster than preserving all tensors).
* **SQLite and local disk** behind repository and storage interfaces, with Postgres-compatible types. Events are derived on read, so the database only stores raw windows, reviews and provenance.
* **Deterministic event ids** (hash of analysis, run, species, start, end), and **reviews that follow windows**: a review stores the raw windows of the event it was made on. Windows of a rejected or corrected event are set aside before consolidation at every threshold and listed as that event, so a call rejected at 0.60 does not return merged with weaker windows at 0.10; windows nobody reviewed form their own unreviewed events. An acceptance carries over only to events whose windows are all inside it. Reviews saved before database schema 2 have no window list and still apply by event id.
* **`counted_in_metrics` on every event row and CSV line** marks the counted set, so exports and the UI never re-derive the rule. A corrected event names the species it counts under and keeps the model's label in `detected_*`.
* **Rate limits behind a proxy** key on `CLIENT_IP_HEADER` (`Fly-Client-IP` on Fly; the last `X-Forwarded-For` entry on Render). `FORWARDED_ALLOW_IPS="*"` is never used: uvicorn would then take the left end of `X-Forwarded-For`, which any client can set.
* **Tailwind v3, Vite, React 18.** One frontend root, one lockfile. Vitest 3 because Vitest 4 broke npm's installer here; Playwright pinned to the Chromium build available in CI images.
* **Hand-built SVG charts** instead of a chart library, so they theme cleanly, stay small and carry `title`/`desc` and a hidden data table for screen readers.
* **Hash routing** so the static demo works on GitHub Pages without server rewrites.
* **Spectrogram level reference from 1 kHz and up.** In many field recordings most energy is distant rumble below 200 Hz; using the whole band as the reference pushed calls into the dark end of the colormap.

## Things that happened during the build

* The build sandbox could not reach iNaturalist, Zenodo, xeno-canto or Hugging Face, and pushing to GitHub from it was not possible. The iNaturalist dataset and frog and insect training therefore live in a GitHub Actions workflow that runs once the repo is on GitHub.
* A soundscape QC head was trained instead, on ESC-50, because it is reachable, has proper source-disjoint folds, and fills a real gap in the spec (audio QC).

## Platform

Choices made while building the multi-tenant backend (October 2026). The contract is `backend/thicket/api/platform_schemas.py` and `docs/PLATFORM_API.md`; nothing in the schema module was renamed or removed, and no model fields were added. `ErrorCode` gained `unauthenticated`, `forbidden` and `conflict` (additive, `SCHEMA_VERSION` 1.3.0).

### Accounts, sessions and tenancy

* **Stateless signed cookies plus a revocation list** instead of a sessions table. The cookie is `{sid, uid, iat}` signed with itsdangerous, 30 days, re-issued on use once an hour old. Logout writes the `sid` to `revoked_sessions`, pruned nightly once the cookie would have expired anyway. No database write per request.
* **Google sign-in is hand-rolled with httpx and PyJWT**, not authlib: about 150 lines, every check visible (PKCE S256, `state` and `nonce` in a ten-minute signed cookie, RS256 against Google's JWKS, `aud`, `iss`, `exp`, `email_verified`, one JWKS refetch on an unknown `kid`). Tests swap the HTTP client for an `httpx.MockTransport`.
* **The local workspace has fixed ids** (`user_` and `org_` followed by 24 zeros) and exists in every auth mode, so a database can move between modes and an upgraded single-user database keeps pointing at it. The local user can never sign in by cookie, and the local workspace cannot be deleted.
* **CSRF header only when sign-in is on.** With `AUTH_MODE=disabled` there is no cookie to ride on, and requiring the header would break the existing single-analysis clients and tests.
* **404 for other organizations' resources, 403 for their org routes.** `/sites/{id}` and friends answer 404 to non-members so ids do not reveal existence; `/orgs/{org}/...` answers 403 for any well-formed org id the caller is not in (also for ids that do not exist, for the same reason).
* **Invite tokens** are stored as SHA-256 only, shown once (`accept_url`), valid 7 days, and only accepted by a signed-in user with the invited email. Access logs redact them from paths.
* **`POST /analyses` without `organization_id`** uses the caller's only organization; with several it asks for one (422), with none it refuses (403). The local owner always uses the local workspace.

### Data model

* **`recording_stats`** (one derived row per completed analysis: richness, events, Shannon, quality, species map, local date, hour bucket, ISO week) was added next to the two rollup tables the contract names. Alerts, recorder health, accumulation and the heatmap read it instead of re-deriving thousands of analyses. `site_day_stats` also stores quality counts and an hour-of-day activity map; `species_day_stats` stores first and last detection times.
* **Implicit and explicit sites.** Sites created from a recording's `site_name` are marked `auto_created` and are still removed with their last recording (the old behaviour). Sites created through the platform persist; deleting one with recordings is a 409.
* **Upgrades**: schema 3 adds nullable columns with `ALTER TABLE`, creates the new tables, the local workspace, attaches existing sites and recordings to it, and rebuilds rollups once at startup.
* **Local date without a timestamp** is the upload date, so untimed phone recordings still appear on the dashboard.

### Batch ingestion

* **One analysis pipeline.** Every batch file goes through `AnalysisService.create` and the same intake checks as a single upload.
* **Priority worker pool** replaces the thread pool: interactive analyses first, batch items (uploads and report rendering) only when nothing interactive waits and at most half the workers (rounded up) at once. Shutdown now joins workers for up to 30 s: a worker still inside matplotlib when the interpreter exits crashes the process.
* **No compression-ratio rule for zips.** Silent field recordings compress a thousandfold, so a ratio rule rejects real data. Caps are checked on the declared size and again while streaming; Python's zipfile also refuses to read past the declared size. Corrupt, encrypted or traversing members are skipped and listed.
* **Clocks.** AudioMoth-style names are UTC (or the fixed offset in `CONFIG.TXT`), Song Meter and ISO-style names are the recorder's local clock (the batch `timezone`), a registered recorder's make overrides the guess, naive GUANO timestamps are local. The CLI uses file modification times where the browser would send `last_modified`.
* **Recorders and deployments are created from device ids** (AudioMoth comment, GUANO serial, Song Meter prefix, `CONFIG.TXT`) so an SD card upload needs only a site. A deployment's start moves earlier when older files arrive.
* **Clock checks run per recorder**, and the out-of-order test only among files timed from metadata: a file named by its own timestamp is in name order by construction.

### Alerts and notifications

* **MAD floors** stop a perfectly flat history from alerting on noise: 1 species, 0.05 events per minute, 1 event per species, 0.01 high-band share, 50 Hz centroid. Drops are `warning` at 1.5 times the configured MAD multiple, `watch` below. Level drift is `warning` above 12 dB.
* **Inferred intervals need three intervals** before gap alerts or uptime figures use them.
* **Battery and temperature alerts fire on telemetry even without a registered recorder** (make `other`, 3.6 V), because the SD card often arrives before anyone registers the device.
* **Default preferences skip `info` alerts** (minimum severity `watch`), so speech flags and new species stay on the alerts page without filling inboxes. The local user and `.invalid` addresses are never emailed. A failed immediate email is queued for the daily digest. Daily digests go out every night, weekly ones on Mondays.

### Reports

* **The JSON bundle is the single source** for every number in the PDF; its SHA-256 is in every footer. Footers use two lines so the checksum and page number never overlap.
* **Wording that section 8 forbids is avoided even where section 6 suggests it.** The NRCS statement reads "Not a practice certification, a habitat evaluation score or a ranking assessment" (section 6(b) names the WHEG and CART tools, which section 8 bans), and the certification summary says "not the certifier's own bird index, ecological health index or field observation" rather than naming those indices. Non-bird species from BirdNET are shown as "unverified non-bird label".
* **Uncertainty** in the credit template is a percentile bootstrap of the per-recording mean (500 resamples, fixed seed, so rendering is deterministic).
* **Charts use matplotlib's Figure API** (no pyplot global state), safe on several worker threads.
* **Report fields are validated** against the template's field list: unknown names, invalid enum values and non-numeric numbers are 422, and file fields must be ids of images uploaded to the same organization.

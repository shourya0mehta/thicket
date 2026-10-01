# Platform API (v1)

Contract for the multi-tenant platform. Shapes live in
`backend/thicket/api/platform_schemas.py` and are exported to
`shared/api.schema.json`; the frontend generates its types from that file.
Everything here sits under `/api/v1`. Errors use the existing `ErrorResponse`
(`error_code`, `message`) plus two new codes: `unauthenticated` (401) and
`forbidden` (403).

## Tenancy and auth

| Method | Path | Role | Returns |
|---|---|---|---|
| GET | `/auth/config` | public | `AuthConfig` |
| GET | `/auth/google/start?next=` | public | 302 to Google (code flow with PKCE, `state` in a short-lived cookie) |
| GET | `/auth/google/callback` | public | sets the session cookie, 302 to `FRONTEND_URL/#/` (or `next`) |
| POST | `/auth/dev` | public, `AUTH_MODE=dev` only | body `DevLogin`, sets session, returns `Me` |
| POST | `/auth/logout` | signed in | 204 |
| GET | `/auth/me` | signed in | `Me` |
| GET | `/me/notifications?unread_only=&organization_id=` | signed in | `NotificationPage` (`unread` counts the same organization when one is given) |
| POST | `/me/notifications/read` | signed in | body `{ids: []}` or `{all: true}`, optional `organization_id` to limit it to one organization, 204 |
| GET / PUT | `/me/notification-prefs` | signed in | `NotificationPrefs` |
| GET | `/orgs` | signed in | `list[Organization]` the user belongs to |
| POST | `/orgs` | signed in | body `OrganizationCreate`, creator becomes owner, returns `Organization` |
| GET / PATCH | `/orgs/{org}` | viewer / manager | `Organization` |
| DELETE | `/orgs/{org}` | owner | 204, cascades |
| GET | `/orgs/{org}/members` | viewer | `list[Membership]` |
| PATCH | `/orgs/{org}/members/{user_id}` | owner | body `MembershipUpdate` |
| DELETE | `/orgs/{org}/members/{user_id}` | owner (or self) | 204 |
| POST | `/orgs/{org}/invites` | owner, manager | body `InviteCreate`, returns `Invite` with `accept_url` |
| GET | `/orgs/{org}/invites` | owner, manager | `list[Invite]` |
| DELETE | `/orgs/{org}/invites/{invite_id}` | owner, manager (owner invites: owner) | 204; the link stops working. 409 `conflict` once accepted, 404 for another organization's invite |
| POST | `/invites/{token}/accept` | signed in | returns `Organization` |

Session: HttpOnly, SameSite=Lax, signed with `SESSION_SECRET`, 30 days,
renewed on use. Mutating requests (POST, PATCH, PUT, DELETE) must carry the
header `X-Requested-With: thicket` (CSRF guard; the frontend client always
sets it). Google sign-in: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`PUBLIC_BASE_URL` (for the callback URL `${PUBLIC_BASE_URL}/api/v1/auth/google/callback`),
optional `ALLOWED_SIGNIN_DOMAINS`. With `AUTH_MODE=disabled` every request is
the implicit local owner of the implicit organization (`org_local`).

## Sites, recorders, deployments

| Method | Path | Role | Returns |
|---|---|---|---|
| GET / POST | `/orgs/{org}/sites` | viewer / manager | `list[Site]` / `Site` |
| GET / PATCH / DELETE | `/sites/{site_id}` | viewer / manager / manager | `Site` |
| GET | `/sites/{site_id}/accumulation` | viewer | `Accumulation` |
| GET / POST | `/orgs/{org}/recorders` | viewer / manager | `list[Recorder]` / `Recorder` |
| GET / PATCH / DELETE | `/recorders/{id}` | viewer / manager / manager | `Recorder` |
| GET | `/recorders/{id}/health?days=30` | viewer | `RecorderHealth` |
| GET / POST | `/orgs/{org}/deployments?active=` | viewer / manager | `list[Deployment]` / `Deployment` |
| GET / PATCH / DELETE | `/deployments/{id}` | viewer / manager / manager | `Deployment` |

Deleting a site or recorder with recordings is refused (409 `conflict`);
the client offers to archive by ending deployments instead.

## Recordings and batch ingestion

| Method | Path | Role | Returns |
|---|---|---|---|
| POST | `/orgs/{org}/uploads` | manager | multipart: `files[]` (audio, zip, Song Meter `*_Summary.txt`, AudioMoth `CONFIG.TXT`), `site_id`, `deployment_id?`, `recorder_id?`, `timezone`, `models`, `threshold`, `last_modified[]?` (ms epoch per file, same order), `captured_at_override?`. Returns 202 `BatchJob` |
| GET | `/uploads/{job_id}` | viewer | `BatchJob` (poll) |
| GET | `/orgs/{org}/uploads?limit=` | viewer | `list[BatchJob]` without items |
| GET | `/orgs/{org}/recordings?site_id&from&to&page&page_size&quality&species` | viewer | `RecordingPage` |
| GET | `/recordings/{id}` | viewer | `RecordingSummary` |
| DELETE | `/recordings/{id}` | manager | 204, removes analyses and assets |
| POST | `/analyses` (existing) | manager | now also accepts `organization_id`, `site_id`, `deployment_id`, `recorder_id`; with auth disabled it keeps working with none of them |

Timestamp parsing order: filename pattern, then file metadata (WAV comment
or GUANO), then the browser `last_modified`, then `captured_at_override`;
the result records `captured_at_source`. Supported filename patterns:
AudioMoth `20240514_053000.WAV` (UTC) and `<prefix>_20240514_053000.WAV`,
Song Meter `SMA12345_20240514_053000.wav` / `SMM01234_20240514_053000.wav`
(local time per the recorder's clock), ISO `2024-05-14T05-30-00`,
`2024-05-14 05.30.00`, `20240514T053000`, Voice Memos style `New Recording 7`
(no timestamp). AudioMoth WAV comments
(`Recorded at 05:30:00 14/05/2024 (UTC) by AudioMoth 24A1D5... at medium gain while battery was 4.0V and temperature was 12.3C.`)
yield telemetry; Song Meter summary rows match recordings by timestamp.

## Dashboard and seasonal series

| Method | Path | Role | Returns |
|---|---|---|---|
| GET | `/orgs/{org}/dashboard?from&to&site_id` | viewer | `Dashboard` (default: last 90 days) |
| GET | `/orgs/{org}/phenology?scientific_name&site_id&years=` | viewer | `Phenology` |
| GET | `/orgs/{org}/sites/compare?from&to` | viewer | `SiteComparison` |

Rollups come from two tables maintained after every completed analysis and
rebuilt nightly: `site_day_stats` (site, local date, recordings, minutes,
richness, events, events per minute, Shannon, usable fraction, indices) and
`species_day_stats` (site, local date, species, events, recordings with
detection, max confidence). Local date uses the organization timezone.
Metrics inside a day are computed from the union of counted events across
that day's analyses, each at its own recorded threshold.

## Alerts and notifications

| Method | Path | Role | Returns |
|---|---|---|---|
| GET | `/orgs/{org}/alerts?status&category&kind&site_id&recorder_id&page` | viewer | `AlertPage` |
| PATCH | `/alerts/{id}` | reviewer | body `AlertUpdate` |
| GET / PUT | `/orgs/{org}/alert-rules` | viewer / manager | `AlertRules` |
| POST | `/orgs/{org}/alerts/evaluate` | manager | runs the engine now, returns `AlertPage` of what is open |

The engine runs after each completed analysis for that site and recorder,
and nightly for gaps and digests. Alerts are deduplicated by
(kind, site, recorder, species): a repeat updates `last_seen_at` and
`occurrences` instead of opening a new row. Ecology alerts do not fire until
`min_baseline_recordings` comparable recordings exist (same site, same hour
bucket: dawn, day, dusk, night; same season window of plus or minus 21 days
of the same date across years, falling back to the last 8 weeks). Baselines use the
median and MAD, never the mean. Every alert's `detail` states the observed
value, the baseline and the sample size in plain words.

Recorder health checks per deployment: `muffled_audio` (high-band fraction
and spectral centroid below baseline by more than 3 MAD for
`consecutive_recordings`), `level_drift` (RMS more than 6 dB from the
deployment median for the same hour bucket), `recording_gap` (a gap between consecutive
recordings of a deployment, counted only inside its recording window, longer
than `gap_multiplier` times the median interval and at least `gap_min_hours`;
never measured from the current time), `upload_overdue` (`info`/`watch`: no
upload for twice the deployment's median upload spacing, once it has at
least three),
`clipping_increase`, `channel_imbalance` (stereo, one channel more than 12 dB
below the other), `dc_offset`, `battery_low` (per make threshold),
`temperature_extreme`, `clock_suspect` (timestamps not monotonic within a
batch, duplicates, or in the future), `schedule_deviation` (recordings far
from the expected interval when one is set, counted inside the recording
window). The **recording window** is the set of local hours a deployment
records in: `HH:MM-HH:MM` ranges named in `schedule_description`, otherwise
every local hour its recordings start in or run through. Recorder health
covers the `days` up to the recorder's latest recording; `uptime_fraction_7d`
compares the recordings in the 7 days up to the latest one with the number
the window expects.

Notifications: each alert creates an in-app notification for every member
whose preferences match; email goes out immediately or in a daily/weekly
digest when `SMTP_HOST` (or `RESEND_API_KEY`) is configured, otherwise it is
written to `var/outbox/` in development. Email never includes audio.

## Reports

| Method | Path | Role | Returns |
|---|---|---|---|
| GET | `/reports/templates` | signed in | `ReportTemplates` (fields from `docs/REPORTING.md`) |
| POST | `/orgs/{org}/reports` | reviewer | body `ReportCreate`, 202 `Report` |
| GET | `/orgs/{org}/reports` | viewer | `ReportList` |
| GET | `/reports/{id}` | viewer | `Report` (poll) |
| GET | `/reports/{id}.pdf` | viewer | PDF |
| GET | `/reports/{id}.json` | viewer | the data bundle the PDF was rendered from |
| DELETE | `/reports/{id}` | manager | 204 |
| POST | `/orgs/{org}/files` | manager | multipart image (png/jpg, 10 MB), returns `UploadedFile`; used for deployment photos and tract maps |
| GET | `/files/{id}` | viewer | the file |

Rendering: ReportLab plus matplotlib (Agg), no system dependencies,
deterministic for the same bundle. Every page footer prints the report id,
software version, platform schema version and the SHA-256 of the JSON
bundle. Section 8 of `docs/REPORTING.md` lists wording the renderer must
never produce; a unit test greps the PDF text for it.

## Settings (environment)

```
AUTH_MODE=disabled|dev|google
SESSION_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
PUBLIC_BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173
ALLOWED_SIGNIN_DOMAINS=
ALLOW_UNAUTHENTICATED=false   # production refuses AUTH_MODE=disabled without it
SMTP_HOST= SMTP_PORT=587 SMTP_USER= SMTP_PASSWORD= EMAIL_FROM=
RESEND_API_KEY=
ALERTS_ENABLED=true
NIGHTLY_JOBS_HOUR_UTC=6
MAX_BATCH_FILES=200
MAX_BATCH_BYTES=2147483648
REPORT_LOGO_PATH=
```

## Implementation notes (backend, October 2026)

The backend implements every route above. Where it had to pick a detail the
tables leave open, or deviates, it is listed here with the reason. No model
in `platform_schemas.py` was renamed, removed or given new fields.

* **Error codes**: `ErrorCode` gained `unauthenticated` (401), `forbidden`
  (403) and `conflict` (409, used for deletes refused while recordings exist,
  the last owner, used or expired invites). `SCHEMA_VERSION` is 1.3.0; the
  frontend's generated types need a regeneration for the new codes.
* **Status codes**: creates return 201 (`POST /orgs`, sites, recorders,
  deployments, invites, files); uploads and reports return 202 with a
  `Location` header to poll.
* **Foreign ids**: a resource addressed by id (`/sites/{id}`,
  `/recordings/{id}`, `/analyses/{id}`, `/events/{id}`, `/reports/{id}`...) in
  an organization the caller does not belong to answers 404, so ids do not
  reveal existence. `/orgs/{org}/...` answers 403 to non-members.
* **CSRF header**: required on mutating requests only when sign-in is on
  (`dev` or `google`). With `AUTH_MODE=disabled` there is no session cookie and
  the header is not needed, so existing single-analysis clients keep working.
* **Invites**: `accept_url` is `FRONTEND_URL/#/invite/<token>`, valid 7 days,
  and only accepted by a signed-in user whose email matches the invite (422
  otherwise). Only an owner may invite another owner.
* **Members**: `DELETE /orgs/{org}/members/{user_id}` by any member for
  themselves (leave); the last owner can neither leave nor be demoted (409).
* **`POST /analyses`**: without `organization_id` the caller's only
  organization is used; 422 when they have several, 403 when they have none.
  `site_id`, `deployment_id` and `recorder_id` must belong to that
  organization (422 otherwise). Reviews (`PATCH /events/{id}`) need the
  reviewer role.
* **`POST /orgs/{org}/uploads`**: `timezone` is required; `site_id` is
  required unless `deployment_id` names one. Files may also be sent under
  the field name `files[]` or `file`. Unknown form fields are rejected.
  Recorders and deployments are created from device ids when none are given.
  Corrupt or unsafe zip members are skipped and listed in
  `BatchJob.settings.skipped_entries`.
* **`GET /orgs/{org}/recordings`** also accepts `recorder_id` and
  `deployment_id`; `from` and `to` are ISO dates or date-times (naive values
  in the organization's time zone); `page_size` up to 200. `species` matches a
  scientific or common name.
* **`GET /orgs/{org}/alerts`** also accepts `page_size` (up to 200).
  `PATCH /alerts/{id}` with `snoozed` needs a future `snoozed_until`;
  acknowledging, resolving or snoozing records `acknowledged_by`, reopening
  clears it.
* **`clock_suspect`** is evaluated per recorder within one upload; the order
  test uses files whose time came from file metadata.
* **`recording_gap`** with an inferred interval needs at least three
  intervals; with a declared `expected_interval_minutes` it does not.
* **Dashboards**: `from` must not be after `to`, and a period may span at most
  five years.
* **Report fields** are validated against the template: unknown names, invalid
  enum values and non-numbers are 422; `file` fields take ids returned by
  `POST /orgs/{org}/files` in the same organization. A period without
  recordings renders a "No recordings in this period" page (status `ready`).
* **Extra table**: `recording_stats` (one derived row per completed
  analysis) sits next to `site_day_stats` and `species_day_stats`.
* **CLI**: `python -m thicket.cli ingest DIR --site NAME [--recorder LABEL]
  [--make MAKE] [--timezone TZ]` and `python -m thicket.cli nightly` use the
  same services on the configured data dir and the local workspace.

## Changes after the review (October 2026)

* **Production needs sign-in.** `ENVIRONMENT=production` with
  `AUTH_MODE=disabled` refuses to start unless `ALLOW_UNAUTHENTICATED=true`.
  `fly.toml` and `render.yaml` set `AUTH_MODE=google` and list the required
  secrets.
* **Invite revocation**: `DELETE /orgs/{org}/invites/{invite_id}`.
* **Notifications per organization**: `organization_id` on
  `GET /me/notifications` and on `POST /me/notifications/read`; the web app
  marks only the open organization's notifications read.
* **`AlertKind.upload_overdue`** (additive). `recording_gap` now only measures
  holes between consecutive recordings inside the recording window.
* **Database schema 4**: `alerts.open_key` with a unique index, one unresolved
  alert per (organization, kind, site, recorder, species).
* **CLI**: `python -m thicket.cli adopt-local --org ORG_ID | --email EMAIL`
  moves the local workspace into an organization; `ingest --org ORG_ID`.

# Thicket frontend

The Thicket web app. Against a platform backend it is a multi-tenant monitoring product for
farms and land stewards: sign-in, organizations, a farm dashboard, sites, batch uploads,
recording history, seasonal views, an alerts inbox, recorder health and a report builder.
Against an older backend (no `/auth/config`) it is the original single-recording workspace:
upload a field recording, follow the analysis stage by stage, then review species detection
events, detection-derived metrics, a timeline, a map (only with real coordinates), provenance and
CSV/JSON exports. That workspace is also the per-recording view inside the platform.

Vite, React 18, TypeScript (strict), Tailwind CSS 3, Leaflet (react-leaflet), hand-built SVG
charts. Tests use Vitest with Testing Library, and Playwright with mocked API routes.

## Quick start

Requirements: Node 20.19 or newer (CI uses Node 22) and npm.

```bash
cd frontend
npm ci
npm run dev          # http://localhost:5173
```

Run the backend on port 8000 in another terminal (see `backend/README.md`). The Vite dev server
proxies `/api` to `http://localhost:8000`, so the browser only talks to one origin. Without a
backend the app still loads and explains that the server cannot be reached.

To serve a production build from the backend, run `npm run build` and point the backend's
`SERVE_FRONTEND_DIR` at `frontend/dist`.

## Routes

Hash routing, so deep links work on static hosting. Query parameters after the path carry
filters (`?period=30`, `?site_id=...`, `?status=open`).

| Route                                        | Page                                                                                                                                                                                                                                       |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `#/`                                         | Sign-in when needed; then the organization list, straight to the only organization, or the last one used; "Create your farm or project" when there is none                                                                                 |
| `#/orgs/:org`                                | Dashboard: period (30, 90, 365 days or custom) and site filters, KPI tiles, richness by day with a rolling median and MAD band, activity heatmap, species by presence, taxon split, soundscape small multiples, audio quality, open alerts |
| `#/orgs/:org/sites`                          | Site cards with health, create form with coordinate validation, comparison table                                                                                                                                                           |
| `#/orgs/:org/sites/:site`                    | Site facts, map (only with coordinates), deployments, richness by day, species accumulation, phenology ribbon, recordings, open alerts, edit and delete                                                                                    |
| `#/orgs/:org/recordings`                     | Paginated table filtered by site, dates, audio quality and species                                                                                                                                                                         |
| `#/orgs/:org/recordings/:id`                 | Recording facts and telemetry, then the existing results view for its analysis                                                                                                                                                             |
| `#/orgs/:org/upload`                         | Batch upload with a client-side timestamp preview per file, site, deployment, time zone, model and threshold; upload progress and job polling                                                                                              |
| `#/orgs/:org/analyze`                        | The single-recording workspace, filed under a chosen site                                                                                                                                                                                  |
| `#/orgs/:org/alerts`                         | Inbox grouped by ecology, audio quality and recorder; acknowledge, resolve, snooze, reopen                                                                                                                                                 |
| `#/orgs/:org/recorders` and `/recorders/:id` | Recorder list; health checks, battery, temperature, level and high-band fraction against the deployment band, clipping, gaps, deployments                                                                                                  |
| `#/orgs/:org/reports` and `/reports/new`     | Report list with downloads; four-step wizard generated from `ReportTemplate.fields`                                                                                                                                                        |
| `#/orgs/:org/settings`                       | Organization details, members and roles, invitations, priority species, alert rules, notification preferences                                                                                                                              |
| `#/invite/:token`                            | Accept an invitation                                                                                                                                                                                                                       |
| `#/methods`                                  | Methods and limits                                                                                                                                                                                                                         |
| `#/history`                                  | Local history, standalone or `AUTH_MODE=disabled` only                                                                                                                                                                                     |

## Auth modes

The app asks `GET /auth/config` first.

- `google`: a "Continue with Google" button links to `sign_in_url` with `next` set to the page
  the user wanted.
- `dev`: an email and name form posts to `/auth/dev`. Any email works; development only.
- `disabled`: no sign-in; every request acts as the implicit owner of `org_local`.
- `/auth/config` answers 404: an older backend, so the standalone workspace is shown.

Any 401 from any request shows the sign-in page. A 403 is shown as "Your role does not allow
this". Mutating requests always carry `X-Requested-With: thicket`. Roles gate the interface:
viewers see no edit controls, reviewers can act on alerts, review events and build reports,
managers manage sites, recorders, uploads and rules, owners manage members. The last
organization opened is kept in `localStorage` (`thicket-last-org`).

## Environment variables

Copy `.env.example` to `.env.local` to override. All variables are optional.

| Variable                          | Default                 | Purpose                                                                    |
| --------------------------------- | ----------------------- | -------------------------------------------------------------------------- |
| `VITE_API_BASE_URL`               | empty (same origin)     | Base URL of the API. Requests go to `${VITE_API_BASE_URL}/api/v1/...`.     |
| `VITE_ENABLE_EXPERIMENTAL_MODELS` | `false`                 | Show experimental models (always badged) and the Combined option.          |
| `VITE_DEMO_MODE`                  | `false`                 | Static demo: no uploads, loads precomputed analyses from `public/demo/`.   |
| `VITE_BASE_PATH`                  | `/`                     | Base path the app is served from, for example `/thicket/` on GitHub Pages. |
| `VITE_DEV_API_PROXY`              | `http://localhost:8000` | Dev and preview servers only: where `/api` is proxied.                     |

## Scripts

| Script                      | What it does                                                        |
| --------------------------- | ------------------------------------------------------------------- |
| `npm run dev`               | Dev server on :5173 with the `/api` proxy.                          |
| `npm run build`             | Type-check (`tsc -b`) and build to `dist/`.                         |
| `npm run preview`           | Serve `dist/` on :4173 (with the same proxy).                       |
| `npm run lint`              | ESLint (typed rules, React hooks, jsx-a11y), zero warnings allowed. |
| `npm run typecheck`         | `tsc -b` for the app and the Node/e2e project.                      |
| `npm test`                  | Vitest unit and component tests (jsdom).                            |
| `npm run test:e2e`          | Playwright end-to-end tests with mocked API routes.                 |
| `npm run screenshots`       | Capture reference screenshots into `screenshots/` (mocked data).    |
| `npm run gen:types`         | Regenerate `src/api/generated.ts` from `../shared/api.schema.json`. |
| `npm run check:types-fresh` | Fail if `src/api/generated.ts` is out of date with the schema.      |
| `npm run format`            | Prettier on the whole frontend.                                     |

## API types

`shared/api.schema.json` is exported from `backend/thicket/api/schemas.py` and is the only
source of response shapes. `npm run gen:types` turns it into `src/api/generated.ts` with
`json-schema-to-typescript`; the file is committed and must not be edited by hand.
`src/api/types.ts` only re-exports it plus a few derived helpers. After the backend changes the
schema, run `npm run gen:types`, fix any type errors, and commit both files.
`npm run check:types-fresh` fails when they drift.

## Tests

```bash
npm test                        # unit and component tests
npx playwright test             # e2e (mocked API)
npm run screenshots             # opt-in visual reference captures
```

Playwright starts three Vite dev servers, one per build flag combination: :5173 (defaults),
:5174 (experimental models enabled) and :5175 (demo mode). All API calls are answered by
`page.route` mocks built from the typed fixtures in `src/test/fixtures/`, so no backend is
needed. The single-recording suite covers upload, preview, stage list, polling, threshold
refetch, event seeking, exports, the no-detections result, a backend 500 with retry, the
experimental and disabled model states, demo mode, keyboard access, mobile overflow and an axe
scan of the results view in light and dark themes.

The platform routes are answered by one in-memory server,
`src/test/fixtures/platformServer.ts`, shared by the Vitest fake backend
(`installFakeBackend({ platform: {...} })`) and the Playwright mock (`e2e/support/mockPlatform.ts`,
which also serves a synthetic map tile so no tiles are fetched). `e2e/platform.spec.ts` runs dev
sign-in, create an organization, add a site, batch upload, dashboard, acknowledge an alert, the
report wizard to its download links; an axe scan of the dashboard, alerts, recorder and site
pages in both themes; phone-width overflow on every platform page; and Google sign-in. The demo
project also checks the read-only demo dashboard.

The browser is expected under `PLAYWRIGHT_BROWSERS_PATH` for the pinned `@playwright/test`
version (Chromium build 1194). If your installed browser differs, point
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` at a Chromium binary instead of downloading a new one.

A full-stack smoke test against a real backend is skipped by default:

```bash
# backend running on :8000 with BirdNET ready
E2E_REAL_BACKEND=1 npx playwright test --project=real-backend
```

It uploads `backend/tests/fixtures/soundscape_30s.flac` (override with `E2E_AUDIO_FIXTURE`),
waits for the analysis, checks the CSV export and a threshold change.

## Demo mode (GitHub Pages)

`VITE_DEMO_MODE=true` builds a static site with no uploads. It shows a demo banner and reads
precomputed files relative to the base path:

```
public/demo/
  index.json                  { "analyses": [ { "id", "title", "description", "attribution", "license" } ] }
  <id>/threshold-0.10.json    full Analysis JSON at a 0.10 decision threshold
  <id>/threshold-0.15.json
  ...                         one file per 0.05 step, two decimals in the name
  <id>/threshold-0.95.json
  <id>/spectrogram.png        covers 0 to duration seconds, spectrogram_min_hz to spectrogram_max_hz
  <id>/audio.mp3
```

If `public/demo/platform.json` also exists, the demo opens a read-only dashboard instead, and
recordings whose `analysis_id` matches a demo analysis id open that analysis. Every write is
refused with a friendly message and nothing calls an API. Only `organization`, `dashboard`,
`sites`, `alerts` and `recorders` are required; the rest fill the other pages when present:

```
public/demo/platform.json
  organization        Organization
  user                User (optional; a placeholder visitor otherwise)
  dashboard           Dashboard (served for every period; a site filter narrows it in the browser)
  sites               Site[]
  alerts              Alert[]
  recorders           Recorder[]
  recorder_health     { "<recorder id>": RecorderHealth }
  deployments         Deployment[]
  recordings          RecordingSummary[]
  accumulation        { "<site id>": Accumulation }
  phenology           Phenology[] (one per species)
  site_comparison     SiteComparison
  reports             Report[]
  report_templates    ReportTemplates
  alert_rules         AlertRules
```

`buildDemoPlatformFile()` in `src/test/fixtures/platform.ts` builds a complete example.

The threshold slider loads the matching file. Exports are generated in the browser from the
loaded analysis with the same CSV columns, float formatting and file names as the backend, and
the JSON export carries the same `export_metadata`. Review actions are disabled. Demo files are
generated by a separate process; none are committed here. `.github/workflows/pages.yml` builds
with `VITE_DEMO_MODE=true` and `VITE_BASE_PATH=/<repo>/` and copies `index.html` to `404.html`.
Routing uses the URL hash (`#/history`, `#/methods`), so deep links work on static hosting.

## How the app behaves

- **One hidden file input** opened by the Choose file button through a ref; never a button
  inside a label. Client guard: `.wav .mp3 .m4a .flac`, 20 MB. A new file clears the preview,
  results, errors and progress; metadata is kept only when Keep is ticked.
- **Generate spectrogram** uploads once to `POST /previews`; Run analysis then reuses the upload
  with `preview_id` (and falls back to sending the file if the preview expired).
- **Stages** come from `analysis.stage`, polled every 700 ms, plus local upload progress.
- **Threshold**: 0.60 by default, 0.05 steps from the analysis's ingestion floor to 0.95. Changes
  are debounced (250 ms) and refetch `GET /analyses/{id}?threshold=`; every view, including the
  exports, renders from the returned analysis and shows the applied threshold.
- **Review**: `PATCH /events/{id}`, then refetch at the current threshold.
- **Other sounds** (human, domestic, mechanical, environmental, noise) and species flagged
  unlikely for the place and season are listed separately. Which section an event goes in comes
  from the server's `counted_in_metrics` flag; the frontend never re-derives the counting rule.
  A corrected event shows under the species it counts as, with "Detected as" the model's label.
- **Map** only when latitude and longitude are numbers in range, the same rule as the backend
  (0,0 is a valid location; missing coordinates are null). There is never a fallback point.
- **Previews** are deleted on the server (`DELETE /previews/{id}`, fire and forget) on Clear,
  when another file replaces a previewed one, and when an analysis is opened from history.
- **Audio** plays from the local file (object URL, revoked on reset) or `assets.audio_url`.
- **History**: the last three summaries in `localStorage` (`thicket-history`); opening one reloads
  it from the server and removes it if the server no longer has it.
- **Theme**: class-based, stored as `thicket-theme`, system preference until the user chooses.

## Structure

```
src/
  api/          generated.ts (from the schema), client (fetch + XHR upload, CSRF header, 401
                handling), platform.ts (typed platform routes), errors, polling
  platform/     PlatformProvider (auth config, session, data source), OrgProvider (org, sites,
                recorders, unread count), PlatformApi interface (HTTP or static demo)
  state/        workspace reducer and hook (upload, poll, threshold, review), playback context
  components/   charts (time series with baseline band, heatmap, ranked bars, stacked bar,
                accumulation, phenology ribbon, gaps, sparkline), shell (app shell, plain
                layout), platform (pills, forms, tables, filters), intake, progress, results, ui
  pages/        platform/ (sign-in, organizations, dashboard, sites, recordings, upload,
                alerts, recorders, reports, settings, invite), workspace, history, methods
  lib/          routes, filenames (timestamp patterns), stats (median, MAD), dates, dashboard
                series, report fields, roles, labels, species names, demo loaders, formatting
  test/         setup, fake backend, typed fixtures, platform server, flow and platform tests
e2e/            Playwright specs and route mocks (synthetic spectrogram, WAV and map tile)
scripts/        gen-types.mjs
```

## Design notes

Deep forest greens (`forest-50` to `forest-950`, primary `forest-600 #377157`) on warm paper in
light mode and deep green-charcoal in dark mode, Inter (self-hosted via `@fontsource-variable`),
1.25rem panel radius, thin borders and soft shadows, no glow effects. Semantic colors are CSS
variables in `src/index.css`, so both themes share one set of class names. Text contrast meets
WCAG AA in both themes. Motion is limited to short fades and respects `prefers-reduced-motion`.
Charts are SVG with titles, descriptions and visually hidden data tables; taxa are shown with
icons and labels, never by color alone.

Platform charts follow the same rules: one hue (the forest mark color) for magnitude, light to
dark; four fixed taxon slots for identity (bird, amphibian, insect, mammal as CSS variables per
theme, validated for color vision deficiency with legends and icons as the second channel);
ok, warn and danger only for state, always with an icon and a label. Gridlines are solid
hairlines, marks are thin, values use tabular figures, and every chart answers hover and
keyboard focus with a tooltip that is never the only way to read a value. Richness baselines are
a 14-day rolling median plus or minus MAD computed in the browser and labelled as such; recorder
bands are the deployment median plus or minus MAD. Copy never calls counts individuals,
populations or abundance: they are detection events.

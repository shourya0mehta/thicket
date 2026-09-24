# Thicket frontend

The Thicket web app: upload a field recording, follow the analysis stage by stage, then review
species detection events, detection-derived metrics, a timeline, a map (only with real
coordinates), provenance and CSV/JSON exports.

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
needed. The suite covers upload, preview, stage list, polling, threshold refetch, event seeking,
exports, the no-detections result, a backend 500 with retry, the experimental and disabled
model states, demo mode, keyboard access, mobile overflow and an axe accessibility scan of the
results view in light and dark themes.

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
  api/          generated.ts (from the schema), client (fetch + XHR upload), errors, polling
  state/        workspace reducer and hook (upload, poll, threshold, review), playback context
  components/   intake, progress, results (spectrogram, charts, tables, timeline, map), ui kit
  pages/        workspace, history, methods
  lib/          formatting, validation, taxa, stages, CSV, demo loader, history, theme
  test/         setup, fake backend, typed fixtures, flow tests
e2e/            Playwright specs and route mocks (synthetic spectrogram and WAV)
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

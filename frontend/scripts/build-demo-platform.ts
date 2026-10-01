/**
 * Writes public/demo/platform.json, the sample farm that the static demo build
 * (VITE_DEMO_MODE=true on GitHub Pages or Vercel) shows as a read-only
 * dashboard with sites, alerts, recorders, phenology and reports.
 *
 *   npm run demo:platform               # 90 days ending today
 *   npm run demo:platform -- 2026-09-30 # 90 days ending on that date
 *
 * The data is synthetic (the same fixture the tests use) and the app labels it
 * as sample data. The first recording opens the bundled BirdNET example
 * soundscape so the drill-down from the dashboard works.
 */
import { writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildDemoPlatformFile } from '../src/test/fixtures/platform';

const DAY_MS = 86_400_000;
const WINDOW_DAYS = 90;
const DEMO_ANALYSIS_ID = 'birdnet-example-soundscape';

const arg = process.argv.slice(2).find((a) => /^\d{4}-\d{2}-\d{2}$/.test(a));
const end = arg ? new Date(`${arg}T00:00:00Z`) : new Date();
const to = end.toISOString().slice(0, 10);
const from = new Date(end.getTime() - (WINDOW_DAYS - 1) * DAY_MS).toISOString().slice(0, 10);

const file = buildDemoPlatformFile(from, to);
file.recordings = file.recordings.map((r, i) =>
  i === 0 ? { ...r, analysis_id: DEMO_ANALYSIS_ID } : { ...r, analysis_id: null },
);

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, '../public/demo/platform.json');
writeFileSync(out, `${JSON.stringify(file)}\n`);
process.stdout.write(`wrote ${out} (${from} to ${to})\n`);

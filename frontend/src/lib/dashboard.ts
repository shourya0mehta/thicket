import type { Dashboard, DayPoint, IndexPoint } from '../api/generated';
import { dateRange } from './dates';
import { rollingBaseline, type BaselineBand } from './stats';

export interface DaySeries {
  dates: string[];
  richness: Array<number | null>;
  recordings: number[];
  minutes: number[];
  events: number[];
  eventsPerMinute: Array<number | null>;
  /** Rolling median plus or minus MAD of richness, computed here from the series. */
  baseline: BaselineBand[];
  /** True when more than one site contributed rows for the same date. */
  multiSite: boolean;
}

/**
 * One row per calendar day across the period. Missing days become gaps
 * (null richness, zero recordings). When the server returns one row per site
 * and day, recordings, minutes and events add up and richness takes the
 * largest site value for that day, which the chart note says.
 */
export function buildDaySeries(
  points: DayPoint[],
  periodStart: string,
  periodEnd: string,
): DaySeries {
  const byDate = new Map<string, { rows: DayPoint[] }>();
  for (const p of points) {
    const key = p.date.slice(0, 10);
    const entry = byDate.get(key) ?? { rows: [] };
    entry.rows.push(p);
    byDate.set(key, entry);
  }
  let dates = dateRange(periodStart.slice(0, 10), periodEnd.slice(0, 10));
  if (!dates.length) dates = [...byDate.keys()].sort();
  let multiSite = false;
  const richness: Array<number | null> = [];
  const recordings: number[] = [];
  const minutes: number[] = [];
  const events: number[] = [];
  const eventsPerMinute: Array<number | null> = [];
  for (const date of dates) {
    const rows = byDate.get(date)?.rows ?? [];
    if (rows.length > 1) multiSite = true;
    const rec = rows.reduce((a, r) => a + r.recordings, 0);
    const min = rows.reduce((a, r) => a + r.minutes, 0);
    const ev = rows.reduce((a, r) => a + r.detection_events, 0);
    recordings.push(rec);
    minutes.push(min);
    events.push(ev);
    richness.push(rows.length ? Math.max(...rows.map((r) => r.species_richness)) : null);
    eventsPerMinute.push(rows.length && min > 0 ? ev / min : rows.length ? 0 : null);
  }
  return {
    dates,
    richness,
    recordings,
    minutes,
    events,
    eventsPerMinute,
    baseline: rollingBaseline(richness, 14, 5),
    multiSite,
  };
}

/** Folds a daily series into about `buckets` sums or maxima for a sparkline. */
export function bucketize(
  values: Array<number | null>,
  buckets = 12,
  mode: 'sum' | 'max' = 'sum',
): Array<number | null> {
  if (values.length <= buckets) return values;
  const size = values.length / buckets;
  const out: Array<number | null> = [];
  for (let b = 0; b < buckets; b += 1) {
    const slice = values
      .slice(Math.floor(b * size), Math.floor((b + 1) * size))
      .filter((v): v is number => v !== null);
    if (!slice.length) {
      out.push(null);
      continue;
    }
    out.push(mode === 'sum' ? slice.reduce((a, v) => a + v, 0) : Math.max(...slice));
  }
  return out;
}

export type IndexKey =
  'acoustic_complexity_index' | 'acoustic_diversity_index' | 'bioacoustic_index' | 'ndsi';

export const INDEX_META: Array<{
  key: IndexKey;
  label: string;
  short: string;
  digits: number;
  min: number | null;
}> = [
  {
    key: 'acoustic_complexity_index',
    label: 'Acoustic complexity',
    short: 'ACI',
    digits: 0,
    min: null,
  },
  { key: 'acoustic_diversity_index', label: 'Acoustic diversity', short: 'ADI', digits: 2, min: 0 },
  { key: 'bioacoustic_index', label: 'Bioacoustic index', short: 'BI', digits: 1, min: 0 },
  { key: 'ndsi', label: 'Soundscape difference', short: 'NDSI', digits: 2, min: null },
];

/** Per-day median of an index when several sites report the same day. */
export function indexSeries(
  points: IndexPoint[],
  dates: string[],
  key: IndexKey,
): Array<number | null> {
  const byDate = new Map<string, number[]>();
  for (const p of points) {
    const v = p[key];
    if (v == null || !Number.isFinite(v)) continue;
    const d = p.date.slice(0, 10);
    byDate.set(d, [...(byDate.get(d) ?? []), v]);
  }
  return dates.map((d) => {
    const vs = byDate.get(d);
    if (!vs?.length) return null;
    const sorted = vs.slice().sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
  });
}

export const QUALITY_ORDER = ['usable', 'usable_with_warnings', 'not_usable'] as const;

export function qualityCounts(dashboard: Dashboard): Array<{ key: string; count: number }> {
  const out: Array<{ key: string; count: number }> = QUALITY_ORDER.map((key) => ({
    key,
    count: dashboard.quality[key] ?? 0,
  }));
  for (const [key, count] of Object.entries(dashboard.quality)) {
    if (!(QUALITY_ORDER as readonly string[]).includes(key)) out.push({ key, count });
  }
  return out;
}

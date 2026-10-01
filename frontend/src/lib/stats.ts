/**
 * Small robust statistics for client-side chart annotations. Baselines in
 * Thicket use the median and MAD, never the mean (docs/PLATFORM_API.md).
 */

export function median(values: number[]): number | null {
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

/** Median absolute deviation (unscaled). */
export function mad(values: number[]): number | null {
  const m = median(values);
  if (m === null) return null;
  return median(values.map((v) => Math.abs(v - m)));
}

export interface BaselineBand {
  center: number | null;
  low: number | null;
  high: number | null;
}

/**
 * Rolling median plus or minus MAD, computed over a trailing window of points
 * (the current point included). Short windows return nulls until `minPoints`
 * values are available, so the band never pretends to know more than it does.
 */
export function rollingBaseline(
  values: Array<number | null>,
  window = 14,
  minPoints = 5,
): BaselineBand[] {
  return values.map((_, i) => {
    const slice = values
      .slice(Math.max(0, i - window + 1), i + 1)
      .filter((v): v is number => v !== null && Number.isFinite(v));
    if (slice.length < minPoints) return { center: null, low: null, high: null };
    const center = median(slice)!;
    const spread = mad(slice)!;
    return { center, low: Math.max(0, center - spread), high: center + spread };
  });
}

export function sum(values: number[]): number {
  return values.reduce((acc, v) => acc + (Number.isFinite(v) ? v : 0), 0);
}

export function maxOf(values: number[], fallback = 0): number {
  const finite = values.filter((v) => Number.isFinite(v));
  return finite.length ? Math.max(...finite) : fallback;
}

export function minOf(values: number[], fallback = 0): number {
  const finite = values.filter((v) => Number.isFinite(v));
  return finite.length ? Math.min(...finite) : fallback;
}

/** Evenly spaced "nice" ticks between min and max (inclusive-ish), at most maxTicks. */
export function niceValueTicks(min: number, max: number, maxTicks = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (max === min) return [min];
  const span = max - min;
  const rough = span / Math.max(1, maxTicks - 1);
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const residual = rough / magnitude;
  const step =
    (residual >= 5 ? 10 : residual >= 2 ? 5 : residual >= 1 ? 2 : 1) * magnitude || magnitude;
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + step * 1e-6 && ticks.length < 50; v += step) {
    ticks.push(Math.round(v * 1e6) / 1e6);
  }
  return ticks.length ? ticks : [min, max];
}

/** Rounds a chart maximum up to the next nice tick so lines never touch the top. */
export function niceMax(value: number, minimum = 1): number {
  const v = Math.max(minimum, value);
  const ticks = niceValueTicks(0, v * 1.08, 5);
  const last = ticks[ticks.length - 1] ?? v;
  return last >= v ? last : v;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

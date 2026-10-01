import { shortDate } from '../../lib/dates';

export interface LinearScale {
  (value: number): number;
  domain: [number, number];
  range: [number, number];
}

export function linearScale(domain: [number, number], range: [number, number]): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const scale = ((value: number) => r0 + ((value - d0) / span) * (r1 - r0)) as LinearScale;
  scale.domain = domain;
  scale.range = range;
  return scale;
}

/** Milliseconds for a date key (local midnight) or an ISO timestamp. */
export function timeValue(x: string): number {
  if (/^\d{4}-\d{2}-\d{2}$/.test(x)) {
    const [y, m, d] = x.split('-').map(Number) as [number, number, number];
    return new Date(y, m - 1, d).getTime();
  }
  const t = new Date(x).getTime();
  return Number.isNaN(t) ? 0 : t;
}

const DAY = 86_400_000;

/** Picks evenly spread tick indexes so labels never crowd (about one per `pixelsPerTick`). */
export function spreadTickIndexes(count: number, plotWidth: number, pixelsPerTick = 84): number[] {
  if (count <= 0) return [];
  const maxTicks = Math.max(2, Math.floor(plotWidth / pixelsPerTick));
  if (count <= maxTicks) return Array.from({ length: count }, (_, i) => i);
  const step = (count - 1) / (maxTicks - 1);
  const out = new Set<number>();
  for (let i = 0; i < maxTicks; i += 1) out.add(Math.round(i * step));
  return [...out];
}

/** Axis label for a time value given the span the axis covers. */
export function timeLabel(x: string, spanMs: number): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(x)) return shortDate(x, spanMs > 400 * DAY);
  const date = new Date(x);
  if (Number.isNaN(date.getTime())) return x;
  if (spanMs <= 2 * DAY) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  }
  const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  return shortDate(key, spanMs > 400 * DAY);
}

/** Full readable label for tooltips. */
export function timeLabelLong(x: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(x)) {
    const date = new Date(timeValue(x));
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }
  const date = new Date(x);
  if (Number.isNaN(date.getTime())) return x;
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** SVG path for a polyline that breaks at null values. */
export function linePath(points: Array<{ x: number; y: number | null }>): string {
  let d = '';
  let pen = false;
  for (const p of points) {
    if (p.y === null || !Number.isFinite(p.y)) {
      pen = false;
      continue;
    }
    d += `${pen ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** SVG path for an area between two series, broken wherever either is null. */
export function bandPath(
  points: Array<{ x: number; low: number | null; high: number | null }>,
): string {
  const segments: Array<Array<{ x: number; low: number; high: number }>> = [];
  let current: Array<{ x: number; low: number; high: number }> = [];
  for (const p of points) {
    if (p.low === null || p.high === null) {
      if (current.length) segments.push(current);
      current = [];
      continue;
    }
    current.push({ x: p.x, low: p.low, high: p.high });
  }
  if (current.length) segments.push(current);
  return segments
    .filter((seg) => seg.length > 1)
    .map((seg) => {
      const top = seg.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.high.toFixed(1)}`);
      const bottom = seg
        .slice()
        .reverse()
        .map((p) => `L${p.x.toFixed(1)},${p.low.toFixed(1)}`);
      return `${top.join('')}${bottom.join('')}Z`;
    })
    .join('');
}

/** Bar with a 4px rounded data end and a square baseline (vertical bars grow upward). */
export function columnPath(x: number, yTop: number, w: number, h: number, radius = 4): string {
  if (h <= 0 || w <= 0) return '';
  const r = Math.min(radius, w / 2, h);
  return `M${x},${yTop + h}v${-(h - r)}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${h - r}Z`;
}

/** Horizontal bar with a rounded right (data) end and a square left baseline. */
export function barPath(x: number, y: number, w: number, h: number, radius = 4): string {
  if (w <= 0 || h <= 0) return '';
  const r = Math.min(radius, w, h / 2);
  return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(w - r)}Z`;
}

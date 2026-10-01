/** Date helpers for dashboard periods, ISO weeks and compact axis labels. */

export type PeriodPreset = '30' | '90' | '365' | 'custom';

export interface Period {
  preset: PeriodPreset;
  /** YYYY-MM-DD, inclusive. */
  from: string;
  to: string;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** Local calendar date as YYYY-MM-DD. */
export function toDateKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function parseDateKey(key: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(key);
  if (!m) return null;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function periodForPreset(preset: PeriodPreset, today = new Date()): Period {
  const days = preset === '30' ? 30 : preset === '365' ? 365 : 90;
  return { preset, from: toDateKey(addDays(today, -(days - 1))), to: toDateKey(today) };
}

export function periodFromQuery(query: URLSearchParams, today = new Date()): Period {
  const from = query.get('from');
  const to = query.get('to');
  if (from && to && parseDateKey(from) && parseDateKey(to) && from <= to) {
    const preset = query.get('period');
    return {
      preset: preset === '30' || preset === '90' || preset === '365' ? preset : 'custom',
      from,
      to,
    };
  }
  const preset = query.get('period');
  return periodForPreset(preset === '30' || preset === '365' ? preset : '90', today);
}

export function daysBetween(from: string, to: string): number {
  const a = parseDateKey(from);
  const b = parseDateKey(to);
  if (!a || !b) return 0;
  return Math.round((b.getTime() - a.getTime()) / 86_400_000) + 1;
}

/** Every date key between from and to inclusive. */
export function dateRange(from: string, to: string): string[] {
  const start = parseDateKey(from);
  const end = parseDateKey(to);
  if (!start || !end || start > end) return [];
  const out: string[] = [];
  for (let d = start; d <= end && out.length < 4000; d = addDays(d, 1)) out.push(toDateKey(d));
  return out;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "May 14" from YYYY-MM-DD, or "May 2026" when `monthOnly`. */
export function shortDate(key: string, monthOnly = false): string {
  const date = parseDateKey(key);
  if (!date) return key;
  return monthOnly
    ? `${MONTHS[date.getMonth()]} ${date.getFullYear()}`
    : `${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

export function longDate(key: string): string {
  const date = parseDateKey(key);
  if (!date) return key;
  return `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** ISO 8601 week number and week-based year. */
export function isoWeek(date: Date): { year: number; week: number } {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((d.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
  return { year: d.getUTCFullYear(), week };
}

/** Approximate month label for an ISO week (for the phenology axis). */
export function monthOfIsoWeek(week: number): string {
  const index = Math.min(11, Math.floor(((week - 1) * 7 + 3) / 30.44));
  return MONTHS[index] ?? '';
}

export function hourLabel(hour: number): string {
  if (hour === 0) return '12a';
  if (hour === 12) return '12p';
  return hour < 12 ? `${hour}a` : `${hour - 12}p`;
}

/** "3 h ago", "2 d ago", "just now" for freshness copy. */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Math.max(0, now - t);
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days} d ago`;
  const months = Math.round(days / 30);
  return `${months} mo ago`;
}

/** Local datetime-local value for an ISO timestamp (for form defaults). */
export function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function datetimeLocalToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

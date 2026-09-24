const MB = 1024 * 1024;
const KB = 1024;

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Unknown size';
  if (bytes >= MB) return `${(bytes / MB).toFixed(1).replace(/\.0$/, '')} MB`;
  if (bytes >= KB) return `${Math.round(bytes / KB)} KB`;
  return `${bytes} B`;
}

/** 0:07, 1:02, 1:02:03. */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** Like formatClock but keeps one decimal when the value is not a whole second. */
export function formatClockPrecise(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const rounded = Math.round(seconds * 10) / 10;
  const whole = Math.floor(rounded);
  const tenths = Math.round((rounded - whole) * 10);
  const base = formatClock(whole);
  return tenths === 0 ? base : `${base}.${tenths}`;
}

/** 45.2 s, 3 min 05 s, 1 h 02 min. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Unknown';
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`;
  return `${m} min ${String(s).padStart(2, '0')} s`;
}

export function formatSeconds(seconds: number, digits = 1): string {
  if (!Number.isFinite(seconds)) return 'n/a';
  return `${seconds.toFixed(digits)} s`;
}

export function formatPercent(fraction: number, digits = 0): string {
  if (!Number.isFinite(fraction)) return 'n/a';
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return 'n/a';
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatInteger(value: number): string {
  if (!Number.isFinite(value)) return 'n/a';
  return Math.round(value).toLocaleString('en-US');
}

export function formatHz(hz: number): string {
  if (hz >= 1000) {
    const k = hz / 1000;
    return `${Number.isInteger(k) ? k.toFixed(0) : k.toFixed(1)} kHz`;
  }
  return `${Math.round(hz)} Hz`;
}

export function formatMs(ms: number): string {
  if (!Number.isFinite(ms)) return 'n/a';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

function isValidTimeZone(tz: string | null | undefined): tz is string {
  if (!tz) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/**
 * Formats an ISO timestamp. With a time zone, the wall-clock time at the
 * recording site is shown together with the zone abbreviation.
 */
export function formatDateTime(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return 'Not provided';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const zone = isValidTimeZone(timeZone) ? timeZone : undefined;
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: zone,
    timeZoneName: zone ? 'short' : undefined,
  }).format(date);
}

export function formatDate(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return 'Not provided';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: isValidTimeZone(timeZone) ? timeZone : undefined,
  }).format(date);
}

export function formatCoordinate(value: number, axis: 'lat' | 'lon'): string {
  const hemisphere = axis === 'lat' ? (value >= 0 ? 'N' : 'S') : value >= 0 ? 'E' : 'W';
  return `${Math.abs(value).toFixed(4)}° ${hemisphere}`;
}

export function shortHash(hash: string | null | undefined, length = 12): string {
  if (!hash) return 'n/a';
  return hash.length > length ? hash.slice(0, length) : hash;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatInteger(count)} ${count === 1 ? singular : plural}`;
}

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot).toLowerCase() : '';
}

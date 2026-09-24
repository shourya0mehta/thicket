import { ACCEPTED_EXTENSIONS, MAX_FILE_BYTES } from '../config';
import { fileExtension, formatBytes } from './format';

export type FileCheck =
  | { ok: true }
  | { ok: false; code: 'unsupported_file_type' | 'file_too_large' | 'empty_file'; message: string };

export function validateAudioFile(file: File): FileCheck {
  const ext = fileExtension(file.name);
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
    return {
      ok: false,
      code: 'unsupported_file_type',
      message: `"${file.name}" is not a supported audio file. Choose a .wav, .mp3, .m4a or .flac recording.`,
    };
  }
  if (file.size > MAX_FILE_BYTES) {
    return {
      ok: false,
      code: 'file_too_large',
      message: `"${file.name}" is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_FILE_BYTES)}; trim the recording or export it at a lower bitrate.`,
    };
  }
  if (file.size === 0) {
    return { ok: false, code: 'empty_file', message: `"${file.name}" is empty.` };
  }
  return { ok: true };
}

export interface Metadata {
  siteName: string;
  latitude: string;
  longitude: string;
  /** datetime-local value, wall-clock time at the recording site. */
  capturedAt: string;
  timezone: string;
}

export type MetadataErrors = Partial<Record<keyof Metadata, string>>;

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function emptyMetadata(): Metadata {
  return { siteName: '', latitude: '', longitude: '', capturedAt: '', timezone: browserTimeZone() };
}

export function isValidTimeZone(zone: string): boolean {
  if (!zone.trim()) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone.trim() });
    return true;
  } catch {
    return false;
  }
}

function parseCoordinate(raw: string): number | null {
  const text = raw.trim();
  if (!text) return null;
  if (!/^[-+]?\d+(\.\d+)?$/.test(text)) return Number.NaN;
  return Number(text);
}

export function validateMetadata(meta: Metadata): MetadataErrors {
  const errors: MetadataErrors = {};
  const lat = parseCoordinate(meta.latitude);
  const lon = parseCoordinate(meta.longitude);

  if (lat !== null && (Number.isNaN(lat) || lat < -90 || lat > 90)) {
    errors.latitude = 'Latitude must be a number between -90 and 90.';
  }
  if (lon !== null && (Number.isNaN(lon) || lon < -180 || lon > 180)) {
    errors.longitude = 'Longitude must be a number between -180 and 180.';
  }
  if (lat !== null && lon === null && !errors.latitude) {
    errors.longitude = 'Add a longitude too, or clear the latitude.';
  }
  if (lon !== null && lat === null && !errors.longitude) {
    errors.latitude = 'Add a latitude too, or clear the longitude.';
  }
  if (meta.capturedAt && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(meta.capturedAt)) {
    errors.capturedAt = 'Enter a valid date and time.';
  }
  if (meta.timezone.trim() && !isValidTimeZone(meta.timezone)) {
    errors.timezone = 'Use an IANA time zone such as America/Chicago.';
  }
  if (meta.capturedAt && !meta.timezone.trim()) {
    errors.timezone = 'Add the time zone the recording date is in.';
  }
  return errors;
}

export function coordinatesFrom(meta: Metadata): { latitude: number; longitude: number } | null {
  const lat = parseCoordinate(meta.latitude);
  const lon = parseCoordinate(meta.longitude);
  if (lat === null || lon === null || Number.isNaN(lat) || Number.isNaN(lon)) return null;
  return { latitude: lat, longitude: lon };
}

function zoneOffsetMinutes(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(instant));
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((p) => p.type === type)?.value ?? '0');
  const asUtc = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    get('hour') % 24,
    get('minute'),
    get('second'),
  );
  return Math.round((asUtc - instant) / 60_000);
}

const pad = (n: number) => String(n).padStart(2, '0');

/**
 * Converts a wall-clock time at the recording site (datetime-local value) in an
 * IANA zone to ISO 8601 with that zone's UTC offset, e.g. 2026-05-14T05:42:00-04:00.
 */
export function zonedLocalToIso(local: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(local);
  if (!match || !isValidTimeZone(timeZone)) return null;
  const [y, mo, d, h, mi, s] = match.slice(1).map((v) => Number(v ?? 0)) as [
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  const wallAsUtc = Date.UTC(y, mo - 1, d, h, mi, s || 0);
  let offset = zoneOffsetMinutes(wallAsUtc, timeZone);
  const corrected = zoneOffsetMinutes(wallAsUtc - offset * 60_000, timeZone);
  if (corrected !== offset) offset = corrected;
  const sign = offset >= 0 ? '+' : '-';
  const abs = Math.abs(offset);
  return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}:${pad(s || 0)}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

let cachedZones: string[] | null = null;

export function timeZoneOptions(): string[] {
  if (cachedZones) return cachedZones;
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    cachedZones = intl.supportedValuesOf?.('timeZone') ?? [];
  } catch {
    cachedZones = [];
  }
  return cachedZones;
}

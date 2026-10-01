/**
 * Client-side preview of the capture timestamp a recorder wrote into a file
 * name. Mirrors the patterns the backend parses (docs/PLATFORM_API.md); the
 * server result always wins once the batch is processed.
 *
 *   AudioMoth    20240514_053000.WAV            UTC
 *                <prefix>_20240514_053000.WAV   UTC (AudioMoth with a custom prefix)
 *   Song Meter   SMA12345_20240514_053000.wav   local time per the recorder's clock
 *                SMM01234_20240514_053000.wav
 *   ISO          2024-05-14T05-30-00            local
 *                2024-05-14 05.30.00            local
 *   Compact      20240514T053000                local
 *   Voice Memos  New Recording 7                no timestamp
 */

export type FilenamePattern =
  | 'audiomoth'
  | 'audiomoth_prefixed'
  | 'song_meter'
  | 'iso'
  | 'iso_space'
  | 'compact'
  | 'voice_memo';

export interface ParsedFilename {
  pattern: FilenamePattern | null;
  /** Wall-clock timestamp without zone, `YYYY-MM-DDTHH:MM:SS`, or null. */
  localTimestamp: string | null;
  /** Whether the timestamp is UTC (AudioMoth) or the recorder's local clock. */
  clock: 'utc' | 'local' | null;
  /** Short explanation for the UI. */
  note: string;
}

export const AUDIO_EXTENSIONS = ['.wav', '.flac', '.mp3', '.m4a'] as const;
export const SIDECAR_EXTENSIONS = ['.txt', '.zip'] as const;

const PATTERN_LABEL: Record<FilenamePattern, string> = {
  audiomoth: 'AudioMoth name (UTC)',
  audiomoth_prefixed: 'AudioMoth name with prefix (UTC)',
  song_meter: 'Song Meter name (recorder local time)',
  iso: 'ISO date in name (local)',
  iso_space: 'Date and time in name (local)',
  compact: 'Compact timestamp in name (local)',
  voice_memo: 'Voice Memos name (no timestamp)',
};

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function validDate(y: number, mo: number, d: number, h: number, mi: number, s: number) {
  if (y < 2000 || y > 2100) return false;
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 60) return false;
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

function stamp(y: number, mo: number, d: number, h: number, mi: number, s: number): string | null {
  if (!validDate(y, mo, d, h, mi, s)) return null;
  return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}:${pad(s)}`;
}

function fromCompact(date: string, time: string): string | null {
  return stamp(
    Number(date.slice(0, 4)),
    Number(date.slice(4, 6)),
    Number(date.slice(6, 8)),
    Number(time.slice(0, 2)),
    Number(time.slice(2, 4)),
    Number(time.slice(4, 6)),
  );
}

export function stripExtension(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? name;
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(0, dot) : base;
}

export function fileExtensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot).toLowerCase() : '';
}

export function parseFilenameTimestamp(filename: string): ParsedFilename {
  const base = stripExtension(filename.trim());
  const none = (pattern: FilenamePattern | null, note: string): ParsedFilename => ({
    pattern,
    localTimestamp: null,
    clock: null,
    note,
  });

  let m = /^(\d{8})_(\d{6})$/.exec(base);
  if (m) {
    const ts = fromCompact(m[1]!, m[2]!);
    return ts
      ? { pattern: 'audiomoth', localTimestamp: ts, clock: 'utc', note: PATTERN_LABEL.audiomoth }
      : none(null, 'Looks like an AudioMoth name but the date is not valid.');
  }

  m = /^(SM[A-Z]?\d+)_(\d{8})_(\d{6})$/i.exec(base);
  if (m) {
    const ts = fromCompact(m[2]!, m[3]!);
    return ts
      ? {
          pattern: 'song_meter',
          localTimestamp: ts,
          clock: 'local',
          note: PATTERN_LABEL.song_meter,
        }
      : none(null, 'Looks like a Song Meter name but the date is not valid.');
  }

  m = /^(.+)_(\d{8})_(\d{6})$/.exec(base);
  if (m) {
    const ts = fromCompact(m[2]!, m[3]!);
    return ts
      ? {
          pattern: 'audiomoth_prefixed',
          localTimestamp: ts,
          clock: 'utc',
          note: PATTERN_LABEL.audiomoth_prefixed,
        }
      : none(null, 'The name carries a date that is not valid.');
  }

  m = /(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})/.exec(base);
  if (m) {
    const ts = stamp(
      ...(m.slice(1, 7).map(Number) as [number, number, number, number, number, number]),
    );
    return ts
      ? { pattern: 'iso', localTimestamp: ts, clock: 'local', note: PATTERN_LABEL.iso }
      : none(null, 'The name carries a date that is not valid.');
  }

  m = /(\d{4})-(\d{2})-(\d{2}) (\d{2})\.(\d{2})\.(\d{2})/.exec(base);
  if (m) {
    const ts = stamp(
      ...(m.slice(1, 7).map(Number) as [number, number, number, number, number, number]),
    );
    return ts
      ? { pattern: 'iso_space', localTimestamp: ts, clock: 'local', note: PATTERN_LABEL.iso_space }
      : none(null, 'The name carries a date that is not valid.');
  }

  m = /(?:^|[^\d])(\d{8})T(\d{6})(?:[^\d]|$)/.exec(base);
  if (m) {
    const ts = fromCompact(m[1]!, m[2]!);
    return ts
      ? { pattern: 'compact', localTimestamp: ts, clock: 'local', note: PATTERN_LABEL.compact }
      : none(null, 'The name carries a date that is not valid.');
  }

  if (/^New Recording( \d+)?$/i.test(base)) {
    return none(
      'voice_memo',
      'Voice Memos name: no timestamp. The file date or your override will be used.',
    );
  }

  return none(null, 'No timestamp in the name. File metadata or the file date will be used.');
}

export type UploadFileKind = 'audio' | 'zip' | 'sidecar' | 'unsupported';

/** Classifies a file for the batch uploader (audio, zip archive, recorder sidecar). */
export function classifyUploadFile(name: string): UploadFileKind {
  const ext = fileExtensionOf(name);
  if ((AUDIO_EXTENSIONS as readonly string[]).includes(ext)) return 'audio';
  if (ext === '.zip') return 'zip';
  if (ext === '.txt') {
    const base = name.split(/[\\/]/).pop() ?? name;
    if (/_Summary\.txt$/i.test(base) || /^CONFIG\.TXT$/i.test(base)) return 'sidecar';
  }
  return 'unsupported';
}

/** Human label for a preview row, e.g. "May 14, 2024, 05:30 UTC". */
export function describeTimestamp(parsed: ParsedFilename): string {
  if (!parsed.localTimestamp) return 'Not in the name';
  const [date, time] = parsed.localTimestamp.split('T');
  return `${date} ${time?.slice(0, 5)}${parsed.clock === 'utc' ? ' UTC' : ' local'}`;
}

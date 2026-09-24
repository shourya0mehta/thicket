/**
 * Runtime configuration from Vite env variables. Read through functions (not
 * module-level constants) so tests can stub env per case.
 */

/** Client-side upload guard. The server enforces its own limits as well. */
export const MAX_FILE_BYTES = 20 * 1024 * 1024;

export const ACCEPTED_EXTENSIONS = ['.wav', '.mp3', '.m4a', '.flac'] as const;

export const DEFAULT_THRESHOLD = 0.6;
export const THRESHOLD_STEP = 0.05;
export const THRESHOLD_MAX = 0.95;
/** Used until an analysis reports its own ingestion floor. */
export const FALLBACK_RAW_THRESHOLD = 0.1;

export const POLL_INTERVAL_MS = 700;
export const THRESHOLD_DEBOUNCE_MS = 250;
/** Stop polling after this long; the server has its own analysis timeout. */
export const MAX_POLL_DURATION_MS = 20 * 60 * 1000;

export const HISTORY_KEY = 'thicket-history';
export const THEME_KEY = 'thicket-theme';
export const HISTORY_LIMIT = 3;

export function apiBaseUrl(): string {
  const raw: unknown = import.meta.env.VITE_API_BASE_URL;
  return typeof raw === 'string' ? raw.trim().replace(/\/+$/, '') : '';
}

export function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === 'true';
}

export function experimentalModelsEnabled(): boolean {
  return import.meta.env.VITE_ENABLE_EXPERIMENTAL_MODELS === 'true';
}

/** Public asset base (Vite `base`), always ending with a slash. */
export function publicBase(): string {
  const base = import.meta.env.BASE_URL || '/';
  return base.endsWith('/') ? base : `${base}/`;
}

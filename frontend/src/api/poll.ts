import { MAX_POLL_DURATION_MS, POLL_INTERVAL_MS } from '../config';
import { ApiError, getAnalysis, isAbortError } from './client';
import type { Analysis } from './types';

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      window.clearTimeout(timer);
      const error = new Error('Aborted');
      error.name = 'AbortError';
      reject(error);
    };
    if (signal?.aborted) {
      abort();
      return;
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', abort, { once: true });
  });
}

export interface PollOptions {
  signal?: AbortSignal;
  intervalMs?: number;
  maxDurationMs?: number;
  /** Consecutive network failures tolerated before giving up. */
  maxFailures?: number;
  onUpdate?: (analysis: Analysis) => void;
  fetcher?: (id: string, signal?: AbortSignal) => Promise<Analysis>;
}

/** Polls GET /analyses/{id} until the analysis is completed or failed. */
export async function pollAnalysis(id: string, options: PollOptions = {}): Promise<Analysis> {
  const {
    signal,
    intervalMs = POLL_INTERVAL_MS,
    maxDurationMs = MAX_POLL_DURATION_MS,
    maxFailures = 5,
    onUpdate,
    fetcher = (analysisId, s) => getAnalysis(analysisId, { signal: s }),
  } = options;
  const started = Date.now();
  let failures = 0;

  for (;;) {
    await sleep(intervalMs, signal);
    try {
      const analysis = await fetcher(id, signal);
      failures = 0;
      onUpdate?.(analysis);
      if (analysis.status === 'completed' || analysis.status === 'failed') return analysis;
    } catch (error) {
      if (isAbortError(error)) throw error;
      const transient =
        error instanceof ApiError &&
        (error.code === 'network' || error.code === 'backend_unavailable');
      failures += 1;
      if (!transient || failures >= maxFailures) throw error;
    }
    if (Date.now() - started > maxDurationMs) {
      throw new ApiError(
        'analysis_timeout',
        'The analysis is still running after a long wait. Check the server, then try again.',
      );
    }
  }
}

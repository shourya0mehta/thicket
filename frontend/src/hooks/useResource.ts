import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbortError } from '../api/client';
import { describeError, type FriendlyError } from '../api/errors';

export interface Resource<T> {
  data: T | null;
  error: FriendlyError | null;
  /** True during the first load; refreshes keep the previous data on screen. */
  loading: boolean;
  /** True while any load is in flight (first or refresh). */
  busy: boolean;
  reload: () => void;
  /** Replace the data locally (optimistic updates after a mutation). */
  setData: (updater: T | ((current: T | null) => T | null)) => void;
}

/**
 * Loads one resource with abort-on-change semantics. `key` identifies the
 * request: when it changes the previous request is aborted and a new one
 * starts, holding the old data at reduced opacity rather than flashing.
 */
export function useResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  key: string,
  enabled = true,
): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [busy, setBusy] = useState(enabled);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled) {
      setBusy(false);
      return;
    }
    const ctrl = new AbortController();
    setBusy(true);
    setError(null);
    fetcherRef
      .current(ctrl.signal)
      .then((result) => {
        if (ctrl.signal.aborted) return;
        setData(result);
        setLoadedKey(key);
        setBusy(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted || isAbortError(err)) return;
        setError(describeError(err));
        setBusy(false);
      });
    return () => ctrl.abort();
  }, [key, attempt, enabled]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const set = useCallback((updater: T | ((current: T | null) => T | null)) => {
    setData((current) =>
      typeof updater === 'function' ? (updater as (c: T | null) => T | null)(current) : updater,
    );
  }, []);

  return {
    data,
    error,
    loading: busy && (data === null || loadedKey === null),
    busy,
    reload,
    setData: set,
  };
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { getModels } from '../api/client';
import { describeError, type FriendlyError } from '../api/errors';
import type { ModelInfo } from '../api/types';

const LOADING_POLL_MS = 3000;

export interface ModelsState {
  status: 'idle' | 'loading' | 'ready' | 'error';
  models: ModelInfo[];
  error: FriendlyError | null;
  reload: () => void;
}

export function useModels(enabled: boolean): ModelsState {
  const [status, setStatus] = useState<ModelsState['status']>(enabled ? 'loading' : 'idle');
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<FriendlyError | null>(null);
  const ctrl = useRef<AbortController | null>(null);
  const retryTimer = useRef<number | null>(null);

  /** `silent` refreshes keep the current list on screen (no loading state). */
  const load = useCallback(async (silent = false): Promise<void> => {
    if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    retryTimer.current = null;
    ctrl.current?.abort();
    const controller = new AbortController();
    ctrl.current = controller;
    if (!silent) {
      setStatus('loading');
      setError(null);
    }
    try {
      const response = await getModels(controller.signal);
      if (controller.signal.aborted) return;
      const list = Array.isArray(response.models) ? response.models : [];
      setModels(list);
      setStatus('ready');
      // Models load in the background on server start; refresh until they settle.
      if (list.some((m) => m.status === 'loading')) {
        retryTimer.current = window.setTimeout(() => void load(true), LOADING_POLL_MS);
      }
    } catch (err) {
      const friendly = describeError(err);
      if (!friendly || controller.signal.aborted) return;
      setError(friendly);
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load();
    return () => {
      ctrl.current?.abort();
      if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    };
  }, [enabled, load]);

  return { status, models, error, reload: () => void load() };
}

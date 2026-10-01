import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import * as api from '../api/client';
import { ApiError } from '../api/client';
import { describeError, describeErrorCode } from '../api/errors';
import { pollAnalysis } from '../api/poll';
import type { Analysis, CreateAnalysisParams, ReviewStatus } from '../api/types';
import { DEFAULT_THRESHOLD, THRESHOLD_DEBOUNCE_MS, isDemoMode } from '../config';
import { loadDemoAnalysis } from '../lib/demo';
import { addToHistory, entryFromAnalysis, readHistory, removeFromHistory } from '../lib/history';
import { sameThreshold } from '../lib/threshold';
import {
  coordinatesFrom,
  validateAudioFile,
  zonedLocalToIso,
  type Metadata,
} from '../lib/validation';
import {
  initialWorkspaceState,
  workspaceReducer,
  type ResultSource,
  type WorkspaceState,
} from './workspaceReducer';

type LastAction =
  | { kind: 'run'; models: string[] }
  | { kind: 'preview' }
  | { kind: 'load'; id: string }
  | { kind: 'demo'; id: string };

/** Where a platform analysis is filed. Null outside an organization. */
export interface OrgContext {
  organizationId: string;
  siteId: string | null;
  deploymentId: string | null;
  recorderId: string | null;
}

export interface Workspace {
  state: WorkspaceState;
  /** Set by the platform analyze page; sent with the next run. */
  setOrgContext: (context: OrgContext | null) => void;
  /** Audio source for playback: the local file, or a retained/demo audio URL. */
  audioSrc: string | null;
  selectFile: (file: File | null) => void;
  clear: () => void;
  setMetadata: (patch: Partial<Metadata>) => void;
  setKeepMetadata: (value: boolean) => void;
  generatePreview: () => Promise<void>;
  runAnalysis: (models: string[]) => Promise<void>;
  /** Stops following the running analysis (the server may still finish it). */
  cancelRun: () => void;
  retryRefresh: () => void;
  retry: () => void;
  setThreshold: (value: number) => void;
  review: (eventId: string, status: ReviewStatus) => Promise<void>;
  deleteCurrent: () => Promise<void>;
  loadAnalysis: (id: string) => Promise<void>;
  loadDemo: (id: string) => Promise<void>;
  dismissNotice: () => void;
  refreshHistory: () => void;
}

function analysisParams(
  metadata: Metadata,
  models: string[],
  threshold: number,
  context: OrgContext | null,
): CreateAnalysisParams {
  const coords = coordinatesFrom(metadata);
  const timezone = metadata.timezone.trim() || null;
  return {
    models,
    threshold,
    latitude: coords?.latitude ?? null,
    longitude: coords?.longitude ?? null,
    capturedAt:
      metadata.capturedAt && timezone ? zonedLocalToIso(metadata.capturedAt, timezone) : null,
    timezone,
    siteName: metadata.siteName.trim() || null,
    organizationId: context?.organizationId ?? null,
    siteId: context?.siteId ?? null,
    deploymentId: context?.deploymentId ?? null,
    recorderId: context?.recorderId ?? null,
  };
}

function previewIsFresh(expiresAt: string | undefined): boolean {
  if (!expiresAt) return false;
  const expires = new Date(expiresAt).getTime();
  return Number.isFinite(expires) && expires - Date.now() > 10_000;
}

export function useWorkspace(): Workspace {
  const [state, dispatch] = useReducer(workspaceReducer, undefined, () =>
    initialWorkspaceState(isDemoMode() ? [] : readHistory()),
  );
  const stateRef = useRef(state);
  stateRef.current = state;

  const runCtrl = useRef<AbortController | null>(null);
  const previewCtrl = useRef<AbortController | null>(null);
  const refreshCtrl = useRef<AbortController | null>(null);
  const refreshSeq = useRef(0);
  const objectUrl = useRef<string | null>(null);
  const lastAction = useRef<LastAction | null>(null);
  const orgContext = useRef<OrgContext | null>(null);

  const abortAll = useCallback(() => {
    runCtrl.current?.abort();
    previewCtrl.current?.abort();
    refreshCtrl.current?.abort();
    runCtrl.current = null;
    previewCtrl.current = null;
    refreshCtrl.current = null;
    refreshSeq.current += 1;
  }, []);

  const replaceObjectUrl = useCallback((file: File | null): string | null => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = file ? URL.createObjectURL(file) : null;
    return objectUrl.current;
  }, []);

  useEffect(
    () => () => {
      abortAll();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    },
    [abortAll],
  );

  /**
   * Fire and forget: the server deletes the previewed upload now instead of at
   * its expiry. Used whenever the workspace lets go of a preview.
   */
  const discardPreview = useCallback(() => {
    const { preview } = stateRef.current;
    if (!preview || isDemoMode()) return;
    void api.deletePreview(preview.id).catch(() => undefined);
  }, []);

  const rememberInHistory = useCallback((analysis: Analysis) => {
    if (isDemoMode()) return;
    dispatch({ type: 'history', history: addToHistory(entryFromAnalysis(analysis)) });
  }, []);

  const selectFile = useCallback(
    (file: File | null) => {
      if (!file) return;
      abortAll();
      discardPreview();
      const check = validateAudioFile(file);
      if (!check.ok) {
        replaceObjectUrl(null);
        dispatch({ type: 'file_rejected', message: check.message });
        return;
      }
      const url = replaceObjectUrl(file);
      dispatch({ type: 'file_selected', file, url: url ?? '' });
    },
    [abortAll, discardPreview, replaceObjectUrl],
  );

  const clear = useCallback(() => {
    abortAll();
    discardPreview();
    replaceObjectUrl(null);
    lastAction.current = null;
    dispatch({ type: 'cleared' });
  }, [abortAll, discardPreview, replaceObjectUrl]);

  const generatePreview = useCallback(async () => {
    const { file } = stateRef.current;
    if (!file || isDemoMode()) return;
    previewCtrl.current?.abort();
    const ctrl = new AbortController();
    previewCtrl.current = ctrl;
    lastAction.current = { kind: 'preview' };
    dispatch({ type: 'preview_start' });
    try {
      const preview = await api.createPreview(
        file,
        (fraction) => dispatch({ type: 'preview_progress', fraction }),
        ctrl.signal,
      );
      if (ctrl.signal.aborted) return;
      dispatch({ type: 'preview_done', preview });
    } catch (error) {
      const friendly = describeError(error);
      if (friendly && !ctrl.signal.aborted) dispatch({ type: 'preview_failed', error: friendly });
    }
  }, []);

  const finishRun = useCallback(
    (analysis: Analysis, source: ResultSource) => {
      if (analysis.status === 'failed') {
        dispatch({
          type: 'run_failed',
          analysis,
          error: describeErrorCode(analysis.error_code ?? 'internal_error', analysis.error_message),
        });
        return;
      }
      dispatch({ type: 'run_done', analysis, source });
      rememberInHistory(analysis);
    },
    [rememberInHistory],
  );

  const runAnalysis = useCallback(
    async (models: string[]) => {
      const current = stateRef.current;
      if (isDemoMode() || (!current.file && !current.preview) || models.length === 0) return;
      runCtrl.current?.abort();
      refreshCtrl.current?.abort();
      const ctrl = new AbortController();
      runCtrl.current = ctrl;
      lastAction.current = { kind: 'run', models };

      const usePreview = previewIsFresh(current.preview?.expires_at) && current.preview !== null;
      const params = analysisParams(
        current.metadata,
        models,
        current.threshold,
        orgContext.current,
      );
      const onProgress = (fraction: number) => {
        if (!ctrl.signal.aborted) dispatch({ type: 'run_upload_progress', fraction });
      };
      dispatch({ type: 'run_start', models, uploadSkipped: usePreview });

      try {
        let accepted: Analysis;
        try {
          accepted = await api.createAnalysis(
            usePreview
              ? { ...params, previewId: current.preview?.id ?? null, file: null }
              : { ...params, file: current.file },
            onProgress,
            ctrl.signal,
          );
        } catch (error) {
          // The preview may have expired server-side: fall back to uploading the file.
          const retryWithFile =
            usePreview &&
            current.file !== null &&
            error instanceof ApiError &&
            (error.code === 'not_found' ||
              error.code === 'invalid_parameter' ||
              error.code === 'analysis_not_found');
          if (!retryWithFile) throw error;
          dispatch({ type: 'run_start', models, uploadSkipped: false });
          accepted = await api.createAnalysis(
            { ...params, file: current.file, previewId: null },
            onProgress,
            ctrl.signal,
          );
        }
        if (ctrl.signal.aborted) return;
        dispatch({ type: 'run_update', analysis: accepted });

        const final =
          accepted.status === 'completed' || accepted.status === 'failed'
            ? accepted
            : await pollAnalysis(accepted.id, {
                signal: ctrl.signal,
                onUpdate: (analysis) => {
                  if (!ctrl.signal.aborted) dispatch({ type: 'run_update', analysis });
                },
              });
        if (ctrl.signal.aborted) return;
        finishRun(final, 'upload');
      } catch (error) {
        const friendly = describeError(error);
        if (friendly && !ctrl.signal.aborted) dispatch({ type: 'run_failed', error: friendly });
      }
    },
    [finishRun],
  );

  const refreshAt = useCallback(async (threshold: number) => {
    const { analysis, source, demoId } = stateRef.current;
    if (!analysis) return;
    refreshCtrl.current?.abort();
    const ctrl = new AbortController();
    refreshCtrl.current = ctrl;
    const seq = ++refreshSeq.current;
    dispatch({ type: 'refresh_start' });
    try {
      const next =
        source === 'demo' && demoId
          ? await loadDemoAnalysis(demoId, threshold, ctrl.signal)
          : await api.getAnalysis(analysis.id, { threshold, signal: ctrl.signal });
      if (seq !== refreshSeq.current) return;
      if (!sameThreshold(next.settings.decision_threshold, stateRef.current.threshold)) {
        // The slider moved while this request was in flight (for example back to
        // the applied value, which schedules no new request). Showing this result
        // would pair the slider with results computed at another threshold.
        dispatch({ type: 'refresh_cancelled' });
        return;
      }
      dispatch({ type: 'refresh_done', analysis: next });
    } catch (error) {
      const friendly = describeError(error);
      if (friendly && seq === refreshSeq.current)
        dispatch({ type: 'refresh_failed', error: friendly });
    }
  }, []);

  // Debounced refetch whenever the requested threshold moves away from the applied one.
  const analysisId = state.analysis?.id ?? null;
  useEffect(() => {
    const analysis = stateRef.current.analysis;
    if (!analysis || analysis.status !== 'completed') return;
    if (sameThreshold(analysis.settings.decision_threshold, state.threshold)) return;
    const timer = window.setTimeout(() => {
      void refreshAt(state.threshold);
    }, THRESHOLD_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [state.threshold, analysisId, refreshAt]);

  const setThreshold = useCallback((value: number) => {
    dispatch({ type: 'threshold_set', value });
  }, []);

  const review = useCallback(
    async (eventId: string, status: ReviewStatus) => {
      const { analysis, source, threshold } = stateRef.current;
      if (!analysis || source === 'demo' || isDemoMode()) return;
      dispatch({ type: 'review_start', eventId });
      try {
        await api.reviewEvent(eventId, { review_status: status });
      } catch (error) {
        dispatch({ type: 'review_failed', error: describeError(error) });
        return;
      }
      // The refetch replaces any threshold recompute in flight.
      refreshCtrl.current?.abort();
      const ctrl = new AbortController();
      refreshCtrl.current = ctrl;
      const seq = ++refreshSeq.current;
      try {
        const next = await api.getAnalysis(analysis.id, { threshold, signal: ctrl.signal });
        const latest = seq === refreshSeq.current;
        dispatch({ type: 'review_done', analysis: latest ? next : null });
        const wanted = stateRef.current.threshold;
        if (latest && !sameThreshold(next.settings.decision_threshold, wanted)) {
          // The slider moved during the review; bring the results to its position.
          void refreshAt(wanted);
        }
      } catch (error) {
        dispatch({ type: 'review_failed', error: describeError(error) });
        if (seq === refreshSeq.current) dispatch({ type: 'refresh_cancelled' });
      }
    },
    [refreshAt],
  );

  const deleteCurrent = useCallback(async () => {
    const { analysis } = stateRef.current;
    if (!analysis || isDemoMode()) return;
    abortAll();
    try {
      await api.deleteAnalysis(analysis.id);
    } catch (error) {
      // abortAll() dropped any recompute in flight; the analysis stays on screen.
      dispatch({ type: 'refresh_cancelled' });
      throw error;
    }
    dispatch({ type: 'history', history: removeFromHistory(analysis.id) });
    dispatch({
      type: 'deleted',
      notice: 'The analysis and its derived files were deleted from the server.',
    });
  }, [abortAll]);

  const loadAnalysis = useCallback(
    async (id: string) => {
      if (isDemoMode()) return;
      abortAll();
      discardPreview();
      replaceObjectUrl(null);
      const ctrl = new AbortController();
      runCtrl.current = ctrl;
      lastAction.current = { kind: 'load', id };
      dispatch({ type: 'load_start', source: 'history' });
      try {
        const analysis = await api.getAnalysis(id, { signal: ctrl.signal });
        if (ctrl.signal.aborted) return;
        if (analysis.status === 'completed') {
          dispatch({ type: 'load_done', analysis, source: 'history' });
          rememberInHistory(analysis);
          return;
        }
        dispatch({ type: 'run_update', analysis });
        const final =
          analysis.status === 'failed'
            ? analysis
            : await pollAnalysis(id, {
                signal: ctrl.signal,
                onUpdate: (a) => {
                  if (!ctrl.signal.aborted) dispatch({ type: 'run_update', analysis: a });
                },
              });
        if (!ctrl.signal.aborted) finishRun(final, 'history');
      } catch (error) {
        if (ctrl.signal.aborted) return;
        if (
          error instanceof ApiError &&
          (error.status === 404 || error.code === 'analysis_not_found')
        ) {
          dispatch({ type: 'history', history: removeFromHistory(id) });
          dispatch({
            type: 'load_failed',
            error: null,
            notice:
              'That analysis is no longer on the server (it may have been deleted or expired), so it was removed from your history.',
          });
          return;
        }
        dispatch({ type: 'load_failed', error: describeError(error) });
      }
    },
    [abortAll, discardPreview, finishRun, rememberInHistory, replaceObjectUrl],
  );

  const loadDemo = useCallback(
    async (id: string) => {
      abortAll();
      replaceObjectUrl(null);
      const ctrl = new AbortController();
      runCtrl.current = ctrl;
      lastAction.current = { kind: 'demo', id };
      dispatch({ type: 'load_start', source: 'demo', demoId: id });
      try {
        const analysis = await loadDemoAnalysis(id, DEFAULT_THRESHOLD, ctrl.signal);
        if (!ctrl.signal.aborted) dispatch({ type: 'load_done', analysis, source: 'demo' });
      } catch (error) {
        if (!ctrl.signal.aborted) dispatch({ type: 'load_failed', error: describeError(error) });
      }
    },
    [abortAll, replaceObjectUrl],
  );

  const retry = useCallback(() => {
    const action = lastAction.current;
    if (!action) return;
    if (action.kind === 'run') void runAnalysis(action.models);
    else if (action.kind === 'preview') void generatePreview();
    else if (action.kind === 'load') void loadAnalysis(action.id);
    else void loadDemo(action.id);
  }, [generatePreview, loadAnalysis, loadDemo, runAnalysis]);

  const cancelRun = useCallback(() => {
    runCtrl.current?.abort();
    runCtrl.current = null;
    dispatch({ type: 'run_cancelled' });
  }, []);

  const retryRefresh = useCallback(() => {
    void refreshAt(stateRef.current.threshold);
  }, [refreshAt]);

  const setMetadata = useCallback((patch: Partial<Metadata>) => {
    dispatch({ type: 'metadata_changed', patch });
  }, []);

  const setKeepMetadata = useCallback((value: boolean) => {
    dispatch({ type: 'keep_metadata', value });
  }, []);

  const dismissNotice = useCallback(() => dispatch({ type: 'notice', notice: null }), []);

  const setOrgContext = useCallback((context: OrgContext | null) => {
    orgContext.current = context;
  }, []);

  const refreshHistory = useCallback(() => {
    if (!isDemoMode()) dispatch({ type: 'history', history: readHistory() });
  }, []);

  const audioSrc = useMemo(() => {
    if (state.localAudioUrl && (state.source === null || state.source === 'upload')) {
      return state.localAudioUrl;
    }
    return api.resolveApiUrl(state.analysis?.assets.audio_url ?? null);
  }, [state.localAudioUrl, state.source, state.analysis?.assets.audio_url]);

  return {
    state,
    setOrgContext,
    audioSrc,
    selectFile,
    clear,
    setMetadata,
    setKeepMetadata,
    generatePreview,
    runAnalysis,
    cancelRun,
    retryRefresh,
    retry,
    setThreshold,
    review,
    deleteCurrent,
    loadAnalysis,
    loadDemo,
    dismissNotice,
    refreshHistory,
  };
}

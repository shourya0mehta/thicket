import type { FriendlyError } from '../api/errors';
import type { Analysis, Preview } from '../api/types';
import { DEFAULT_THRESHOLD } from '../config';
import type { HistoryEntry } from '../lib/history';
import { stageDefinitions, stageIndex } from '../lib/stages';
import { emptyMetadata, type Metadata } from '../lib/validation';

export type RunPhase = 'idle' | 'uploading' | 'processing' | 'completed' | 'failed';
export type PreviewPhase = 'idle' | 'uploading' | 'processing' | 'ready' | 'failed';
export type ResultSource = 'upload' | 'history' | 'demo';

export interface RunState {
  phase: RunPhase;
  uploadProgress: number;
  /** Requested model keys, in order, for the stage list. */
  models: string[];
  stage: string | null;
  /** Highest stage index reached; progress never moves backwards. */
  stageIndex: number;
  timings: Record<string, number> | null;
  error: FriendlyError | null;
  analysisId: string | null;
}

export interface WorkspaceState {
  file: File | null;
  fileError: string | null;
  localAudioUrl: string | null;
  metadata: Metadata;
  keepMetadata: boolean;
  preview: Preview | null;
  previewPhase: PreviewPhase;
  previewProgress: number;
  previewError: FriendlyError | null;
  run: RunState;
  analysis: Analysis | null;
  source: ResultSource | null;
  demoId: string | null;
  /** Requested decision threshold (slider). The applied one is on the analysis. */
  threshold: number;
  refreshing: boolean;
  refreshError: FriendlyError | null;
  loading: boolean;
  loadError: FriendlyError | null;
  reviewingEventId: string | null;
  reviewError: FriendlyError | null;
  notice: string | null;
  history: HistoryEntry[];
}

export const IDLE_RUN: RunState = {
  phase: 'idle',
  uploadProgress: 0,
  models: [],
  stage: null,
  stageIndex: -1,
  timings: null,
  error: null,
  analysisId: null,
};

export function initialWorkspaceState(history: HistoryEntry[] = []): WorkspaceState {
  return {
    file: null,
    fileError: null,
    localAudioUrl: null,
    metadata: emptyMetadata(),
    keepMetadata: false,
    preview: null,
    previewPhase: 'idle',
    previewProgress: 0,
    previewError: null,
    run: IDLE_RUN,
    analysis: null,
    source: null,
    demoId: null,
    threshold: DEFAULT_THRESHOLD,
    refreshing: false,
    refreshError: null,
    loading: false,
    loadError: null,
    reviewingEventId: null,
    reviewError: null,
    notice: null,
    history,
  };
}

export type WorkspaceAction =
  | { type: 'file_selected'; file: File; url: string }
  | { type: 'file_rejected'; message: string }
  | { type: 'cleared' }
  | { type: 'metadata_changed'; patch: Partial<Metadata> }
  | { type: 'keep_metadata'; value: boolean }
  | { type: 'preview_start' }
  | { type: 'preview_progress'; fraction: number }
  | { type: 'preview_done'; preview: Preview }
  | { type: 'preview_failed'; error: FriendlyError }
  | { type: 'run_start'; models: string[]; uploadSkipped: boolean }
  | { type: 'run_upload_progress'; fraction: number }
  | { type: 'run_update'; analysis: Analysis }
  | { type: 'run_done'; analysis: Analysis; source: ResultSource }
  | { type: 'run_failed'; error: FriendlyError; analysis?: Analysis | null }
  | { type: 'run_cancelled' }
  | { type: 'threshold_set'; value: number }
  | { type: 'refresh_start' }
  | { type: 'refresh_done'; analysis: Analysis }
  | { type: 'refresh_failed'; error: FriendlyError }
  /** A recompute was dropped (stale threshold or aborted); keep the shown analysis. */
  | { type: 'refresh_cancelled' }
  | { type: 'load_start'; source: ResultSource; demoId?: string | null }
  | { type: 'load_done'; analysis: Analysis; source: ResultSource }
  | { type: 'load_failed'; error: FriendlyError | null; notice?: string | null }
  | { type: 'review_start'; eventId: string }
  | { type: 'review_done'; analysis: Analysis | null }
  | { type: 'review_failed'; error: FriendlyError | null }
  | { type: 'deleted'; notice: string }
  | { type: 'notice'; notice: string | null }
  | { type: 'history'; history: HistoryEntry[] };

/** Fresh working state for a new file or a newly loaded analysis. */
function resetResults(state: WorkspaceState): WorkspaceState {
  return {
    ...state,
    fileError: null,
    preview: null,
    previewPhase: 'idle',
    previewProgress: 0,
    previewError: null,
    run: IDLE_RUN,
    analysis: null,
    source: null,
    demoId: null,
    refreshing: false,
    refreshError: null,
    loading: false,
    loadError: null,
    reviewingEventId: null,
    reviewError: null,
    notice: null,
  };
}

function stageModelKeys(keys: string[]) {
  return stageDefinitions(keys.map((key) => ({ key, label: key })));
}

function advanceRun(run: RunState, analysis: Analysis): RunState {
  const models = run.models.length ? run.models : analysis.settings.requested_models;
  const defs = stageModelKeys(models);
  let index = stageIndex(defs, analysis.stage ?? null);
  if (analysis.status === 'queued' && index < 0) index = stageIndex(defs, 'queued');
  if (analysis.status === 'completed') index = defs.length;
  return {
    ...run,
    phase: analysis.status === 'completed' ? 'completed' : 'processing',
    uploadProgress: 1,
    models,
    stage: analysis.stage ?? run.stage,
    // Unknown stage names keep the last known position; at least "uploaded".
    stageIndex: Math.max(run.stageIndex, index, 1),
    timings: analysis.stage_timings_ms ?? run.timings,
    analysisId: analysis.id,
  };
}

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case 'file_selected': {
      const replacing = state.file !== null || state.analysis !== null;
      const metadata = replacing && !state.keepMetadata ? emptyMetadata() : state.metadata;
      return {
        ...resetResults(state),
        file: action.file,
        localAudioUrl: action.url,
        metadata,
        threshold: state.threshold,
      };
    }
    case 'file_rejected': {
      const metadata =
        (state.file !== null || state.analysis !== null) && !state.keepMetadata
          ? emptyMetadata()
          : state.metadata;
      return {
        ...resetResults(state),
        file: null,
        localAudioUrl: null,
        metadata,
        fileError: action.message,
      };
    }
    case 'cleared':
      return {
        ...resetResults(state),
        file: null,
        localAudioUrl: null,
        metadata: state.keepMetadata ? state.metadata : emptyMetadata(),
        threshold: DEFAULT_THRESHOLD,
      };
    case 'metadata_changed':
      return { ...state, metadata: { ...state.metadata, ...action.patch } };
    case 'keep_metadata':
      return { ...state, keepMetadata: action.value };
    case 'preview_start':
      return {
        ...state,
        preview: null,
        previewPhase: 'uploading',
        previewProgress: 0,
        previewError: null,
        notice: null,
      };
    case 'preview_progress':
      return {
        ...state,
        previewProgress: action.fraction,
        previewPhase: action.fraction >= 1 ? 'processing' : 'uploading',
      };
    case 'preview_done':
      return { ...state, preview: action.preview, previewPhase: 'ready', previewProgress: 1 };
    case 'preview_failed':
      return { ...state, previewPhase: 'failed', previewError: action.error };
    case 'run_start':
      return {
        ...state,
        analysis: null,
        refreshError: null,
        reviewError: null,
        notice: null,
        loadError: null,
        run: {
          ...IDLE_RUN,
          phase: action.uploadSkipped ? 'processing' : 'uploading',
          uploadProgress: action.uploadSkipped ? 1 : 0,
          models: action.models,
          stage: action.uploadSkipped ? 'queued' : 'uploading',
          stageIndex: action.uploadSkipped ? 1 : 0,
        },
      };
    case 'run_upload_progress':
      return { ...state, run: { ...state.run, uploadProgress: action.fraction } };
    case 'run_update':
      return { ...state, loading: false, run: advanceRun(state.run, action.analysis) };
    case 'run_done':
      return {
        ...state,
        loading: false,
        run: advanceRun(state.run, action.analysis),
        analysis: action.analysis,
        source: action.source,
        threshold: action.analysis.settings.decision_threshold,
      };
    case 'run_failed': {
      const run = action.analysis ? advanceRun(state.run, action.analysis) : state.run;
      return {
        ...state,
        loading: false,
        run: { ...run, phase: 'failed', error: action.error },
      };
    }
    case 'run_cancelled':
      return { ...state, loading: false, run: IDLE_RUN };
    case 'threshold_set':
      return { ...state, threshold: action.value, refreshError: null };
    case 'refresh_start':
      return { ...state, refreshing: true, refreshError: null };
    case 'refresh_done':
      return { ...state, refreshing: false, analysis: action.analysis };
    case 'refresh_failed':
      return { ...state, refreshing: false, refreshError: action.error };
    case 'refresh_cancelled':
      return { ...state, refreshing: false };
    case 'load_start':
      return {
        ...resetResults(state),
        file: null,
        localAudioUrl: null,
        loading: true,
        source: action.source,
        demoId: action.demoId ?? null,
        threshold: DEFAULT_THRESHOLD,
      };
    case 'load_done':
      return {
        ...state,
        loading: false,
        analysis: action.analysis,
        source: action.source,
        threshold: action.analysis.settings.decision_threshold,
        run: { ...IDLE_RUN, phase: 'completed', analysisId: action.analysis.id },
      };
    case 'load_failed':
      return {
        ...state,
        loading: false,
        loadError: action.error,
        notice: action.notice ?? null,
        source: action.error ? state.source : null,
      };
    case 'review_start':
      return { ...state, reviewingEventId: action.eventId, reviewError: null };
    case 'review_done':
      return {
        ...state,
        reviewingEventId: null,
        analysis: action.analysis ?? state.analysis,
        // The review refetch replaced (and aborted) any threshold recompute in flight.
        refreshing: action.analysis ? false : state.refreshing,
      };
    case 'review_failed':
      return { ...state, reviewingEventId: null, reviewError: action.error };
    case 'deleted':
      return {
        ...resetResults(state),
        file: state.file,
        localAudioUrl: state.localAudioUrl,
        notice: action.notice,
      };
    case 'notice':
      return { ...state, notice: action.notice };
    case 'history':
      return { ...state, history: action.history };
    default:
      return state;
  }
}

import { describe, expect, it } from 'vitest';
import { buildAnalysis, pendingAnalysis, PREVIEW } from '../test/fixtures/analysis';
import { initialWorkspaceState, workspaceReducer, type WorkspaceState } from './workspaceReducer';

const file = new File(['x'], 'first.wav');

function withResults(): WorkspaceState {
  let state = initialWorkspaceState();
  state = workspaceReducer(state, { type: 'file_selected', file, url: 'blob:1' });
  state = workspaceReducer(state, { type: 'metadata_changed', patch: { siteName: 'Plot 3' } });
  state = workspaceReducer(state, { type: 'preview_done', preview: PREVIEW });
  state = workspaceReducer(state, { type: 'run_start', models: ['birdnet'], uploadSkipped: false });
  state = workspaceReducer(state, {
    type: 'run_done',
    analysis: buildAnalysis(),
    source: 'upload',
  });
  return state;
}

describe('workspace reducer', () => {
  it('resets preview, results, errors and progress on a new file', () => {
    let state = withResults();
    state = workspaceReducer(state, {
      type: 'refresh_failed',
      error: { code: 'network', title: 't', body: 'b', detail: null, action: 'retry' },
    });
    state = workspaceReducer(state, {
      type: 'file_selected',
      file: new File(['y'], 'second.wav'),
      url: 'blob:2',
    });
    expect(state.analysis).toBeNull();
    expect(state.preview).toBeNull();
    expect(state.run.phase).toBe('idle');
    expect(state.refreshError).toBeNull();
    expect(state.file?.name).toBe('second.wav');
    expect(state.metadata.siteName).toBe('');
  });

  it('keeps metadata when asked', () => {
    let state = withResults();
    state = workspaceReducer(state, { type: 'keep_metadata', value: true });
    state = workspaceReducer(state, { type: 'file_selected', file, url: 'blob:3' });
    expect(state.metadata.siteName).toBe('Plot 3');
  });

  it('a rejected file also clears previous results', () => {
    let state = withResults();
    state = workspaceReducer(state, { type: 'file_rejected', message: 'bad' });
    expect(state.analysis).toBeNull();
    expect(state.file).toBeNull();
    expect(state.fileError).toBe('bad');
  });

  it('advances stages monotonically and ignores unknown stage names', () => {
    let state = initialWorkspaceState();
    state = workspaceReducer(state, {
      type: 'run_start',
      models: ['birdnet'],
      uploadSkipped: false,
    });
    expect(state.run.stageIndex).toBe(0);
    state = workspaceReducer(state, {
      type: 'run_update',
      analysis: pendingAnalysis('model:birdnet'),
    });
    expect(state.run.stageIndex).toBe(5);
    state = workspaceReducer(state, { type: 'run_update', analysis: pendingAnalysis('mystery') });
    expect(state.run.stageIndex).toBe(5);
    state = workspaceReducer(state, { type: 'run_update', analysis: pendingAnalysis('quality') });
    expect(state.run.stageIndex).toBe(5);
  });

  it('adopts the applied threshold from a completed analysis', () => {
    let state = initialWorkspaceState();
    state = workspaceReducer(state, { type: 'threshold_set', value: 0.3 });
    state = workspaceReducer(state, {
      type: 'run_done',
      analysis: buildAnalysis({ threshold: 0.35 }),
      source: 'upload',
    });
    expect(state.threshold).toBe(0.35);
  });
});

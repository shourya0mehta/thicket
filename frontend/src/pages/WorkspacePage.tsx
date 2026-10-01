import { useEffect, useRef, useState } from 'react';
import { ControlsPanel } from '../components/intake/ControlsPanel';
import { EmptySteps } from '../components/intake/EmptySteps';
import { DemoPicker } from '../components/demo/DemoPicker';
import { ErrorCallout } from '../components/feedback/ErrorCallout';
import { ProcessingPanel } from '../components/progress/ProcessingPanel';
import { StageList } from '../components/progress/StageList';
import { PreviewSection } from '../components/results/PreviewSection';
import { ResultsView } from '../components/results/ResultsView';
import { Callout } from '../components/ui/Callout';
import { Button } from '../components/ui/Button';
import { Spinner } from '../components/ui/Spinner';
import { experimentalModelsEnabled, isDemoMode } from '../config';
import { useModels } from '../hooks/useModels';
import { defaultSelection, isSelectable, modelShortName, COMBINED_SELECTION } from '../lib/models';
import { buildStageItems } from '../lib/stages';
import { PlaybackProvider } from '../state/playback';
import type { Workspace } from '../state/useWorkspace';

export function WorkspacePage({ workspace }: { workspace: Workspace }) {
  const demo = isDemoMode();
  const experimental = experimentalModelsEnabled();
  const modelsState = useModels(!demo);
  const [selection, setSelection] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { state } = workspace;

  // Pick a sensible default model once the list arrives (or when the choice disappears).
  useEffect(() => {
    if (modelsState.status !== 'ready') return;
    const visible = modelsState.models.filter((m) => experimental || !m.experimental);
    const stillValid =
      selection === COMBINED_SELECTION
        ? experimental
        : visible.some((m) => m.key === selection && isSelectable(m));
    if (!stillValid) setSelection(defaultSelection(visible, experimental));
  }, [modelsState.status, modelsState.models, selection, experimental]);

  const running = state.run.phase === 'uploading' || state.run.phase === 'processing';
  const failed = state.run.phase === 'failed' && state.run.error;
  const duration =
    state.analysis?.recording?.duration_seconds ?? state.preview?.recording.duration_seconds ?? 0;
  const showEmpty =
    !demo &&
    !state.file &&
    !state.analysis &&
    !running &&
    !failed &&
    !state.loading &&
    !state.loadError;

  const stageModels = state.run.models.map((key) => ({
    key,
    label: modelShortName(key, modelsState.models),
  }));

  return (
    <PlaybackProvider src={workspace.audioSrc} fallbackDuration={duration}>
      <div className="space-y-6">
        <div className="max-w-3xl">
          <h1 className="text-[1.75rem] font-semibold leading-tight tracking-tight text-ink sm:text-[2.125rem]">
            Turn field recordings into transparent biodiversity evidence.
          </h1>
          <p className="mt-2 text-base text-muted">
            Species detection events with confidence, time stamps and provenance, ready to review
            and export.
          </p>
        </div>

        {demo ? (
          <DemoPicker activeId={state.demoId} onOpen={(id) => void workspace.loadDemo(id)} />
        ) : (
          <ControlsPanel
            workspace={workspace}
            modelsState={modelsState}
            selection={selection}
            onSelectModel={setSelection}
            experimentalEnabled={experimental}
            fileInputRef={fileInputRef}
          />
        )}

        {state.notice ? (
          <Callout
            tone="info"
            role="status"
            actions={
              <Button size="sm" variant="ghost" onClick={workspace.dismissNotice}>
                Dismiss
              </Button>
            }
          >
            {state.notice}
          </Callout>
        ) : null}

        {state.previewError ? (
          <ErrorCallout
            error={state.previewError}
            onRetry={workspace.retry}
            onChooseFile={() => fileInputRef.current?.click()}
          />
        ) : null}

        {state.loadError ? (
          <ErrorCallout error={state.loadError} onRetry={workspace.retry} />
        ) : null}

        {state.loading ? (
          <p className="flex items-center gap-2 text-sm text-muted" role="status">
            <Spinner size={14} /> Loading analysis...
          </p>
        ) : null}

        {running ? (
          <ProcessingPanel
            run={state.run}
            models={modelsState.models}
            filename={state.file?.name ?? null}
            onCancel={workspace.cancelRun}
          />
        ) : null}

        {failed && state.run.error ? (
          <div className="space-y-4">
            <ErrorCallout
              error={state.run.error}
              onRetry={workspace.retry}
              onChooseFile={() => fileInputRef.current?.click()}
            />
            {state.run.stageIndex > 0 ? (
              <details className="panel px-5 py-4">
                <summary className="cursor-pointer text-sm font-medium text-ink">
                  Where the analysis stopped
                </summary>
                <StageList
                  className="mt-3"
                  stages={buildStageItems({
                    models: stageModels,
                    activeIndex: state.run.stageIndex,
                    failed: true,
                    timings: state.run.timings,
                  })}
                />
              </details>
            ) : null}
          </div>
        ) : null}

        {state.analysis && state.run.phase !== 'failed' && !running ? (
          <ResultsView workspace={workspace} models={modelsState.models} />
        ) : state.preview && !running && !failed ? (
          <PreviewSection preview={state.preview} />
        ) : null}

        {showEmpty ? <EmptySteps /> : null}
      </div>
    </PlaybackProvider>
  );
}

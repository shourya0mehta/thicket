import type { ModelInfo } from '../../api/types';
import { modelShortName } from '../../lib/models';
import { buildStageItems, friendlyStageCopy, stageDefinitions } from '../../lib/stages';
import type { RunState } from '../../state/workspaceReducer';
import { Button } from '../ui/Button';
import { Panel } from '../ui/Panel';
import { StageList } from './StageList';

export function ProcessingPanel({
  run,
  models,
  filename,
  onCancel,
}: {
  run: RunState;
  models: ModelInfo[];
  filename: string | null;
  onCancel: () => void;
}) {
  const stageModels = run.models.map((key) => ({ key, label: modelShortName(key, models) }));
  const defs = stageDefinitions(stageModels);
  const activeIndex = run.phase === 'uploading' ? 0 : Math.max(1, run.stageIndex);
  const stages = buildStageItems({ models: stageModels, activeIndex, timings: run.timings });
  const activeKey = defs[activeIndex]?.key ?? null;
  const uploading = run.phase === 'uploading';

  return (
    <Panel labelledBy="processing-heading" className="animate-fade-in-up p-5 sm:p-6">
      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] md:gap-10">
        <div>
          <p className="eyebrow mb-1">Analysis in progress</p>
          <h2 id="processing-heading" className="text-lg font-semibold tracking-tight text-ink">
            Analyzing {filename ?? 'your recording'}
          </h2>
          <p className="mt-2 text-sm text-muted" aria-live="polite">
            {friendlyStageCopy(activeKey)}
          </p>
          {uploading ? (
            <div className="mt-4">
              <div className="flex justify-between text-xs text-muted">
                <span>Upload</span>
                <span className="num">{Math.round(run.uploadProgress * 100)}%</span>
              </div>
              <div
                className="mt-1 h-1.5 overflow-hidden rounded-full bg-mark/15"
                role="progressbar"
                aria-label="Upload progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(run.uploadProgress * 100)}
              >
                <div
                  className="h-full rounded-full bg-mark transition-[width] duration-200"
                  style={{ width: `${Math.round(run.uploadProgress * 100)}%` }}
                />
              </div>
            </div>
          ) : null}
          <p className="mt-4 text-xs text-muted">
            Most short recordings finish in under a minute. You can keep this page open; results
            appear here when every stage is done.
          </p>
          <Button variant="ghost" size="sm" className="-ml-3 mt-3" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        <StageList stages={stages} />
      </div>
    </Panel>
  );
}

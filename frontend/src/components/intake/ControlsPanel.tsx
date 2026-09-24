import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { ACCEPTED_EXTENSIONS } from '../../config';
import type { ModelsState } from '../../hooks/useModels';
import { formatBytes } from '../../lib/format';
import { modelDisplay, modelsForSelection, COMBINED_SELECTION } from '../../lib/models';
import { validateMetadata, type MetadataErrors } from '../../lib/validation';
import type { Workspace } from '../../state/useWorkspace';
import { Button } from '../ui/Button';
import { FileAudioIcon, UploadIcon, WaveformIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';
import { Spinner } from '../ui/Spinner';
import { FilePicker } from './FilePicker';
import { MetadataFields } from './MetadataFields';
import { ModelSelector } from './ModelSelector';

/** Show errors for fields the user has typed into, without waiting for submit. */
function pickTouchedErrors(
  errors: MetadataErrors,
  metadata: { latitude: string; longitude: string; capturedAt: string; timezone: string },
): MetadataErrors {
  const out: MetadataErrors = {};
  if (errors.latitude && metadata.latitude.trim() && !errors.latitude.startsWith('Add')) {
    out.latitude = errors.latitude;
  }
  if (errors.longitude && metadata.longitude.trim() && !errors.longitude.startsWith('Add')) {
    out.longitude = errors.longitude;
  }
  if (errors.capturedAt) out.capturedAt = errors.capturedAt;
  if (errors.timezone && metadata.timezone.trim()) out.timezone = errors.timezone;
  return out;
}

export function ControlsPanel({
  workspace,
  modelsState,
  selection,
  onSelectModel,
  experimentalEnabled,
  fileInputRef,
}: {
  workspace: Workspace;
  modelsState: ModelsState;
  selection: string | null;
  onSelectModel: (value: string) => void;
  experimentalEnabled: boolean;
  fileInputRef: RefObject<HTMLInputElement>;
}) {
  const { state } = workspace;
  const [showErrors, setShowErrors] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const formRef = useRef<HTMLDivElement>(null);

  const errors: MetadataErrors = useMemo(() => validateMetadata(state.metadata), [state.metadata]);
  const running = state.run.phase === 'uploading' || state.run.phase === 'processing';
  const previewBusy = state.previewPhase === 'uploading' || state.previewPhase === 'processing';
  const models = modelsForSelection(selection, modelsState.models);
  const hasInput = state.file !== null;
  const analysisId = state.analysis?.id ?? null;

  // Collapse the setup once an analysis starts or a result is shown; the
  // results are the working surface from then on.
  useEffect(() => {
    if (running || analysisId) setExpanded(false);
  }, [running, analysisId]);

  const compact = (running || analysisId !== null || state.loading) && !expanded;

  let runBlocker: string | null = null;
  if (!hasInput) runBlocker = 'Choose a recording to begin.';
  else if (modelsState.status === 'error') runBlocker = 'The model list could not be loaded.';
  else if (modelsState.status !== 'ready') runBlocker = 'Waiting for the model list.';
  else if (models.length === 0) runBlocker = 'No model is ready on this server.';

  const openPicker = () => fileInputRef.current?.click();

  const onRun = () => {
    if (Object.keys(errors).length > 0) {
      setShowErrors(true);
      // Move focus to the first invalid field so keyboard users land on it.
      window.setTimeout(() => {
        formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      }, 0);
      return;
    }
    setShowErrors(false);
    void workspace.runAnalysis(models);
  };

  const visibleErrors = showErrors ? errors : pickTouchedErrors(errors, state.metadata);

  // One hidden input for the whole page, opened through a ref. Never inside a label.
  const hiddenInput = (
    <input
      ref={fileInputRef}
      type="file"
      accept={`${ACCEPTED_EXTENSIONS.join(',')},audio/*`}
      hidden
      data-testid="file-input"
      onChange={(event) => {
        const chosen = event.target.files?.[0] ?? null;
        workspace.selectFile(chosen);
        // Allow choosing the same file again after clearing.
        event.target.value = '';
      }}
    />
  );

  if (compact) {
    const recording = state.analysis?.recording ?? state.preview?.recording ?? null;
    const filename = state.file?.name ?? recording?.filename ?? 'Recording';
    const selected = modelsState.models.find((m) => m.key === selection);
    const modelLabel =
      selection === COMBINED_SELECTION
        ? 'Combined models'
        : selected
          ? modelDisplay(selected).subtitle
          : null;
    const details = [
      state.metadata.siteName.trim() || recording?.site_name || null,
      state.file ? formatBytes(state.file.size) : null,
      modelLabel,
      state.source === 'history' ? 'Loaded from history' : null,
    ].filter(Boolean);
    return (
      <Panel labelledBy="controls-heading" className="px-5 py-4 sm:px-6">
        {hiddenInput}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-mark/10 text-accent">
              <FileAudioIcon size={20} />
            </span>
            <div className="min-w-0">
              <h2
                id="controls-heading"
                className="truncate text-sm font-semibold text-ink"
                title={filename}
              >
                {filename}
              </h2>
              {details.length ? (
                <p className="truncate text-xs text-muted">{details.join(' · ')}</p>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:shrink-0">
            <Button variant="ghost" size="sm" onClick={() => setExpanded(true)} disabled={running}>
              Edit setup
            </Button>
            <Button variant="secondary" size="sm" onClick={openPicker} disabled={running}>
              <UploadIcon size={14} />
              New recording
            </Button>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel labelledBy="controls-heading" className="p-5 sm:p-6">
      {hiddenInput}
      <h2 id="controls-heading" className="sr-only">
        Set up an analysis
      </h2>
      <div ref={formRef} className="grid gap-6 lg:grid-cols-12 lg:gap-8">
        <div className="flex flex-col lg:col-span-4">
          <p className="eyebrow mb-3">Recording</p>
          <FilePicker
            onPick={openPicker}
            file={state.file}
            fileError={state.fileError}
            preview={state.preview}
            disabled={running}
            onFile={workspace.selectFile}
          />
        </div>

        <fieldset className="min-w-0 lg:col-span-5">
          <legend className="eyebrow mb-3">
            Where and when{' '}
            <span className="font-normal normal-case tracking-normal">(optional)</span>
          </legend>
          <MetadataFields
            metadata={state.metadata}
            errors={visibleErrors}
            onChange={workspace.setMetadata}
            keepMetadata={state.keepMetadata}
            onKeepMetadata={workspace.setKeepMetadata}
            disabled={running}
          />
        </fieldset>

        <fieldset className="min-w-0 lg:col-span-3">
          <legend className="eyebrow mb-3">Model</legend>
          <ModelSelector
            modelsState={modelsState}
            selection={selection}
            onSelect={onSelectModel}
            experimentalEnabled={experimentalEnabled}
          />
        </fieldset>
      </div>

      <div className="mt-6 flex flex-col gap-4 border-t border-line pt-5 md:flex-row md:items-center md:justify-between">
        <p className="text-xs text-muted" id="run-hint" aria-live="polite">
          {runBlocker ??
            'Analysis runs on your Thicket server. Uploaded audio is not kept once the analysis finishes.'}
        </p>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center sm:justify-end">
          <Button
            variant="primary"
            onClick={onRun}
            disabled={runBlocker !== null || running}
            aria-describedby="run-hint"
            className="col-span-2 sm:order-3"
          >
            {running ? <Spinner size={14} /> : null}
            {running ? 'Analyzing...' : 'Run analysis'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => void workspace.generatePreview()}
            disabled={!hasInput || running || previewBusy}
            className="sm:order-2"
          >
            {previewBusy ? <Spinner size={14} /> : <WaveformIcon size={16} />}
            {state.previewPhase === 'uploading'
              ? `Uploading ${Math.round(state.previewProgress * 100)}%`
              : state.previewPhase === 'processing'
                ? 'Generating...'
                : 'Generate spectrogram'}
          </Button>
          <Button
            variant="ghost"
            onClick={workspace.clear}
            disabled={!hasInput && !state.analysis && !state.fileError}
            className="sm:order-1"
          >
            Clear
          </Button>
        </div>
      </div>
    </Panel>
  );
}

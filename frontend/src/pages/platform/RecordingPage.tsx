import { useEffect, useRef } from 'react';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { AnalysisStatusPill, QualityPill } from '../../components/platform/pills';
import { ErrorState, Facts, LoadingState, PageHeader } from '../../components/platform/primitives';
import { ProcessingPanel } from '../../components/progress/ProcessingPanel';
import { ResultsView } from '../../components/results/ResultsView';
import { Callout } from '../../components/ui/Callout';
import { useModels } from '../../hooks/useModels';
import { useResource } from '../../hooks/useResource';
import { formatDateTime, formatDuration, formatCoordinate } from '../../lib/format';
import { orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';
import { PlaybackProvider } from '../../state/playback';
import type { Workspace } from '../../state/useWorkspace';

const SOURCE_LABEL = {
  filename: 'Parsed from the file name',
  file_metadata: 'Read from the file metadata',
  user: 'Entered by hand',
  browser_last_modified: 'Taken from the file date in the browser',
  unknown: 'Unknown',
} as const;

export function RecordingPage({
  recordingId,
  workspace,
}: {
  recordingId: string;
  workspace: Workspace;
}) {
  const { api, demo } = usePlatform();
  const { org, permissions, siteName, recorderLabel } = useOrg();
  const recording = useResource(
    (signal) => api.getRecording(recordingId, signal),
    `recording:${recordingId}`,
  );
  const modelsState = useModels(!demo);
  const loadedFor = useRef<string | null>(null);
  const analysisId = recording.data?.analysis_id ?? null;

  useEffect(() => {
    if (!analysisId || loadedFor.current === analysisId) return;
    loadedFor.current = analysisId;
    if (demo) void workspace.loadDemo(analysisId);
    else void workspace.loadAnalysis(analysisId);
  }, [analysisId, demo, workspace]);

  const r = recording.data;
  const { state } = workspace;
  const running = state.run.phase === 'uploading' || state.run.phase === 'processing';
  const duration = state.analysis?.recording?.duration_seconds ?? r?.duration_seconds ?? 0;
  const showResults =
    state.analysis !== null &&
    (state.analysis.id === analysisId || (demo && state.demoId === analysisId)) &&
    !state.loading &&
    !running;

  if (recording.error) {
    return (
      <ErrorState
        error={recording.error}
        onRetry={recording.reload}
        backHref={orgHref(org.id, 'recordings')}
        backLabel="Back to recordings"
      />
    );
  }
  if (!r) return <LoadingState label="Loading the recording..." />;

  return (
    <PlaybackProvider src={workspace.audioSrc} fallbackDuration={duration}>
      <div className="space-y-6">
        <PageHeader
          eyebrow={
            <a href={orgHref(org.id, 'recordings')} className="hover:underline">
              Recordings
            </a>
          }
          title={r.filename}
          description={
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>
                {r.captured_at
                  ? `Captured ${formatDateTime(r.captured_at, r.timezone)}`
                  : 'Capture time unknown'}
              </span>
              <span>{formatDuration(r.duration_seconds)}</span>
              {r.site_id ? (
                <a className="link" href={orgHref(org.id, 'site', r.site_id)}>
                  {r.site_name ?? siteName(r.site_id)}
                </a>
              ) : (
                <span>No site</span>
              )}
              <QualityPill status={r.quality_status} />
              <AnalysisStatusPill status={r.analysis_status} />
            </span>
          }
        />

        <div className="panel p-5 sm:p-6">
          <Facts
            items={[
              { label: 'Capture time source', value: SOURCE_LABEL[r.captured_at_source] },
              { label: 'Time zone', value: r.timezone ?? 'Not set' },
              {
                label: 'Location',
                value:
                  r.latitude != null && r.longitude != null
                    ? `${formatCoordinate(r.latitude, 'lat')}, ${formatCoordinate(r.longitude, 'lon')}`
                    : 'Not provided',
              },
              {
                label: 'Recorder',
                value: r.recorder_id ? (
                  <a className="link" href={orgHref(org.id, 'recorder', r.recorder_id)}>
                    {recorderLabel(r.recorder_id)}
                  </a>
                ) : (
                  'Not linked'
                ),
              },
              {
                label: 'Battery',
                value:
                  r.telemetry?.battery_v != null ? `${r.telemetry.battery_v.toFixed(2)} V` : 'n/a',
              },
              {
                label: 'Temperature',
                value:
                  r.telemetry?.temperature_c != null
                    ? `${r.telemetry.temperature_c.toFixed(1)} C`
                    : 'n/a',
              },
              { label: 'Gain', value: r.telemetry?.gain ?? 'n/a' },
              { label: 'Uploaded', value: formatDateTime(r.created_at) },
              {
                label: 'Threshold at upload',
                value:
                  r.decision_threshold == null
                    ? 'n/a'
                    : `${Math.round(r.decision_threshold * 100)}%`,
              },
            ]}
          />
        </div>

        {!analysisId ? (
          <Callout tone="info" title="No analysis for this recording">
            The file was stored but no analysis finished. If the batch failed, re-upload the file.
          </Callout>
        ) : null}
        {state.loadError && analysisId ? (
          <ErrorCallout error={state.loadError} onRetry={workspace.retry} />
        ) : null}
        {state.loading ? <LoadingState label="Loading the analysis..." /> : null}
        {running ? (
          <ProcessingPanel
            run={state.run}
            models={modelsState.models}
            filename={r.filename}
            onCancel={workspace.cancelRun}
          />
        ) : null}
        {state.run.phase === 'failed' && state.run.error && analysisId ? (
          <ErrorCallout error={state.run.error} onRetry={workspace.retry} />
        ) : null}
        {showResults ? (
          <ResultsView
            workspace={workspace}
            models={modelsState.models}
            reviewDisabledReason={
              permissions.canReview
                ? null
                : 'Your role is view-only; reviewers can accept or reject events.'
            }
            allowDelete={permissions.canManage}
          />
        ) : null}
      </div>
    </PlaybackProvider>
  );
}

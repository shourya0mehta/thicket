import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { resolveApiUrl } from '../../api/client';
import type { Analysis, ModelInfo } from '../../api/types';
import { isDemoMode } from '../../config';
import {
  countedSpecies,
  excludedWildlifeCount,
  hasNoDetections,
  hasValidCoordinates,
  listedEvents,
  modelLabelForRun,
  otherSoundGroups,
  unlikelyGroups,
} from '../../lib/analysis';
import { formatDateTime } from '../../lib/format';
import { modelDisplay, sanitizeCopy } from '../../lib/models';
import { round2, thresholdBounds, thresholdPercent } from '../../lib/threshold';
import type { Workspace } from '../../state/useWorkspace';
import { ErrorCallout } from '../feedback/ErrorCallout';
import { Callout } from '../ui/Callout';
import { MapPinIcon } from '../ui/icons';
import { Spinner } from '../ui/Spinner';
import { TabPanel, Tabs, type TabDef } from '../ui/Tabs';
import { AcousticIndicesCard } from './AcousticIndicesCard';
import { EventsList } from './EventsList';
import { ExportBar } from './ExportBar';
import { NoDetections } from './NoDetections';
import { OtherSounds } from './OtherSounds';
import { ProvenancePanel } from './ProvenancePanel';
import { QualityBadge, QualityPanel } from './QualityPanel';
import { RecordingCard } from './RecordingCard';
import { SpeciesFrequencyChart } from './SpeciesFrequencyChart';
import { SpeciesTable } from './SpeciesTable';
import { SummaryPanel } from './SummaryPanel';
import { ThresholdControl } from './ThresholdControl';
import { TimelineView } from './TimelineView';
import { UnlikelySection } from './UnlikelySection';

const MapView = lazy(() => import('./MapView'));

type TabKey = 'results' | 'timeline' | 'map' | 'methods';

function modelSummary(analysis: Analysis, models: ModelInfo[]): string {
  if (analysis.model_runs.length) {
    return analysis.model_runs.map((r) => modelLabelForRun(r)).join(' + ');
  }
  return analysis.settings.requested_models
    .map((key) => {
      const info = models.find((m) => m.key === key);
      return info ? modelDisplay(info).subtitle : key;
    })
    .join(' + ');
}

export function ResultsView({
  workspace,
  models,
  demoAttribution,
  reviewDisabledReason = null,
  allowDelete = true,
}: {
  workspace: Workspace;
  models: ModelInfo[];
  demoAttribution?: string | null;
  /** Platform roles below reviewer cannot accept or reject events. */
  reviewDisabledReason?: string | null;
  /** Platform roles below manager cannot delete. */
  allowDelete?: boolean;
}) {
  const { state } = workspace;
  const analysis = state.analysis as Analysis;
  const [tab, setTab] = useState<TabKey>('results');
  const recording = analysis.recording;
  const showMap = hasValidCoordinates(recording);
  const demo = isDemoMode() || state.source === 'demo';

  useEffect(() => {
    if (tab === 'map' && !showMap) setTab('results');
  }, [tab, showMap]);

  const species = useMemo(() => countedSpecies(analysis), [analysis]);
  const events = useMemo(() => listedEvents(analysis), [analysis]);
  const other = useMemo(() => otherSoundGroups(analysis), [analysis]);
  const unlikely = useMemo(() => unlikelyGroups(analysis), [analysis]);
  const empty = hasNoDetections(analysis);
  const applied = analysis.settings.decision_threshold;
  const { min } = thresholdBounds(analysis.settings.raw_threshold);
  const dimmed = state.refreshing;

  const spectrogramUrl = resolveApiUrl(analysis.assets.spectrogram_url);
  const minHz = analysis.assets.spectrogram_min_hz ?? 0;
  const maxHz = analysis.assets.spectrogram_max_hz ?? 16000;

  const tabs: Array<TabDef<TabKey>> = [
    { id: 'results', label: 'Results' },
    { id: 'timeline', label: 'Timeline' },
    ...(showMap ? [{ id: 'map' as const, label: 'Map' }] : []),
    { id: 'methods', label: 'Methods' },
  ];

  const qualityReasons = analysis.quality
    ? [
        ...analysis.quality.checks.filter((c) => c.status === 'fail').map((c) => c.message),
        ...analysis.quality.warnings,
      ].map(sanitizeCopy)
    : [];
  const title = recording?.site_name || recording?.filename || 'Analysis';
  const lowerTo = applied - min > 0.001 ? round2(Math.max(min, applied - 0.15)) : null;

  return (
    <section aria-labelledby="results-heading" className="animate-fade-in-up space-y-5">
      <div className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="eyebrow mb-1">Results</p>
            <h2
              id="results-heading"
              className="break-words text-xl font-semibold tracking-tight text-ink sm:text-2xl"
            >
              {title}
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted">
              {recording?.site_name && recording.filename ? (
                <span>{recording.filename}</span>
              ) : null}
              <span>
                {recording?.captured_at
                  ? `Recorded ${formatDateTime(recording.captured_at, recording.timezone)}`
                  : 'Recording date not provided'}
              </span>
              <span className="inline-flex items-center gap-1" data-testid="location-status">
                <MapPinIcon size={14} className="text-subtle" />
                {showMap ? 'Location on map' : 'Location not provided'}
              </span>
              <span>{modelSummary(analysis, models)}</span>
              {analysis.quality ? <QualityBadge status={analysis.quality.status} /> : null}
            </div>
            {demoAttribution ? (
              <p className="mt-2 text-xs text-muted">Recording: {demoAttribution}</p>
            ) : null}
          </div>
          <ThresholdControl
            className="w-full lg:w-[21rem] lg:shrink-0"
            value={state.threshold}
            applied={applied}
            rawThreshold={analysis.settings.raw_threshold}
            onChange={workspace.setThreshold}
            updating={state.refreshing}
            failed={state.refreshError !== null}
          />
        </div>
      </div>

      {analysis.quality?.status === 'not_usable' ? (
        <Callout tone="warn" role="status" title="Audio quality is too low for reliable detection">
          <p>
            Results are shown for transparency but may miss species or include false detections.
          </p>
          {qualityReasons.length ? (
            <ul className="mt-1 list-disc pl-5">
              {qualityReasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
        </Callout>
      ) : null}

      {analysis.warnings.length ? (
        <Callout tone="info" title="Notes from the analysis">
          <ul className="list-disc pl-5">
            {analysis.warnings.map((w) => (
              <li key={w}>{sanitizeCopy(w)}</li>
            ))}
          </ul>
        </Callout>
      ) : null}

      {state.refreshError ? (
        <ErrorCallout
          error={{ ...state.refreshError, action: 'retry' }}
          onRetry={workspace.retryRefresh}
        />
      ) : null}
      {state.reviewError ? <ErrorCallout error={state.reviewError} /> : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs tabs={tabs} value={tab} onChange={setTab} label="Result views" idPrefix="results" />
        {state.refreshing ? (
          <span className="flex items-center gap-2 text-xs text-muted" aria-hidden="true">
            <Spinner size={12} /> Recomputing at {thresholdPercent(state.threshold)}
          </span>
        ) : null}
      </div>

      {tab === 'results' ? (
        <TabPanel idPrefix="results" id="results" className="space-y-5">
          <div className="grid gap-5 lg:grid-cols-12">
            <div className="min-w-0 lg:col-span-7">
              {recording ? (
                <RecordingCard
                  recording={recording}
                  spectrogramUrl={spectrogramUrl}
                  minHz={minHz}
                  maxHz={maxHz}
                  headingId="recording-heading"
                  audioUnavailableReason={
                    demo
                      ? 'Audio for this demo is not available.'
                      : 'Audio is not stored on the server. Choose the original file to listen.'
                  }
                />
              ) : null}
            </div>
            <div className="min-w-0 space-y-5 lg:col-span-5">
              <SummaryPanel analysis={analysis} dimmed={dimmed} />
              {empty ? (
                <NoDetections
                  threshold={applied}
                  lowerTo={lowerTo}
                  onLower={workspace.setThreshold}
                  excluded={excludedWildlifeCount(analysis)}
                />
              ) : (
                <SpeciesFrequencyChart species={species} threshold={applied} dimmed={dimmed} />
              )}
            </div>
          </div>

          {!empty ? <SpeciesTable analysis={analysis} species={species} dimmed={dimmed} /> : null}

          {other.length || unlikely.length || analysis.quality?.speech_detected ? (
            <div className="grid items-start gap-5 lg:grid-cols-2">
              <OtherSounds
                groups={other}
                speechDetected={analysis.quality?.speech_detected ?? false}
              />
              <UnlikelySection groups={unlikely} />
            </div>
          ) : null}

          {events.length ? (
            <EventsList
              events={events}
              threshold={applied}
              reviewingEventId={state.reviewingEventId}
              reviewDisabledReason={
                demo ? 'Review is turned off in the demo.' : reviewDisabledReason
              }
              onReview={(id, status) => void workspace.review(id, status)}
              dimmed={dimmed}
            />
          ) : null}

          <div className="grid gap-5 lg:grid-cols-12">
            <div className="min-w-0 lg:col-span-5">
              <QualityPanel quality={analysis.quality} />
            </div>
            <div className="min-w-0 lg:col-span-7">
              <AcousticIndicesCard indices={analysis.acoustic_indices} />
            </div>
          </div>
        </TabPanel>
      ) : null}

      {tab === 'timeline' ? (
        <TabPanel idPrefix="results" id="timeline">
          <TimelineView
            analysis={analysis}
            spectrogramUrl={spectrogramUrl}
            minHz={minHz}
            maxHz={maxHz}
          />
        </TabPanel>
      ) : null}

      {tab === 'map' && showMap ? (
        <TabPanel idPrefix="results" id="map">
          <Suspense
            fallback={
              <p className="flex items-center gap-2 text-sm text-muted">
                <Spinner size={14} /> Loading map...
              </p>
            }
          >
            <MapView analysis={analysis} />
          </Suspense>
        </TabPanel>
      ) : null}

      {tab === 'methods' ? (
        <TabPanel idPrefix="results" id="methods">
          <ProvenancePanel analysis={analysis} />
        </TabPanel>
      ) : null}

      <ExportBar
        analysis={analysis}
        clientSide={demo}
        onDelete={demo || !allowDelete ? undefined : workspace.deleteCurrent}
      />
    </section>
  );
}

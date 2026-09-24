import type { ReactNode } from 'react';
import type { Analysis } from '../../api/types';
import { API_SCHEMA_VERSION } from '../../api/types';
import { formatDateTime, formatHz, formatMs, formatSeconds, shortHash } from '../../lib/format';
import { modelLabelForRun } from '../../lib/analysis';
import { modelShortName } from '../../lib/models';
import { thresholdPercent } from '../../lib/threshold';
import { MethodsExplainer } from '../methods/MethodsExplainer';
import { Badge } from '../ui/Badge';
import { FlaskIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';

function Facts({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2.5 text-sm md:grid-cols-2 lg:grid-cols-1">
      {items.map(([term, value]) => (
        <div key={term} className="flex min-w-0 justify-between gap-4 border-b border-line pb-2.5">
          <dt className="shrink-0 text-muted">{term}</dt>
          <dd className="num min-w-0 truncate text-right font-medium text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const STAGE_LABELS: Record<string, string> = {
  queued: 'Waiting in queue',
  normalizing: 'Normalizing audio',
  quality: 'Checking audio quality',
  spectrogram: 'Generating spectrogram',
  consolidating: 'Consolidating detections',
  metrics: 'Computing metrics',
  total: 'Total processing',
};

function stageLabel(key: string): string {
  if (key.startsWith('model:')) return `Running ${modelShortName(key.slice(6))}`;
  if (STAGE_LABELS[key]) return STAGE_LABELS[key];
  const text = key.replace(/[_-]+/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function ProvenancePanel({ analysis }: { analysis: Analysis }) {
  const s = analysis.settings;
  const timings = Object.entries(analysis.stage_timings_ms ?? {});
  const firstRun = analysis.model_runs[0];

  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <Panel labelledBy="methods-heading" className="p-5 sm:p-6 lg:col-span-7">
        <p className="eyebrow mb-1">Methods</p>
        <h3 id="methods-heading" className="text-base font-semibold tracking-tight text-ink">
          How these results were produced
        </h3>
        <MethodsExplainer
          className="mt-5"
          windowSeconds={firstRun?.window_seconds ?? 3}
          hopSeconds={s.hop_seconds}
          rawThreshold={s.raw_threshold}
          decisionThreshold={s.decision_threshold}
          mergeGapSeconds={s.merge_gap_seconds}
        />
      </Panel>

      <div className="space-y-5 lg:col-span-5">
        <Panel labelledBy="provenance-heading" className="p-5 sm:p-6">
          <p className="eyebrow mb-1">Provenance</p>
          <h3 id="provenance-heading" className="text-base font-semibold tracking-tight text-ink">
            Settings recorded with this analysis
          </h3>
          <div className="mt-4">
            <Facts
              items={[
                ['Decision threshold', thresholdPercent(s.decision_threshold)],
                ['Ingestion floor', thresholdPercent(s.raw_threshold)],
                ['Merge gap', formatSeconds(s.merge_gap_seconds)],
                ['Hop', formatSeconds(s.hop_seconds)],
                [
                  'Range and season filter',
                  s.location_filter
                    ? `On, at ${thresholdPercent(s.location_filter_threshold)}`
                    : 'Off',
                ],
                ['Requested models', s.requested_models.join(', ') || 'n/a'],
                ['Software version', analysis.software_version],
                ['Schema version', analysis.schema_version ?? API_SCHEMA_VERSION],
                [
                  'Analysis ID',
                  <span key="id" title={analysis.id}>
                    {shortHash(analysis.id, 18)}
                  </span>,
                ],
                ['Created', formatDateTime(analysis.created_at)],
                ['Completed', formatDateTime(analysis.completed_at)],
                [
                  'Recording checksum',
                  <span key="sha" title={analysis.recording?.checksum_sha256}>
                    {shortHash(analysis.recording?.checksum_sha256)}
                  </span>,
                ],
              ]}
            />
          </div>
        </Panel>

        {analysis.model_runs.map((run) => (
          <Panel key={run.id} labelledBy={`run-${run.id}`} className="p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="eyebrow mb-1">Model run</p>
                <h3
                  id={`run-${run.id}`}
                  className="text-base font-semibold tracking-tight text-ink"
                >
                  {modelLabelForRun(run)}
                </h3>
              </div>
              {run.experimental ? (
                <Badge tone="info" icon={<FlaskIcon size={12} />}>
                  Experimental
                </Badge>
              ) : null}
            </div>
            <div className="mt-4">
              <Facts
                items={[
                  ['Adapter', run.adapter],
                  [
                    'Model SHA-256',
                    <span key="sha" title={run.model_sha256 ?? undefined}>
                      {shortHash(run.model_sha256)}
                    </span>,
                  ],
                  ['Taxa', run.taxa.join(', ')],
                  [
                    'Window / hop',
                    `${formatSeconds(run.window_seconds)} / ${formatSeconds(run.hop_seconds)}`,
                  ],
                  ['Model sample rate', formatHz(run.required_sample_rate_hz)],
                  ['Ingestion floor', thresholdPercent(run.raw_threshold)],
                  ['Windows analyzed', run.n_windows.toLocaleString('en-US')],
                  ['Runtime', formatMs(run.runtime_ms)],
                  [
                    'Run ID',
                    <span key="rid" title={run.id}>
                      {shortHash(run.id, 18)}
                    </span>,
                  ],
                ]}
              />
            </div>
          </Panel>
        ))}

        {timings.length ? (
          <Panel labelledBy="timings-heading" className="p-5 sm:p-6">
            <p className="eyebrow mb-1">Pipeline</p>
            <h3 id="timings-heading" className="text-base font-semibold tracking-tight text-ink">
              Stage timings
            </h3>
            <div className="mt-4">
              <Facts items={timings.map(([key, ms]) => [stageLabel(key), formatMs(ms)])} />
            </div>
          </Panel>
        ) : null}
      </div>
    </div>
  );
}

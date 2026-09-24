import type { ReactNode } from 'react';
import type { Analysis } from '../../api/types';
import { cx } from '../../lib/cx';
import { formatDateTime, formatDuration, formatInteger, formatNumber } from '../../lib/format';
import { thresholdPercent } from '../../lib/threshold';
import { InfoTip } from '../ui/InfoTip';
import { Panel } from '../ui/Panel';

const NOT_A_CENSUS = 'Derived from acoustic detection events, not a census or abundance estimate.';

function Stat({
  label,
  value,
  info,
  size = 'md',
  className,
  testId,
}: {
  label: string;
  value: ReactNode;
  info: ReactNode;
  size?: 'lg' | 'md';
  className?: string;
  testId?: string;
}) {
  return (
    <div className={cx('well min-w-0 px-3.5 py-3', className)} data-testid={testId}>
      <dt className="flex items-center gap-1 text-xs font-medium text-muted">
        <span>{label}</span>
        <InfoTip label={`About ${label.toLowerCase()}`}>
          {info} <span className="font-medium">{NOT_A_CENSUS}</span>
        </InfoTip>
      </dt>
      <dd
        className={cx(
          'mt-1 font-semibold tracking-tight text-ink',
          size === 'lg' ? 'text-[1.75rem] leading-9' : 'text-xl leading-7',
        )}
      >
        {value}
      </dd>
    </div>
  );
}

export function SummaryPanel({ analysis, dimmed }: { analysis: Analysis; dimmed?: boolean }) {
  const m = analysis.metrics;
  const duration = analysis.recording?.duration_seconds ?? 0;
  const threshold = analysis.settings.decision_threshold;

  return (
    <Panel labelledBy="summary-heading" className="p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="eyebrow mb-1">Biodiversity summary</p>
          <h3 id="summary-heading" className="text-base font-semibold tracking-tight text-ink">
            Detection-derived metrics
          </h3>
        </div>
        <p className="text-xs text-muted">
          At the <span className="font-semibold text-ink">{thresholdPercent(threshold)}</span>{' '}
          decision threshold
        </p>
      </div>

      <dl
        className={cx(
          'grid grid-cols-2 gap-2.5 transition-opacity',
          dimmed ? 'opacity-60' : 'opacity-100',
        )}
        aria-busy={dimmed || undefined}
      >
        <Stat
          label="Species richness"
          size="lg"
          testId="metric-richness"
          value={m ? formatInteger(m.species_richness) : 'n/a'}
          info="Number of species with at least one detection event above the decision threshold."
        />
        <Stat
          label="Detection events"
          size="lg"
          testId="metric-events"
          value={m ? formatInteger(m.total_detection_events) : 'n/a'}
          info="Stretches of audio in which a species was detected, after merging adjacent windows. Events are not individuals: one animal can produce many events."
        />
        <Stat
          label="Shannon (H′)"
          testId="metric-shannon"
          value={m ? formatNumber(m.shannon_index, 2) : 'n/a'}
          info="H′ = −Σ pᵢ ln pᵢ, where pᵢ is each species' share of detection events (natural log). Higher values mean detection events are spread across more species."
        />
        <Stat
          label="Pielou (J′)"
          testId="metric-pielou"
          value={m ? formatNumber(m.pielou_evenness, 2) : 'n/a'}
          info="J′ = H′ / ln S. Near 1 when detection events are spread evenly across species; 0 when fewer than two species are detected."
        />
        <Stat
          label="Gini-Simpson"
          testId="metric-simpson"
          value={m ? formatNumber(m.simpson_diversity, 2) : 'n/a'}
          info="1 − Σ pᵢ². The probability that two randomly chosen detection events belong to different species."
        />
        <Stat
          label="Events per minute"
          testId="metric-epm"
          value={m ? formatNumber(m.events_per_minute, 1) : 'n/a'}
          info="Detection events divided by the recording length in minutes. Useful for comparing recordings of different lengths from the same site."
        />
        <Stat
          label="Dominant species"
          testId="metric-dominant"
          value={
            m?.dominant_species ? (
              <span className="block min-w-0">
                <span className="block break-words text-lg leading-6">
                  {m.dominant_species.common_name}
                </span>
                <span className="sci mt-0.5 block break-words text-xs font-normal text-muted">
                  {m.dominant_species.scientific_name}
                </span>
              </span>
            ) : (
              <span className="text-lg text-muted">None</span>
            )
          }
          info="The species with the most detection events. Loud or frequent callers produce more events, so this is not necessarily the most common species."
        />
        <Stat
          label="Recording length"
          testId="metric-duration"
          value={formatDuration(duration)}
          info="Length of the decoded audio. Metrics per minute use this duration."
        />
      </dl>

      <p className="mt-4 text-xs text-muted">
        Analyzed {formatDateTime(analysis.completed_at ?? analysis.created_at)}
        {m ? (
          <>
            {' · '}
            {formatInteger(m.raw_detection_count)} contributing windows
          </>
        ) : null}
      </p>
    </Panel>
  );
}

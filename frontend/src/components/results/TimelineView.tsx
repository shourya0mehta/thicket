import { useId, useMemo, useState, type ReactNode } from 'react';
import type { Analysis, DetectionEvent, Taxon } from '../../api/types';
import { buildTimelineLanes, eventsAtTime, isRejected, listedEvents } from '../../lib/analysis';
import { cx } from '../../lib/cx';
import { formatClockPrecise, formatPercent, pluralize } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { snapThreshold, thresholdPercent } from '../../lib/threshold';
import { useElementWidth } from '../../hooks/useElementWidth';
import { usePlayback, usePlaybackTime } from '../../state/playbackContext';
import { TaxonIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';
import { AudioControls } from './AudioControls';
import { Playhead, Spectrogram, TimeAxis } from './Spectrogram';

const ROW_H = 22;
const LANE_PAD = 8;
const GUTTER = 'w-24 sm:w-44';

/** Fill opacity from confidence: faint near the threshold, solid near 100%. */
function confidenceAlpha(confidence: number, threshold: number): number {
  const span = Math.max(0.05, 1 - threshold);
  const t = Math.min(1, Math.max(0, (confidence - threshold) / span));
  return 0.28 + 0.72 * t;
}

function Chip({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cx(
        'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors',
        pressed
          ? 'border-mark bg-mark text-white dark:text-forest-950'
          : 'border-line-strong bg-raised text-ink hover:border-mark/60',
      )}
    >
      {children}
    </button>
  );
}

function EventBar({
  event,
  duration,
  row,
  threshold,
  active,
  selected,
  onSelect,
  trackWidth,
}: {
  event: DetectionEvent;
  duration: number;
  row: number;
  threshold: number;
  active: boolean;
  selected: boolean;
  onSelect: (event: DetectionEvent) => void;
  trackWidth: number;
}) {
  const left = (event.start_seconds / duration) * 100;
  const width = ((event.end_seconds - event.start_seconds) / duration) * 100;
  const alpha = confidenceAlpha(event.max_confidence, threshold);
  const rejected = isRejected(event);
  const showNumber = (width / 100) * trackWidth >= 26;
  const label = `${event.common_name}, ${formatClockPrecise(event.start_seconds)} to ${formatClockPrecise(event.end_seconds)}, max confidence ${formatPercent(event.max_confidence)}${rejected ? ', rejected by reviewer' : ''}`;
  return (
    <button
      type="button"
      onClick={() => onSelect(event)}
      aria-label={label}
      title={label}
      aria-current={selected ? 'true' : undefined}
      data-testid="timeline-bar"
      className={cx(
        'group absolute flex min-w-[6px] items-center justify-center overflow-hidden rounded-[5px] border text-[0.625rem] font-semibold transition-shadow',
        rejected ? 'border-dashed border-muted' : 'border-mark',
        selected || active
          ? 'z-10 ring-2 ring-ink/70 ring-offset-1 ring-offset-transparent'
          : 'hover:ring-2 hover:ring-mark/40',
      )}
      style={{
        left: `${left}%`,
        width: `${width}%`,
        top: LANE_PAD / 2 + row * ROW_H + 2,
        height: ROW_H - 4,
        backgroundColor: rejected ? 'transparent' : `rgb(var(--mark) / ${alpha.toFixed(2)})`,
      }}
    >
      {showNumber ? (
        <span
          className={cx(
            'num pointer-events-none px-1',
            rejected ? 'text-muted' : alpha > 0.62 ? 'text-white dark:text-forest-950' : 'text-ink',
          )}
          aria-hidden="true"
        >
          {Math.round(event.max_confidence * 100)}
        </span>
      ) : null}
    </button>
  );
}

export function TimelineView({
  analysis,
  spectrogramUrl,
  minHz,
  maxHz,
}: {
  analysis: Analysis;
  spectrogramUrl: string | null;
  minHz: number;
  maxHz: number;
}) {
  const { selectEvent, selectedEventId, playing } = usePlayback();
  const time = usePlaybackTime();
  const sliderId = useId();
  const [trackRef, trackWidth] = useElementWidth<HTMLDivElement>(600);
  const duration = analysis.recording?.duration_seconds ?? 0;
  const threshold = analysis.settings.decision_threshold;

  const baseEvents = useMemo(() => listedEvents(analysis), [analysis]);
  const speciesOptions = useMemo(() => buildTimelineLanes(baseEvents), [baseEvents]);
  const taxaOptions = useMemo(
    () => [...new Set(baseEvents.map((e) => e.taxon))] as Taxon[],
    [baseEvents],
  );

  const [speciesFilter, setSpeciesFilter] = useState<Set<string>>(new Set());
  const [taxonFilter, setTaxonFilter] = useState<Set<Taxon>>(new Set());
  const [minConfidence, setMinConfidence] = useState(0);
  const effectiveMin = Math.max(minConfidence, threshold);

  const filtered = useMemo(
    () =>
      baseEvents.filter(
        (e) =>
          (speciesFilter.size === 0 || speciesFilter.has(e.scientific_name)) &&
          (taxonFilter.size === 0 || taxonFilter.has(e.taxon)) &&
          e.max_confidence + 1e-9 >= effectiveMin,
      ),
    [baseEvents, speciesFilter, taxonFilter, effectiveMin],
  );
  const lanes = useMemo(() => buildTimelineLanes(filtered), [filtered]);
  const activeIds = useMemo(
    () => (playing ? eventsAtTime(filtered, time) : new Set<string>()),
    [filtered, time, playing],
  );

  const toggle = <T,>(set: Set<T>, value: T): Set<T> => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  const filtersActive = speciesFilter.size > 0 || taxonFilter.size > 0 || minConfidence > threshold;

  return (
    <Panel labelledBy="timeline-heading" className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow mb-1">Timeline</p>
          <h3 id="timeline-heading" className="text-base font-semibold tracking-tight text-ink">
            When each species was detected
          </h3>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            One lane per species. Bars span each detection event; stronger fill and the number show
            higher maximum confidence. Select a bar to play it.
          </p>
        </div>
      </div>

      <div
        className="mt-5 space-y-4 rounded-2xl border border-line bg-surface-muted p-4"
        role="group"
        aria-label="Timeline view filters"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-full text-xs font-medium text-muted sm:w-20">Species</span>
          <Chip pressed={speciesFilter.size === 0} onClick={() => setSpeciesFilter(new Set())}>
            All
          </Chip>
          {speciesOptions.map((lane) => (
            <Chip
              key={lane.key}
              pressed={speciesFilter.has(lane.scientificName)}
              onClick={() => setSpeciesFilter((s) => toggle(s, lane.scientificName))}
            >
              {lane.commonName}
            </Chip>
          ))}
        </div>
        {taxaOptions.length > 1 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-full text-xs font-medium text-muted sm:w-20">Taxon</span>
            <Chip pressed={taxonFilter.size === 0} onClick={() => setTaxonFilter(new Set())}>
              All
            </Chip>
            {taxaOptions.map((taxon) => (
              <Chip
                key={taxon}
                pressed={taxonFilter.has(taxon)}
                onClick={() => setTaxonFilter((s) => toggle(s, taxon))}
              >
                <TaxonIcon taxon={taxon} size={13} />
                {TAXON_LABEL[taxon]}
              </Chip>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <label htmlFor={sliderId} className="w-full text-xs font-medium text-muted sm:w-auto">
            Minimum confidence (view filter)
          </label>
          <input
            id={sliderId}
            type="range"
            min={threshold}
            max={0.95}
            step={0.05}
            value={effectiveMin}
            onChange={(e) => setMinConfidence(snapThreshold(Number(e.target.value), threshold))}
            aria-valuetext={`${thresholdPercent(effectiveMin)}, view filter only`}
            aria-describedby={`${sliderId}-hint`}
            className="h-1.5 w-40 cursor-pointer accent-forest-600 dark:accent-forest-400"
          />
          <span className="num text-sm font-semibold text-ink">
            {thresholdPercent(effectiveMin)}
          </span>
          <p id={`${sliderId}-hint`} className="w-full text-xs text-muted">
            Hides weaker bars in this view only. It is not the decision threshold (
            {thresholdPercent(threshold)}), which decides what counts in the metrics and exports.
          </p>
        </div>
      </div>

      <div className="mt-5 [--timeline-aspect:4/3] sm:[--timeline-aspect:16/7] lg:[--timeline-aspect:16/5]">
        <Spectrogram
          src={spectrogramUrl}
          duration={duration}
          minHz={minHz}
          maxHz={maxHz}
          label={`Spectrogram of ${analysis.recording?.filename ?? 'the recording'} with detection events`}
          aspect="var(--timeline-aspect)"
          events={filtered}
          activeIds={activeIds}
          selectedId={selectedEventId}
          onEventSelect={selectEvent}
          gutterClassName={GUTTER}
        />
      </div>

      <div className="mt-3 flex">
        <div className={cx('shrink-0', GUTTER)} />
        <AudioControls className="min-w-0 flex-1" />
      </div>

      <div className="mt-5" data-testid="timeline-lanes">
        {lanes.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-sm text-muted">
            {filtersActive
              ? 'No detection events match these view filters.'
              : 'No detection events at this decision threshold.'}
          </p>
        ) : (
          <>
            <div className="flex">
              <div className={cx('shrink-0 pr-3', GUTTER)}>
                {lanes.map((lane) => (
                  <div
                    key={lane.key}
                    className="flex items-center gap-1.5 border-b border-line text-xs"
                    style={{ height: lane.rows.length * ROW_H + LANE_PAD }}
                  >
                    <TaxonIcon
                      taxon={lane.taxon}
                      size={13}
                      className="hidden shrink-0 text-subtle sm:block"
                    />
                    <span
                      className="min-w-0 flex-1 truncate font-medium text-ink"
                      title={lane.commonName}
                    >
                      {lane.commonName}
                    </span>
                    <span className="num shrink-0 text-muted">{lane.eventCount}</span>
                  </div>
                ))}
              </div>
              <div ref={trackRef} className="relative min-w-0 flex-1">
                {lanes.map((lane) => (
                  <div
                    key={lane.key}
                    className="relative border-b border-line"
                    style={{ height: lane.rows.length * ROW_H + LANE_PAD }}
                    role="group"
                    aria-label={`${lane.commonName}: ${pluralize(lane.eventCount, 'detection event')}`}
                  >
                    {lane.rows.map((row, rowIndex) =>
                      row.map((event) => (
                        <EventBar
                          key={event.id}
                          event={event}
                          duration={duration || 1}
                          row={rowIndex}
                          threshold={threshold}
                          active={activeIds.has(event.id)}
                          selected={selectedEventId === event.id}
                          onSelect={selectEvent}
                          trackWidth={trackWidth}
                        />
                      )),
                    )}
                  </div>
                ))}
                <Playhead duration={duration} tone="light" />
              </div>
            </div>
            <div className="flex">
              <div className={cx('shrink-0', GUTTER)} />
              <TimeAxis duration={duration} className="mt-1.5 min-w-0 flex-1" />
            </div>
          </>
        )}
      </div>

      <p className="mt-4 text-xs text-muted">
        Showing {pluralize(filtered.length, 'detection event')} of {baseEvents.length} at the{' '}
        {thresholdPercent(threshold)} decision threshold. Dashed outlines mark events a reviewer
        rejected.
      </p>
    </Panel>
  );
}

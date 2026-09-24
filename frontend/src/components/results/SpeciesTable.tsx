import { useMemo, useState, type ReactNode } from 'react';
import type { Analysis, SpeciesSummary } from '../../api/types';
import { modelLabelForRun, modelRunMap } from '../../lib/analysis';
import { cx } from '../../lib/cx';
import { formatClockPrecise, formatPercent, formatSeconds } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { thresholdPercent } from '../../lib/threshold';
import { usePlayback } from '../../state/playbackContext';
import { SortIcon, TaxonIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';

type SortKey = 'name' | 'events' | 'confidence' | 'mean' | 'duration' | 'first';
type Direction = 'asc' | 'desc';

const DEFAULT_DIRECTION: Record<SortKey, Direction> = {
  name: 'asc',
  events: 'desc',
  confidence: 'desc',
  mean: 'desc',
  duration: 'desc',
  first: 'asc',
};

function compare(a: SpeciesSummary, b: SpeciesSummary, key: SortKey): number {
  switch (key) {
    case 'name':
      return a.common_name.localeCompare(b.common_name);
    case 'events':
      return a.detection_event_count - b.detection_event_count;
    case 'confidence':
      return a.max_confidence - b.max_confidence;
    case 'mean':
      return a.mean_confidence - b.mean_confidence;
    case 'duration':
      return a.total_event_duration_seconds - b.total_event_duration_seconds;
    case 'first':
      return a.first_detection_seconds - b.first_detection_seconds;
    default:
      return 0;
  }
}

function SortableHeader({
  label,
  sortKey,
  current,
  direction,
  onSort,
  align = 'left',
  className,
}: {
  label: ReactNode;
  sortKey: SortKey;
  current: SortKey;
  direction: Direction;
  onSort: (key: SortKey) => void;
  align?: 'left' | 'right';
  className?: string;
}) {
  const active = current === sortKey;
  return (
    <th
      scope="col"
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cx(
        'px-2 py-2.5 font-medium sm:px-3',
        align === 'right' ? 'text-right' : 'text-left',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cx(
          'inline-flex items-center gap-1 rounded-md hover:text-ink',
          active ? 'text-ink' : 'text-muted',
          align === 'right' ? 'flex-row-reverse' : '',
        )}
      >
        {label}
        <SortIcon
          size={13}
          direction={active ? direction : 'none'}
          className={active ? '' : 'opacity-50'}
        />
      </button>
    </th>
  );
}

export function SpeciesTable({
  analysis,
  species,
  dimmed,
}: {
  analysis: Analysis;
  species: SpeciesSummary[];
  dimmed?: boolean;
}) {
  const [sortKey, setSortKey] = useState<SortKey>('events');
  const [direction, setDirection] = useState<Direction>('desc');
  const { selectEvent } = usePlayback();
  const runs = useMemo(() => modelRunMap(analysis), [analysis]);

  const rows = useMemo(() => {
    const sorted = species.slice().sort((a, b) => {
      const primary = compare(a, b, sortKey);
      const tie = a.common_name.localeCompare(b.common_name);
      return (direction === 'asc' ? primary : -primary) || tie;
    });
    return sorted;
  }, [species, sortKey, direction]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) setDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setDirection(DEFAULT_DIRECTION[key]);
    }
  };

  const firstEventFor = (s: SpeciesSummary) =>
    analysis.events
      .filter((e) => e.scientific_name === s.scientific_name)
      .sort((a, b) => a.start_seconds - b.start_seconds)[0];

  const threshold = analysis.settings.decision_threshold;

  return (
    <Panel labelledBy="species-table-heading" className="overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 pb-3 pt-5 sm:px-6">
        <div>
          <p className="eyebrow mb-1">Species</p>
          <h3
            id="species-table-heading"
            className="text-base font-semibold tracking-tight text-ink"
          >
            Species with detection events
          </h3>
        </div>
        <p className="text-xs text-muted">
          {rows.length} {rows.length === 1 ? 'species' : 'species'} at {thresholdPercent(threshold)}
        </p>
      </div>
      <div className={cx('overflow-x-auto transition-opacity', dimmed ? 'opacity-60' : '')}>
        <table className="w-full border-collapse text-sm" data-testid="species-table">
          <caption className="sr-only">
            Species with detection events at the {thresholdPercent(threshold)} decision threshold.
            Sortable by name, detection events and confidence.
          </caption>
          <thead className="border-y border-line bg-surface-muted text-xs">
            <tr>
              <SortableHeader
                label="Species"
                sortKey="name"
                current={sortKey}
                direction={direction}
                onSort={onSort}
                className="pl-5 sm:pl-6"
              />
              <th
                scope="col"
                className="hidden px-3 py-2.5 text-left font-medium text-muted sm:table-cell"
              >
                Taxon
              </th>
              <th
                scope="col"
                className="hidden px-3 py-2.5 text-left font-medium text-muted lg:table-cell"
              >
                Model
              </th>
              <SortableHeader
                label="Events"
                sortKey="events"
                current={sortKey}
                direction={direction}
                onSort={onSort}
                align="right"
              />
              <SortableHeader
                label="Max conf."
                sortKey="confidence"
                current={sortKey}
                direction={direction}
                onSort={onSort}
                align="right"
              />
              <SortableHeader
                label="Mean conf."
                sortKey="mean"
                current={sortKey}
                direction={direction}
                onSort={onSort}
                align="right"
                className="hidden md:table-cell"
              />
              <SortableHeader
                label="Detected time"
                sortKey="duration"
                current={sortKey}
                direction={direction}
                onSort={onSort}
                align="right"
                className="hidden lg:table-cell"
              />
              <SortableHeader
                label="First detection"
                sortKey="first"
                current={sortKey}
                direction={direction}
                onSort={onSort}
                align="right"
                className="pr-5 sm:pr-6"
              />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((s) => {
              const models = s.model_run_ids.map((id) => modelLabelForRun(runs.get(id)));
              const first = firstEventFor(s);
              return (
                <tr
                  key={s.scientific_name}
                  className="align-top hover:bg-surface-muted"
                  data-testid="species-row"
                >
                  <th scope="row" className="py-3 pl-5 pr-2 text-left font-normal sm:pl-6 sm:pr-3">
                    <span className="block font-medium text-ink">{s.common_name}</span>
                    <span className="sci block text-xs text-muted">{s.scientific_name}</span>
                    <span className="mt-0.5 flex items-center gap-1 text-xs text-muted sm:hidden">
                      <TaxonIcon taxon={s.taxon} size={12} />
                      {TAXON_LABEL[s.taxon]}
                    </span>
                  </th>
                  <td className="hidden px-3 py-3 sm:table-cell">
                    <span className="inline-flex items-center gap-1.5 text-ink">
                      <TaxonIcon taxon={s.taxon} size={14} className="text-subtle" />
                      {TAXON_LABEL[s.taxon]}
                    </span>
                  </td>
                  <td className="hidden px-3 py-3 text-muted lg:table-cell">
                    {[...new Set(models)].join(', ') || 'n/a'}
                  </td>
                  <td className="num px-2 py-3 text-right font-semibold text-ink sm:px-3">
                    {s.detection_event_count}
                  </td>
                  <td className="num whitespace-nowrap px-2 py-3 text-right text-ink sm:px-3">
                    {formatPercent(s.max_confidence)}
                  </td>
                  <td className="num hidden px-3 py-3 text-right text-muted md:table-cell">
                    {formatPercent(s.mean_confidence)}
                  </td>
                  <td className="num hidden px-3 py-3 text-right text-muted lg:table-cell">
                    {formatSeconds(s.total_event_duration_seconds)}
                  </td>
                  <td className="num whitespace-nowrap py-3 pl-2 pr-5 text-right sm:pl-3 sm:pr-6">
                    {first ? (
                      <button
                        type="button"
                        className="link"
                        onClick={() => selectEvent(first)}
                        aria-label={`Play first ${s.common_name} detection at ${formatClockPrecise(s.first_detection_seconds)}`}
                      >
                        {formatClockPrecise(s.first_detection_seconds)}
                      </button>
                    ) : (
                      formatClockPrecise(s.first_detection_seconds)
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

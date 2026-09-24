import type { EventGroup } from '../../lib/analysis';
import { formatClockPrecise, formatPercent, pluralize } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { usePlayback } from '../../state/playbackContext';
import { ChevronDownIcon, FlagIcon, TaxonIcon } from '../ui/icons';

/** Species outside BirdNET's expected range or season for this place and week. */
export function UnlikelySection({ groups }: { groups: EventGroup[] }) {
  const { selectEvent } = usePlayback();
  if (groups.length === 0) return null;

  return (
    <details className="group rounded-2xl border border-line bg-surface-muted px-5 py-4 [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer list-none items-start gap-3 rounded-lg">
        <FlagIcon size={17} className="mt-0.5 shrink-0 text-warn" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-ink">
            Excluded as unlikely for this place and season ({groups.length})
          </span>
          <span className="mt-0.5 block text-xs text-muted">
            Detected above the threshold, but outside the range or season the model expects for this
            location and week. Listed for transparency; not counted in any metric.
          </span>
        </span>
        <ChevronDownIcon
          size={18}
          className="mt-0.5 shrink-0 text-muted transition-transform group-open:rotate-180"
        />
      </summary>
      <ul className="mt-4 divide-y divide-line border-t border-line text-sm">
        {groups.map((group) => {
          const first = group.events.slice().sort((a, b) => a.start_seconds - b.start_seconds)[0];
          return (
            <li
              key={group.scientificName}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5"
            >
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-warn">
                <FlagIcon size={13} />
                Unlikely
              </span>
              <span className="min-w-0 flex-1">
                <span className="font-medium text-ink">{group.commonName}</span>{' '}
                <span className="sci text-muted">{group.scientificName}</span>
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted">
                  <TaxonIcon taxon={group.taxon} size={13} />
                  {TAXON_LABEL[group.taxon]}
                </span>
              </span>
              <span className="num text-xs text-muted">
                {pluralize(group.events.length, 'event')} · max {formatPercent(group.maxConfidence)}
              </span>
              {first ? (
                <button
                  type="button"
                  className="link num text-xs"
                  onClick={() => selectEvent(first)}
                >
                  Play {formatClockPrecise(first.start_seconds)}
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

import type { EventGroup } from '../../lib/analysis';
import { pluralize } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { ShieldIcon, TaxonIcon } from '../ui/icons';

/** Human, domestic, mechanical and environmental sounds: noted, never counted as species. */
export function OtherSounds({
  groups,
  speechDetected,
}: {
  groups: EventGroup[];
  speechDetected: boolean;
}) {
  const hasHuman = speechDetected || groups.some((g) => g.taxon === 'human');
  if (groups.length === 0 && !hasHuman) return null;

  return (
    <section
      aria-labelledby="other-sounds-heading"
      className="rounded-2xl border border-line bg-surface-muted px-5 py-4"
    >
      <h3 id="other-sounds-heading" className="text-sm font-semibold text-ink">
        Other sounds
      </h3>
      <p className="mt-0.5 text-xs text-muted">
        Not species. These labels never count toward richness or any metric.
      </p>
      {groups.length ? (
        <ul className="mt-3 space-y-1.5 text-sm">
          {groups.map((group) => (
            <li
              key={`${group.taxon}-${group.commonName}`}
              className="flex items-center gap-2 text-ink"
            >
              <TaxonIcon taxon={group.taxon} size={15} className="shrink-0 text-subtle" />
              <span>
                <span className="font-medium">{group.commonName}</span> detected in{' '}
                {pluralize(group.windows, 'window')}
                <span className="text-muted"> ({TAXON_LABEL[group.taxon]})</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {hasHuman ? (
        <p className="mt-3 flex gap-2 text-xs text-muted">
          <ShieldIcon size={15} className="mt-px shrink-0 text-subtle" />
          <span>
            Human speech may be present in this recording. Thicket does not keep uploaded audio by
            default, and you can delete this analysis and its derived files from the server with the
            Delete button at the bottom of the page.
          </span>
        </p>
      ) : null}
    </section>
  );
}

import { useId, useMemo, useState } from 'react';
import type { SpeciesSummary, Taxon } from '../../api/types';
import { useElementWidth } from '../../hooks/useElementWidth';
import { cx } from '../../lib/cx';
import { formatPercent, pluralize } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { thresholdPercent } from '../../lib/threshold';
import { TaxonIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';

const ROW = 30;
const BAR = 14;
const RADIUS = 4;
const PAD_Y = 4;
const MAX_ROWS = 12;
const CHAR_W = 6.7;

function truncate(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}

/** Horizontal bar with a 4px rounded data end and a square baseline. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(RADIUS, w / 2, h / 2);
  return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(w - r)}Z`;
}

export function SpeciesFrequencyChart({
  species,
  threshold,
  dimmed,
}: {
  /** Counted species only (biodiversity taxa, not flagged unlikely). */
  species: SpeciesSummary[];
  threshold: number;
  dimmed?: boolean;
}) {
  const titleId = useId();
  const descId = useId();
  const svgTitleId = useId();
  const [ref, width] = useElementWidth<HTMLDivElement>(420);
  const [hovered, setHovered] = useState<number | null>(null);

  const sorted = useMemo(
    () =>
      species
        .slice()
        .sort(
          (a, b) =>
            b.detection_event_count - a.detection_event_count ||
            a.common_name.localeCompare(b.common_name),
        ),
    [species],
  );
  const rows = sorted.slice(0, MAX_ROWS);
  const hiddenCount = sorted.length - rows.length;
  const maxCount = Math.max(1, ...rows.map((s) => s.detection_event_count));

  const labelW = Math.round(Math.min(Math.max(width * 0.42, 112), 210));
  const valueW = 34;
  const plotW = Math.max(40, width - labelW - valueW);
  const height = rows.length * ROW + PAD_Y * 2;
  const maxChars = Math.floor((labelW - 30) / CHAR_W);
  const taxaPresent = [...new Set(rows.map((s) => s.taxon))] as Taxon[];

  const description = rows
    .map((s) => `${s.common_name}: ${pluralize(s.detection_event_count, 'detection event')}`)
    .join('; ');

  const hoveredRow = hovered !== null ? rows[hovered] : undefined;

  return (
    <Panel labelledBy={titleId} className="p-5 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="eyebrow mb-1">Species frequency</p>
          <h3 id={titleId} className="text-base font-semibold tracking-tight text-ink">
            Detection events per species
          </h3>
        </div>
        <p className="text-xs text-muted">At {thresholdPercent(threshold)}</p>
      </div>

      <div
        ref={ref}
        className={cx('relative transition-opacity', dimmed ? 'opacity-60' : 'opacity-100')}
      >
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby={`${svgTitleId} ${descId}`}
          className="block max-w-full overflow-visible"
          data-testid="species-chart"
        >
          <title id={svgTitleId}>Detection events per species</title>
          <desc id={descId}>
            Horizontal bar chart of detection events per species at the{' '}
            {thresholdPercent(threshold)} decision threshold. {description}.
          </desc>
          {rows.map((s, i) => {
            const y = PAD_Y + i * ROW;
            const barY = y + (ROW - BAR) / 2;
            const w = Math.max(3, (s.detection_event_count / maxCount) * (plotW - 8));
            const active = hovered === i;
            return (
              <g
                key={s.scientific_name}
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
                data-testid="species-chart-row"
              >
                <rect x={0} y={y} width={width} height={ROW} fill="transparent" />
                <TaxonIcon
                  taxon={s.taxon}
                  size={14}
                  x={0}
                  y={y + (ROW - 14) / 2}
                  className="text-subtle"
                />
                <text
                  x={20}
                  y={y + ROW / 2}
                  dominantBaseline="central"
                  className="fill-ink text-[12.5px]"
                >
                  {truncate(s.common_name, maxChars)}
                </text>
                <path
                  d={barPath(labelW, barY, w, BAR)}
                  className={cx(
                    'fill-mark transition-opacity',
                    active ? 'opacity-80' : 'opacity-100',
                  )}
                />
                <text
                  x={labelW + w + 6}
                  y={y + ROW / 2}
                  dominantBaseline="central"
                  className="num fill-muted text-[12px] font-medium"
                >
                  {s.detection_event_count}
                </text>
              </g>
            );
          })}
        </svg>

        {hoveredRow && hovered !== null ? (
          <div
            className="pointer-events-none absolute z-20 w-max max-w-[16rem] rounded-lg border border-line bg-raised px-3 py-2 text-xs shadow-lift"
            style={{
              top: PAD_Y + hovered * ROW + ROW,
              left: Math.min(labelW, Math.max(0, width - 220)),
            }}
            aria-hidden="true"
          >
            <p className="num text-sm font-semibold text-ink">
              {pluralize(hoveredRow.detection_event_count, 'detection event')}
            </p>
            <p className="text-ink">{hoveredRow.common_name}</p>
            <p className="sci text-muted">{hoveredRow.scientific_name}</p>
            <p className="mt-1 text-muted">
              {TAXON_LABEL[hoveredRow.taxon]} · max confidence{' '}
              {formatPercent(hoveredRow.max_confidence)}
            </p>
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        {taxaPresent.length > 1 || (taxaPresent[0] && taxaPresent[0] !== 'bird') ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>Icons show taxon:</span>
            {taxaPresent.map((t) => (
              <span key={t} className="inline-flex items-center gap-1">
                <TaxonIcon taxon={t} size={13} />
                {TAXON_LABEL[t]}
              </span>
            ))}
          </span>
        ) : null}
        {hiddenCount > 0 ? (
          <span>
            Plus {pluralize(hiddenCount, 'more species', 'more species')}, listed in the table
            below.
          </span>
        ) : null}
      </div>

      <div className="sr-only">
        <table>
          <caption>Detection events per species at {thresholdPercent(threshold)}</caption>
          <thead>
            <tr>
              <th scope="col">Species</th>
              <th scope="col">Taxon</th>
              <th scope="col">Detection events</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => (
              <tr key={s.scientific_name}>
                <th scope="row">{s.common_name}</th>
                <td>{TAXON_LABEL[s.taxon]}</td>
                <td>{s.detection_event_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

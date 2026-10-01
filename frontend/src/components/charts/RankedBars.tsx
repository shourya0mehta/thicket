import { useId, useState, type ReactNode } from 'react';
import type { Taxon } from '../../api/generated';
import { useElementWidth } from '../../hooks/useElementWidth';
import { cx } from '../../lib/cx';
import { formatInteger } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { FlagIcon, TaxonIcon } from '../ui/icons';
import { ChartTooltip, DataTable, TooltipRow, type DataRow } from './ChartFrame';
import { barPath } from './scales';
import { MARK } from './theme';

export interface RankedRow {
  key: string;
  label: string;
  sublabel?: string;
  taxon?: Taxon;
  /** Bar length (0 to 1 when `asFraction`). */
  value: number;
  /** Secondary number shown after the bar. */
  valueText: string;
  flagged?: boolean;
  flagLabel?: string;
  detail?: ReactNode;
  href?: string;
}

const ROW = 30;
const BAR = 12;

/**
 * Horizontal ranked bars in one hue (nominal categories take the same slot).
 * Taxon identity is shown by icon and in the table, never by bar color.
 */
export function RankedBars({
  rows,
  maxRows = 12,
  asFraction = false,
  valueLabel,
  title,
  description,
  caption,
  emptyText = 'Nothing to rank in this period.',
  moreHref,
}: {
  rows: RankedRow[];
  maxRows?: number;
  asFraction?: boolean;
  valueLabel: string;
  title: string;
  description: string;
  caption: string;
  emptyText?: string;
  moreHref?: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(420);
  const titleId = useId();
  const descId = useId();
  const [hovered, setHovered] = useState<number | null>(null);

  const shown = rows.slice(0, maxRows);
  const hidden = rows.length - shown.length;
  const max = asFraction ? 1 : Math.max(1, ...shown.map((r) => r.value));
  const labelW = Math.round(Math.min(Math.max(width * 0.4, 120), 220));
  const valueW = 52;
  const plotW = Math.max(40, width - labelW - valueW);
  const height = shown.length * ROW + 8;
  const maxChars = Math.floor((labelW - 28) / 6.6);
  const truncate = (text: string) =>
    text.length <= maxChars ? text : `${text.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;

  const tableRows: DataRow[] = rows.map((r) => ({
    label: r.label,
    taxon: r.taxon ? TAXON_LABEL[r.taxon] : '',
    value: r.valueText,
    flag: r.flagged ? (r.flagLabel ?? 'Priority') : '',
  }));

  if (!rows.length) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">
        {emptyText}
      </p>
    );
  }

  const hoveredRow = hovered !== null ? shown[hovered] : undefined;

  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        className="block max-w-full overflow-visible"
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>{description}</desc>
        {shown.map((r, i) => {
          const y = 4 + i * ROW;
          const w = Math.max(3, (r.value / max) * (plotW - 8));
          return (
            <g
              key={r.key}
              onPointerEnter={() => setHovered(i)}
              onPointerLeave={() => setHovered(null)}
              data-testid="ranked-row"
            >
              <rect x={0} y={y} width={width} height={ROW} fill="transparent" />
              {r.taxon ? (
                <TaxonIcon
                  taxon={r.taxon}
                  size={14}
                  x={0}
                  y={y + (ROW - 14) / 2}
                  className="text-subtle"
                />
              ) : null}
              <text
                x={r.taxon ? 20 : 0}
                y={y + ROW / 2}
                dominantBaseline="central"
                className="fill-ink text-[12.5px]"
              >
                {truncate(r.label)}
              </text>
              {r.flagged ? (
                <FlagIcon
                  size={12}
                  x={labelW - 18}
                  y={y + (ROW - 12) / 2}
                  className="text-warn"
                  strokeWidth={2.2}
                />
              ) : null}
              <path
                d={barPath(labelW, y + (ROW - BAR) / 2, w, BAR)}
                fill={MARK}
                className={cx('transition-opacity', hovered === i ? 'opacity-75' : 'opacity-100')}
              />
              <text
                x={labelW + w + 6}
                y={y + ROW / 2}
                dominantBaseline="central"
                className="num fill-muted text-[11.5px] font-medium"
              >
                {r.valueText}
              </text>
            </g>
          );
        })}
      </svg>

      {hoveredRow && hovered !== null ? (
        <ChartTooltip x={labelW} y={4 + hovered * ROW + ROW} width={width} align="left">
          <p className="font-medium text-ink">{hoveredRow.label}</p>
          {hoveredRow.sublabel ? <p className="sci text-muted">{hoveredRow.sublabel}</p> : null}
          <div className="mt-1">
            <TooltipRow label={valueLabel} value={hoveredRow.valueText} />
            {hoveredRow.taxon ? (
              <TooltipRow label="Taxon" value={TAXON_LABEL[hoveredRow.taxon]} />
            ) : null}
            {hoveredRow.detail}
          </div>
        </ChartTooltip>
      ) : null}

      {hidden > 0 || rows.some((r) => r.flagged) ? (
        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          {rows.some((r) => r.flagged) ? (
            <span className="inline-flex items-center gap-1">
              <FlagIcon size={12} className="text-warn" strokeWidth={2.2} /> Priority species
            </span>
          ) : null}
          {hidden > 0 ? (
            moreHref ? (
              <a className="link" href={moreHref}>
                {formatInteger(hidden)} more in the full list
              </a>
            ) : (
              <span>{formatInteger(hidden)} more in the table</span>
            )
          ) : null}
        </p>
      ) : null}

      <DataTable
        caption={caption}
        columns={[
          { key: 'label', label: 'Species' },
          { key: 'taxon', label: 'Taxon' },
          { key: 'value', label: valueLabel },
          { key: 'flag', label: 'Flag' },
        ]}
        rows={tableRows}
      />
    </div>
  );
}

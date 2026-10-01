import { useId, useState, type ReactNode } from 'react';
import { useElementWidth } from '../../hooks/useElementWidth';
import { formatInteger, formatPercent } from '../../lib/format';
import { ChartTooltip, DataTable, LegendItem, TooltipRow, type DataRow } from './ChartFrame';

export interface StackSegment {
  key: string;
  label: string;
  value: number;
  color: string;
  icon?: ReactNode;
  /** Extra line in the legend, e.g. "6 species". */
  note?: string;
}

/**
 * One horizontal part-to-whole bar with 2px surface gaps between segments.
 * Each segment is identified by its legend entry (mark, icon and label), and
 * a label is placed inside a segment only when it fits with padding.
 */
export function StackedBar({
  segments,
  title,
  description,
  caption,
  valueLabel,
  height = 22,
  emptyText = 'Nothing to show.',
}: {
  segments: StackSegment[];
  title: string;
  description: string;
  caption: string;
  valueLabel: string;
  height?: number;
  emptyText?: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(420);
  const titleId = useId();
  const descId = useId();
  const [active, setActive] = useState<number | null>(null);
  const total = segments.reduce((acc, s) => acc + Math.max(0, s.value), 0);
  const visible = segments.filter((s) => s.value > 0);

  if (total <= 0 || !visible.length) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-sm text-muted">
        {emptyText}
      </p>
    );
  }

  const gap = 2;
  const usable = width - gap * (visible.length - 1);
  let cursor = 0;
  const placed = visible.map((s, i) => {
    const w = (s.value / total) * usable;
    const x = cursor;
    cursor += w + gap;
    return { ...s, x, w, index: i };
  });
  const rows: DataRow[] = segments.map((s) => ({
    label: s.label,
    value: formatInteger(s.value),
    share: formatPercent(s.value / total),
  }));
  const activeSeg = active !== null ? placed[active] : undefined;

  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        className="block max-w-full overflow-visible"
        onPointerLeave={() => setActive(null)}
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>{description}</desc>
        {placed.map((s) => {
          const label = `${formatPercent(s.value / total)}`;
          const fits = s.w > label.length * 7 + 16;
          return (
            <g key={s.key} onPointerEnter={() => setActive(s.index)}>
              <rect
                x={s.x}
                y={0}
                width={Math.max(1, s.w)}
                height={height}
                rx={3}
                fill={s.color}
                opacity={active === null || active === s.index ? 1 : 0.55}
              />
              {fits ? (
                <text
                  x={s.x + s.w / 2}
                  y={height / 2}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="num text-[11px] font-semibold"
                  fill="var(--viz-on)"
                >
                  {label}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      {activeSeg ? (
        <ChartTooltip x={activeSeg.x + activeSeg.w / 2} y={height + 4} width={width}>
          <p className="font-medium text-ink">{activeSeg.label}</p>
          <TooltipRow
            swatch={activeSeg.color}
            label={valueLabel}
            value={formatInteger(activeSeg.value)}
          />
          <TooltipRow label="Share" value={formatPercent(activeSeg.value / total)} />
          {activeSeg.note ? <p className="mt-0.5 text-muted">{activeSeg.note}</p> : null}
        </ChartTooltip>
      ) : null}
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2" aria-label="Legend">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-2">
            <LegendItem color={s.color} icon={s.icon}>
              <span className="text-ink">{s.label}</span>
            </LegendItem>
            <span className="num text-xs text-muted">
              {formatInteger(s.value)}
              {s.note ? ` · ${s.note}` : ''}
            </span>
          </li>
        ))}
      </ul>
      <DataTable
        caption={caption}
        columns={[
          { key: 'label', label: 'Group' },
          { key: 'value', label: valueLabel },
          { key: 'share', label: 'Share' },
        ]}
        rows={rows}
      />
    </div>
  );
}

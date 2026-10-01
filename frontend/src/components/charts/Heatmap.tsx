import { useId, useMemo, useState } from 'react';
import type { HeatCell } from '../../api/generated';
import { useElementWidth } from '../../hooks/useElementWidth';
import { hourLabel, WEEKDAYS } from '../../lib/dates';
import { formatInteger, formatNumber } from '../../lib/format';
import { ChartTooltip, DataTable, TooltipRow, type DataRow } from './ChartFrame';
import { sequentialFill } from './theme';

/**
 * Weekday by hour grid of detection events per recorded minute. One hue,
 * light to dark; hours without recordings are drawn as hollow cells so an
 * empty slot never reads as "quiet".
 */
export function ActivityHeatmap({
  cells,
  title,
  caption,
}: {
  cells: HeatCell[];
  title: string;
  caption: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const titleId = useId();
  const descId = useId();
  const [active, setActive] = useState<{ weekday: number; hour: number } | null>(null);

  const grid = useMemo(() => {
    const map = new Map<string, HeatCell>();
    for (const c of cells) map.set(`${c.weekday}-${c.hour}`, c);
    const max = Math.max(0, ...cells.map((c) => c.events_per_minute));
    return { map, max };
  }, [cells]);

  const labelW = 34;
  const top = 18;
  const gap = 2;
  const cellW = Math.max(6, (width - labelW - 23 * gap) / 24);
  const cellH = Math.min(22, Math.max(12, cellW * 0.9));
  const height = top + 7 * (cellH + gap) + 6;
  const cellFor = (d: number, h: number) => grid.map.get(`${d}-${h}`);
  const activeCell = active ? cellFor(active.weekday, active.hour) : undefined;
  const recorded = cells.filter((c) => c.recordings > 0).length;

  const peak = useMemo(() => {
    let best: HeatCell | null = null;
    for (const c of cells) if (!best || c.events_per_minute > best.events_per_minute) best = c;
    return best;
  }, [cells]);

  const rows: DataRow[] = cells
    .slice()
    .sort((a, b) => a.weekday - b.weekday || a.hour - b.hour)
    .map((c) => ({
      day: WEEKDAYS[c.weekday] ?? String(c.weekday),
      hour: `${String(c.hour).padStart(2, '0')}:00`,
      epm: formatNumber(c.events_per_minute, 2),
      recordings: formatInteger(c.recordings),
    }));

  if (!cells.length) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">
        No recordings in this period.
      </p>
    );
  }

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
        <desc id={descId}>
          Grid of weekdays by hour of day. Darker cells have more detection events per recorded
          minute; hollow cells have no recordings. {recorded} of 168 hour slots have recordings.
          {peak
            ? ` The busiest slot is ${WEEKDAYS[peak.weekday]} at ${hourLabel(peak.hour)} with ${formatNumber(peak.events_per_minute, 1)} events per minute.`
            : ''}
        </desc>
        {Array.from({ length: 24 }, (_, h) =>
          h % 3 === 0 ? (
            <text
              key={h}
              x={labelW + h * (cellW + gap) + cellW / 2}
              y={top - 6}
              textAnchor="middle"
              className="fill-muted text-[10px]"
            >
              {hourLabel(h)}
            </text>
          ) : null,
        )}
        {WEEKDAYS.map((day, d) => (
          <g key={day}>
            <text
              x={labelW - 8}
              y={top + d * (cellH + gap) + cellH / 2}
              textAnchor="end"
              dominantBaseline="central"
              className="fill-muted text-[10.5px]"
            >
              {day}
            </text>
            {Array.from({ length: 24 }, (_, h) => {
              const c = cellFor(d, h);
              const x = labelW + h * (cellW + gap);
              const y = top + d * (cellH + gap);
              const isActive = active?.weekday === d && active.hour === h;
              if (!c || c.recordings === 0) {
                return (
                  <rect
                    key={h}
                    x={x + 0.5}
                    y={y + 0.5}
                    width={cellW - 1}
                    height={cellH - 1}
                    rx={2}
                    fill="none"
                    stroke="rgb(var(--ink) / 0.1)"
                    strokeWidth={1}
                    onPointerEnter={() => setActive({ weekday: d, hour: h })}
                  />
                );
              }
              const t = grid.max > 0 ? c.events_per_minute / grid.max : 0;
              return (
                <rect
                  key={h}
                  x={x}
                  y={y}
                  width={cellW}
                  height={cellH}
                  rx={2}
                  fill={sequentialFill(t, 0.1, 0.95)}
                  stroke={isActive ? 'rgb(var(--ink))' : 'none'}
                  strokeWidth={isActive ? 1.5 : 0}
                  onPointerEnter={() => setActive({ weekday: d, hour: h })}
                />
              );
            })}
          </g>
        ))}
      </svg>

      {active ? (
        <ChartTooltip
          x={labelW + active.hour * (cellW + gap) + cellW / 2}
          y={top + active.weekday * (cellH + gap) + cellH + 4}
          width={width}
        >
          <p className="mb-1 font-medium text-ink">
            {WEEKDAYS[active.weekday]} {String(active.hour).padStart(2, '0')}:00 to{' '}
            {String(active.hour + 1).padStart(2, '0')}:00
          </p>
          {activeCell && activeCell.recordings > 0 ? (
            <>
              <TooltipRow
                label="Events per minute"
                value={formatNumber(activeCell.events_per_minute, 2)}
              />
              <TooltipRow label="Recordings" value={formatInteger(activeCell.recordings)} />
            </>
          ) : (
            <p className="text-muted">No recordings in this slot</p>
          )}
        </ChartTooltip>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-flex gap-0.5" aria-hidden="true">
            {[0.1, 0.35, 0.6, 0.95].map((a) => (
              <span
                key={a}
                className="inline-block h-3 w-3 rounded-sm"
                style={{ backgroundColor: `rgb(var(--mark) / ${a})` }}
              />
            ))}
          </span>
          <span>
            Fewer to more detection events per recorded minute (max{' '}
            <span className="num">{formatNumber(grid.max, 1)}</span>)
          </span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-3 w-3 rounded-sm border border-ink/20"
            aria-hidden="true"
          />
          No recordings
        </span>
      </div>

      <DataTable
        caption={caption}
        columns={[
          { key: 'day', label: 'Weekday' },
          { key: 'hour', label: 'Hour' },
          { key: 'epm', label: 'Events per minute' },
          { key: 'recordings', label: 'Recordings' },
        ]}
        rows={rows}
      />
    </div>
  );
}

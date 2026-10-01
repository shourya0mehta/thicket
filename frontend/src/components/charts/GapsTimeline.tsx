import { useId, useMemo, useState } from 'react';
import type { Gap } from '../../api/generated';
import { useElementWidth } from '../../hooks/useElementWidth';
import { formatDateTime, formatNumber } from '../../lib/format';
import { ChartTooltip, DataTable, TooltipRow, type DataRow } from './ChartFrame';
import { linearScale, timeLabel } from './scales';
import { AXIS, GRID, STATUS } from './theme';

/**
 * Recording gaps as bars on a time axis covering the health window. Each bar
 * is a stretch with no recordings longer than the rule allows; its height is
 * the gap length in hours so long outages stand out.
 */
export function GapsTimeline({
  gaps,
  from,
  to,
  caption,
}: {
  gaps: Gap[];
  /** ISO bounds of the window shown. */
  from: string;
  to: string;
  caption: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const titleId = useId();
  const descId = useId();
  const [active, setActive] = useState<number | null>(null);
  const margin = { top: 10, right: 12, bottom: 24, left: 34 };
  const height = 120;
  const plotW = Math.max(40, width - margin.left - margin.right);
  const plotH = height - margin.top - margin.bottom;

  const t0 = new Date(from).getTime();
  const t1 = Math.max(t0 + 1, new Date(to).getTime());
  const x = linearScale([t0, t1], [margin.left, margin.left + plotW]);
  const maxHours = Math.max(1, ...gaps.map((g) => g.hours));
  const y = linearScale([0, maxHours], [margin.top + plotH, margin.top]);

  const ticks = useMemo(() => {
    const n = Math.max(2, Math.min(6, Math.floor(plotW / 100)));
    return Array.from({ length: n }, (_, i) => t0 + ((t1 - t0) * i) / (n - 1));
  }, [plotW, t0, t1]);

  const rows: DataRow[] = gaps.map((g) => ({
    start: formatDateTime(g.start),
    end: formatDateTime(g.end),
    hours: formatNumber(g.hours, 1),
    expected: g.expected_recordings == null ? '' : String(g.expected_recordings),
  }));
  const total = gaps.reduce((acc, g) => acc + g.hours, 0);

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
        <title id={titleId}>Recording gaps</title>
        <desc id={descId}>
          {gaps.length === 0
            ? 'No gaps longer than the rule allows in this window.'
            : `${gaps.length} gaps totalling ${formatNumber(total, 1)} hours; the longest is ${formatNumber(maxHours, 1)} hours.`}
        </desc>
        <line
          x1={margin.left}
          x2={margin.left + plotW}
          y1={margin.top + plotH}
          y2={margin.top + plotH}
          stroke={AXIS}
        />
        <line
          x1={margin.left}
          x2={margin.left + plotW}
          y1={y(maxHours)}
          y2={y(maxHours)}
          stroke={GRID}
        />
        <text
          x={margin.left - 6}
          y={y(maxHours)}
          textAnchor="end"
          dominantBaseline="central"
          className="num fill-muted text-[10px]"
        >
          {formatNumber(maxHours, 0)} h
        </text>
        <text
          x={margin.left - 6}
          y={margin.top + plotH}
          textAnchor="end"
          dominantBaseline="central"
          className="num fill-muted text-[10px]"
        >
          0
        </text>
        {ticks.map((t, i) => (
          <text
            key={t}
            x={x(t)}
            y={height - 6}
            textAnchor={i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle'}
            className="fill-muted text-[10.5px]"
          >
            {timeLabel(new Date(t).toISOString(), t1 - t0)}
          </text>
        ))}
        {gaps.map((g, i) => {
          const gx0 = Math.max(margin.left, x(new Date(g.start).getTime()));
          const gx1 = Math.min(margin.left + plotW, x(new Date(g.end).getTime()));
          const w = Math.max(3, gx1 - gx0);
          const h = Math.max(2, margin.top + plotH - y(g.hours));
          return (
            <rect
              key={`${g.start}-${i}`}
              x={gx0}
              y={margin.top + plotH - h}
              width={w}
              height={h}
              rx={2}
              fill={STATUS.warn}
              opacity={active === null || active === i ? 0.85 : 0.5}
              onPointerEnter={() => setActive(i)}
            />
          );
        })}
        {gaps.length === 0 ? (
          <text
            x={margin.left + plotW / 2}
            y={margin.top + plotH / 2}
            textAnchor="middle"
            className="fill-muted text-[12px]"
          >
            No gaps in this window
          </text>
        ) : null}
      </svg>
      {active !== null && gaps[active] ? (
        <ChartTooltip x={x(new Date(gaps[active].start).getTime())} y={margin.top} width={width}>
          <p className="mb-1 font-medium text-ink">
            {formatDateTime(gaps[active].start)} to {formatDateTime(gaps[active].end)}
          </p>
          <TooltipRow label="Gap" value={`${formatNumber(gaps[active].hours, 1)} h`} />
          {gaps[active].expected_recordings != null ? (
            <TooltipRow
              label="Recordings expected"
              value={String(gaps[active].expected_recordings)}
            />
          ) : null}
        </ChartTooltip>
      ) : null}
      <DataTable
        caption={caption}
        columns={[
          { key: 'start', label: 'Start' },
          { key: 'end', label: 'End' },
          { key: 'hours', label: 'Hours' },
          { key: 'expected', label: 'Recordings expected' },
        ]}
        rows={rows}
      />
    </div>
  );
}

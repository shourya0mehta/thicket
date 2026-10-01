import { useId, useMemo, useState, type PointerEvent } from 'react';
import type { AccumulationPoint } from '../../api/generated';
import { useElementWidth } from '../../hooks/useElementWidth';
import { formatDate, formatInteger } from '../../lib/format';
import { niceMax, niceValueTicks } from '../../lib/stats';
import { ChartTooltip, DataTable, TooltipRow, type DataRow } from './ChartFrame';
import { linearScale, spreadTickIndexes } from './scales';
import { AXIS, GRID, MARK } from './theme';

/**
 * Species accumulation: cumulative species counted against recordings in
 * capture order. A step line, because the count only changes at a recording.
 */
export function AccumulationChart({
  points,
  title,
  caption,
}: {
  points: AccumulationPoint[];
  title: string;
  caption: string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const titleId = useId();
  const descId = useId();
  const [active, setActive] = useState<number | null>(null);
  const margin = { top: 16, right: 16, bottom: 40, left: 36 };
  const height = 216;
  const plotW = Math.max(40, width - margin.left - margin.right);
  const plotH = height - margin.top - margin.bottom;

  const sorted = useMemo(
    () => points.slice().sort((a, b) => a.recording_index - b.recording_index),
    [points],
  );
  const maxX = Math.max(1, ...sorted.map((p) => p.recording_index));
  const maxY = niceMax(Math.max(1, ...sorted.map((p) => p.cumulative_species)));
  const x = linearScale([0, maxX], [margin.left, margin.left + plotW]);
  const y = linearScale([0, maxY], [margin.top + plotH, margin.top]);

  const path = useMemo(() => {
    let d = '';
    sorted.forEach((p, i) => {
      const px = x(p.recording_index);
      const py = y(p.cumulative_species);
      if (i === 0) d += `M${x(0).toFixed(1)},${y(0).toFixed(1)}L${px.toFixed(1)},${py.toFixed(1)}`;
      else {
        const prevY = y(sorted[i - 1]!.cumulative_species);
        d += `L${px.toFixed(1)},${prevY.toFixed(1)}L${px.toFixed(1)},${py.toFixed(1)}`;
      }
    });
    return d;
  }, [sorted, x, y]);

  const last = sorted[sorted.length - 1];
  const flattening = useMemo(() => {
    if (sorted.length < 10 || !last) return null;
    const tailStart = sorted[Math.floor(sorted.length * 0.75)]!;
    const gained = last.cumulative_species - tailStart.cumulative_species;
    return { gained, over: last.recording_index - tailStart.recording_index };
  }, [sorted, last]);

  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!sorted.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left;
    let best = 0;
    let bestD = Infinity;
    sorted.forEach((p, i) => {
      const d = Math.abs(x(p.recording_index) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setActive(best);
  };

  const rows: DataRow[] = sorted.map((p) => ({
    index: formatInteger(p.recording_index),
    date: p.captured_at ? formatDate(p.captured_at) : 'Unknown',
    species: formatInteger(p.cumulative_species),
  }));
  const xTicks = spreadTickIndexes(sorted.length, plotW, 90);
  const activePoint = active !== null ? sorted[active] : undefined;

  if (!sorted.length) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">
        The curve appears once the site has analyzed recordings.
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
        onPointerMove={onMove}
        onPointerLeave={() => setActive(null)}
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>
          Cumulative species counted after each recording, from 0 to {last?.cumulative_species} over{' '}
          {last?.recording_index} recordings.
          {flattening
            ? ` The last quarter of recordings added ${flattening.gained} species over ${flattening.over} recordings.`
            : ''}
        </desc>
        {niceValueTicks(0, maxY, 4).map((t) => (
          <g key={t}>
            <line x1={margin.left} x2={margin.left + plotW} y1={y(t)} y2={y(t)} stroke={GRID} />
            <text
              x={margin.left - 6}
              y={y(t)}
              textAnchor="end"
              dominantBaseline="central"
              className="num fill-muted text-[10.5px]"
            >
              {t}
            </text>
          </g>
        ))}
        <line
          x1={margin.left}
          x2={margin.left + plotW}
          y1={margin.top + plotH}
          y2={margin.top + plotH}
          stroke={AXIS}
        />
        {xTicks.map((i) => (
          <text
            key={i}
            x={x(sorted[i]!.recording_index)}
            y={margin.top + plotH + 16}
            textAnchor={i === sorted.length - 1 ? 'end' : 'middle'}
            className="num fill-muted text-[10.5px]"
          >
            {sorted[i]!.recording_index}
          </text>
        ))}
        <text
          x={margin.left + plotW / 2}
          y={height - 4}
          textAnchor="middle"
          className="fill-subtle text-[10px]"
        >
          recordings in capture order
        </text>
        <path d={path} fill="none" stroke={MARK} strokeWidth={2} strokeLinejoin="round" />
        {last ? (
          <g>
            <circle
              cx={x(last.recording_index)}
              cy={y(last.cumulative_species)}
              r={4}
              fill={MARK}
              stroke="rgb(var(--raised))"
              strokeWidth={2}
            />
            <text
              x={x(last.recording_index) - 8}
              y={y(last.cumulative_species) - 8}
              textAnchor="end"
              className="num fill-ink text-[11px] font-semibold"
            >
              {last.cumulative_species} species
            </text>
          </g>
        ) : null}
        {activePoint ? (
          <g aria-hidden="true">
            <line
              x1={x(activePoint.recording_index)}
              x2={x(activePoint.recording_index)}
              y1={margin.top}
              y2={margin.top + plotH}
              stroke={AXIS}
            />
            <circle
              cx={x(activePoint.recording_index)}
              cy={y(activePoint.cumulative_species)}
              r={4.5}
              fill={MARK}
              stroke="rgb(var(--raised))"
              strokeWidth={2}
            />
          </g>
        ) : null}
      </svg>
      {activePoint ? (
        <ChartTooltip
          x={x(activePoint.recording_index)}
          y={y(activePoint.cumulative_species) - 6}
          width={width}
        >
          <p className="mb-1 font-medium text-ink">
            Recording {activePoint.recording_index}
            {activePoint.captured_at ? ` · ${formatDate(activePoint.captured_at)}` : ''}
          </p>
          <TooltipRow
            swatch={MARK}
            label="Species so far"
            value={formatInteger(activePoint.cumulative_species)}
          />
        </ChartTooltip>
      ) : null}
      <DataTable
        caption={caption}
        columns={[
          { key: 'index', label: 'Recording' },
          { key: 'date', label: 'Captured' },
          { key: 'species', label: 'Cumulative species' },
        ]}
        rows={rows}
      />
    </div>
  );
}

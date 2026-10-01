import { useId, useMemo, useState } from 'react';
import type { Phenology } from '../../api/generated';
import { useElementWidth } from '../../hooks/useElementWidth';
import { monthOfIsoWeek } from '../../lib/dates';
import { formatInteger, formatPercent } from '../../lib/format';
import { ChartTooltip, DataTable, TooltipRow, type DataRow } from './ChartFrame';
import { sequentialFill } from './theme';

const WEEKS = 53;

/**
 * Species by ISO week, one row per year, cells shaded by presence fraction
 * (recordings with a detection over recordings made). Weeks without
 * recordings are hollow so "not recorded" never looks like "not detected".
 */
export function PhenologyRibbon({ phenology, caption }: { phenology: Phenology; caption: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const titleId = useId();
  const descId = useId();
  const [active, setActive] = useState<{ year: number; week: number } | null>(null);

  const years = useMemo(
    () => [...new Set(phenology.cells.map((c) => c.year))].sort((a, b) => a - b),
    [phenology.cells],
  );
  const lookup = useMemo(() => {
    const map = new Map<string, Phenology['cells'][number]>();
    for (const c of phenology.cells) map.set(`${c.year}-${c.iso_week}`, c);
    return map;
  }, [phenology.cells]);

  const labelW = 40;
  const narrow = width < 480;
  const gap = narrow ? 1 : 1.5;
  const cellW = Math.max(3, (width - labelW - (WEEKS - 1) * gap) / WEEKS);
  const cellH = Math.min(26, Math.max(14, cellW * 1.6));
  const top = 18;
  const height = top + years.length * (cellH + 4) + 4;
  const activeCell = active ? lookup.get(`${active.year}-${active.week}`) : undefined;

  const rows: DataRow[] = phenology.cells
    .slice()
    .sort((a, b) => a.year - b.year || a.iso_week - b.iso_week)
    .map((c) => ({
      year: String(c.year),
      week: String(c.iso_week),
      presence: formatPercent(c.presence_fraction),
      withDetection: `${formatInteger(c.recordings_with_detection)} of ${formatInteger(c.recordings)}`,
    }));

  const firstLast = years
    .map((y) => {
      const first = phenology.first_detection_by_year[String(y)];
      const last = phenology.last_detection_by_year[String(y)];
      return first || last ? `${y}: first ${first ?? 'n/a'}, last ${last ?? 'n/a'}` : null;
    })
    .filter(Boolean)
    .join('; ');

  if (!phenology.cells.length) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-sm text-muted">
        No weekly data yet for {phenology.species.common_name}.
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
        <title id={titleId}>
          {phenology.species.common_name} by ISO week, {years[0]} to {years[years.length - 1]}
        </title>
        <desc id={descId}>
          Rows are years, columns are ISO weeks 1 to 53. Darker cells mean the species was detected
          in a larger share of that week&apos;s recordings; hollow cells had no recordings.{' '}
          {firstLast}
        </desc>
        {Array.from({ length: 12 }, (_, m) => {
          // Every other month on a phone so labels never collide.
          if (narrow && m % 2 === 1) return null;
          const week = Math.round((m * 30.44 + 1) / 7) + 1;
          return (
            <text
              key={m}
              x={labelW + (week - 1) * (cellW + gap)}
              y={top - 6}
              className="fill-muted text-[10px]"
            >
              {monthOfIsoWeek(week)}
            </text>
          );
        })}
        {years.map((year, yi) => (
          <g key={year}>
            <text
              x={labelW - 8}
              y={top + yi * (cellH + 4) + cellH / 2}
              textAnchor="end"
              dominantBaseline="central"
              className="num fill-muted text-[11px]"
            >
              {year}
            </text>
            {Array.from({ length: WEEKS }, (_, wi) => {
              const week = wi + 1;
              const c = lookup.get(`${year}-${week}`);
              const x = labelW + wi * (cellW + gap);
              const y = top + yi * (cellH + 4);
              const isActive = active?.year === year && active.week === week;
              if (!c || c.recordings === 0) {
                return (
                  <rect
                    key={week}
                    x={x + 0.5}
                    y={y + 0.5}
                    width={cellW - 1}
                    height={cellH - 1}
                    rx={1.5}
                    fill="none"
                    stroke="rgb(var(--ink) / 0.09)"
                    onPointerEnter={() => setActive({ year, week })}
                  />
                );
              }
              return (
                <rect
                  key={week}
                  x={x}
                  y={y}
                  width={cellW}
                  height={cellH}
                  rx={1.5}
                  fill={sequentialFill(c.presence_fraction, 0.12, 0.95)}
                  stroke={isActive ? 'rgb(var(--ink))' : 'none'}
                  strokeWidth={isActive ? 1.5 : 0}
                  onPointerEnter={() => setActive({ year, week })}
                />
              );
            })}
          </g>
        ))}
      </svg>
      {active ? (
        <ChartTooltip
          x={labelW + (active.week - 1) * (cellW + gap) + cellW / 2}
          y={top + years.indexOf(active.year) * (cellH + 4) + cellH + 4}
          width={width}
        >
          <p className="mb-1 font-medium text-ink">
            {active.year}, ISO week {active.week}
          </p>
          {activeCell && activeCell.recordings > 0 ? (
            <>
              <TooltipRow label="Presence" value={formatPercent(activeCell.presence_fraction)} />
              <TooltipRow
                label="Recordings with detection"
                value={`${activeCell.recordings_with_detection} of ${activeCell.recordings}`}
              />
            </>
          ) : (
            <p className="text-muted">No recordings that week</p>
          )}
        </ChartTooltip>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-flex gap-0.5" aria-hidden="true">
            {[0.12, 0.4, 0.68, 0.95].map((a) => (
              <span
                key={a}
                className="inline-block h-3 w-3 rounded-sm"
                style={{ backgroundColor: `rgb(var(--mark) / ${a})` }}
              />
            ))}
          </span>
          Share of that week&apos;s recordings with a detection
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
          { key: 'year', label: 'Year' },
          { key: 'week', label: 'ISO week' },
          { key: 'presence', label: 'Presence' },
          { key: 'withDetection', label: 'Recordings with detection' },
        ]}
        rows={rows}
      />
    </div>
  );
}

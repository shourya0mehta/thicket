import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useElementWidth } from '../../hooks/useElementWidth';
import { cx } from '../../lib/cx';
import { formatInteger, formatNumber } from '../../lib/format';
import { niceMax, niceValueTicks } from '../../lib/stats';
import { ChartTooltip, DataTable, TooltipRow, type DataRow } from './ChartFrame';
import {
  bandPath,
  columnPath,
  linePath,
  linearScale,
  spreadTickIndexes,
  timeLabel,
  timeLabelLong,
  timeValue,
} from './scales';
import { AXIS, GRID, MARK, STATUS } from './theme';

export interface SeriesPointInput {
  /** YYYY-MM-DD or an ISO timestamp. Sorted ascending. */
  x: string;
  y: number | null;
}

export interface BandInput {
  low: number | null;
  high: number | null;
  center?: number | null;
}

export interface ThresholdLine {
  value: number;
  label: string;
  tone?: 'warn' | 'danger' | 'muted';
}

export interface TimeSeriesChartProps {
  points: SeriesPointInput[];
  /** Aligned with points. Drawn as a wash behind the line, with a thin center line. */
  band?: BandInput[] | null;
  bandLabel?: string;
  /** Aligned with points. Drawn as thin columns in a strip under the line. */
  bars?: Array<number | null> | null;
  barsLabel?: string;
  thresholds?: ThresholdLine[];
  /** Series name, used in the tooltip, the legend and the table. */
  yLabel: string;
  yFormat?: (value: number) => string;
  /** Lower y bound; default 0. Pass null to fit the data (for dBFS or temperature). */
  yMin?: number | null;
  yMax?: number | null;
  height?: number;
  color?: string;
  /** Direct-label the maximum and the latest value. */
  annotate?: boolean;
  compact?: boolean;
  /** Accessible name and summary for the SVG. */
  title: string;
  description: string;
  caption: string;
  testId?: string;
  /** Called with the active index on hover or focus (to sync small multiples). */
  onActiveChange?: (index: number | null) => void;
  activeIndex?: number | null;
}

const defaultFormat = (v: number) => (Number.isInteger(v) ? formatInteger(v) : formatNumber(v, 1));

export function TimeSeriesChart({
  points,
  band,
  bandLabel = 'Baseline (median plus or minus MAD)',
  bars,
  barsLabel = 'Recordings',
  thresholds = [],
  yLabel,
  yFormat = defaultFormat,
  yMin = 0,
  yMax = null,
  height,
  color = MARK,
  annotate = true,
  compact = false,
  title,
  description,
  caption,
  testId,
  onActiveChange,
  activeIndex,
}: TimeSeriesChartProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  const descId = useId();
  const active = activeIndex ?? hover;

  const margin = {
    top: compact ? 10 : 18,
    right: compact ? 10 : 16,
    bottom: compact ? 20 : 24,
    left: compact ? 32 : 40,
  };
  const barStrip = bars && bars.some((b) => (b ?? 0) > 0) ? (compact ? 28 : 44) : 0;
  const totalHeight = height ?? (compact ? 120 : 220) + barStrip;
  const plotW = Math.max(40, width - margin.left - margin.right);
  const lineH = totalHeight - margin.top - margin.bottom - (barStrip ? barStrip + 10 : 0);
  const lineTop = margin.top;
  const lineBottom = lineTop + lineH;

  const geometry = useMemo(() => {
    const times = points.map((p) => timeValue(p.x));
    const t0 = times.length ? Math.min(...times) : 0;
    const t1 = times.length ? Math.max(...times) : 1;
    const xScale = linearScale([t0, t1 === t0 ? t0 + 1 : t1], [margin.left, margin.left + plotW]);
    const ys = points.map((p) => p.y).filter((v): v is number => v !== null && Number.isFinite(v));
    const bandValues = (band ?? [])
      .flatMap((b) => [b.low, b.high])
      .filter((v): v is number => v !== null && Number.isFinite(v));
    const thresholdValues = thresholds.map((t) => t.value);
    const all = [...ys, ...bandValues, ...thresholdValues];
    const dataMin = all.length ? Math.min(...all) : 0;
    const dataMax = all.length ? Math.max(...all) : 1;
    let lo = yMin === null ? dataMin : Math.min(yMin, dataMin);
    // Small fractions (clipping, high-band share) keep their own scale instead of 0 to 1.
    let hi =
      yMax ??
      (yMin === null ? dataMax : niceMax(dataMax, dataMax > 0 && dataMax < 1 ? dataMax : 1));
    if (yMin === null) {
      const pad = (dataMax - dataMin || 1) * 0.15;
      lo = dataMin - pad;
      hi = dataMax + pad;
    }
    if (hi <= lo) hi = lo + 1;
    const yScale = linearScale([lo, hi], [lineBottom, lineTop]);
    const px = points.map((p, i) => ({
      x: xScale(times[i]!),
      y: p.y === null || !Number.isFinite(p.y) ? null : yScale(p.y),
    }));
    const bandPx = band
      ? band.map((b, i) => ({
          x: xScale(times[i]!),
          low: b.low === null ? null : yScale(b.low),
          high: b.high === null ? null : yScale(b.high),
          center: b.center == null ? null : yScale(b.center),
        }))
      : null;
    const inRange = (t: number) => t >= lo - 1e-9 && t <= hi + 1e-9;
    let yTicks = niceValueTicks(lo, hi, compact ? 4 : 5).filter(inRange);
    // Always at least two labelled values so the scale can be read.
    for (let n = 6; yTicks.length < 2 && n <= 12; n += 2) {
      yTicks = niceValueTicks(lo, hi, n).filter(inRange);
    }
    const xTickIdx = spreadTickIndexes(points.length, plotW, compact ? 70 : 84);
    const barMax = Math.max(1, ...(bars ?? []).map((b) => b ?? 0));
    const spanMs = t1 - t0;
    const slot = points.length > 1 ? plotW / (points.length - 1) : plotW;
    return { xScale, yScale, px, bandPx, yTicks, xTickIdx, barMax, spanMs, lo, hi, slot, times };
  }, [
    points,
    band,
    bars,
    thresholds,
    yMin,
    yMax,
    plotW,
    margin.left,
    lineBottom,
    lineTop,
    compact,
  ]);

  const nearestIndex = (clientX: number, rect: DOMRect): number | null => {
    if (!points.length) return null;
    const x = clientX - rect.left;
    let best = 0;
    let bestDist = Infinity;
    geometry.px.forEach((p, i) => {
      const d = Math.abs(p.x - x);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    return best;
  };

  const setActive = (index: number | null) => {
    setHover(index);
    onActiveChange?.(index);
  };

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setActive(nearestIndex(event.clientX, rect));
  };

  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (!points.length) return;
    const current = active ?? points.length - 1;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setActive(Math.max(0, current - 1));
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      setActive(Math.min(points.length - 1, current + 1));
    } else if (event.key === 'Home') {
      event.preventDefault();
      setActive(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      setActive(points.length - 1);
    } else if (event.key === 'Escape') {
      setActive(null);
    }
  };

  const maxIndex = useMemo(() => {
    let best = -1;
    let bestValue = -Infinity;
    points.forEach((p, i) => {
      if (p.y !== null && p.y > bestValue) {
        bestValue = p.y;
        best = i;
      }
    });
    return best;
  }, [points]);
  const lastIndex = useMemo(() => {
    for (let i = points.length - 1; i >= 0; i -= 1) if (points[i]!.y !== null) return i;
    return -1;
  }, [points]);

  const activePoint = active !== null ? points[active] : undefined;
  const activePx = active !== null ? geometry.px[active] : undefined;
  const barW = Math.min(24, Math.max(2, geometry.slot - 2));
  const toneColor = (tone: ThresholdLine['tone']) =>
    tone === 'danger' ? STATUS.danger : tone === 'warn' ? STATUS.warn : AXIS;

  const rows: DataRow[] = points.map((p, i) => ({
    x: timeLabelLong(p.x),
    y: p.y === null ? 'No data' : yFormat(p.y),
    low: band?.[i]?.low == null ? '' : yFormat(band[i].low),
    high: band?.[i]?.high == null ? '' : yFormat(band[i].high),
    bars: bars?.[i] == null ? '' : formatInteger(bars[i]),
  }));
  const columns = [
    { key: 'x', label: 'Date' },
    { key: 'y', label: yLabel },
    ...(band
      ? [
          { key: 'low', label: 'Baseline low' },
          { key: 'high', label: 'Baseline high' },
        ]
      : []),
    ...(bars ? [{ key: 'bars', label: barsLabel }] : []),
  ];

  if (!points.length) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">
        No data in this period.
      </p>
    );
  }

  return (
    <div ref={ref} className="relative" data-testid={testId}>
      <svg
        width={width}
        height={totalHeight}
        viewBox={`0 0 ${width} ${totalHeight}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        tabIndex={0}
        className="block max-w-full overflow-visible rounded-md focus-visible:outline-offset-4"
        onPointerMove={onPointerMove}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKeyDown}
        onFocus={() => setActive(lastIndex >= 0 ? lastIndex : null)}
        onBlur={() => setActive(null)}
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>{description}</desc>

        {/* Gridlines and y axis labels (hairline, solid, recessive). */}
        {geometry.yTicks.map((t) => (
          <g key={t}>
            <line
              x1={margin.left}
              x2={margin.left + plotW}
              y1={geometry.yScale(t)}
              y2={geometry.yScale(t)}
              stroke={GRID}
              strokeWidth={1}
            />
            <text
              x={margin.left - 6}
              y={geometry.yScale(t)}
              textAnchor="end"
              dominantBaseline="central"
              className="num fill-muted text-[10.5px]"
            >
              {yFormat(t)}
            </text>
          </g>
        ))}

        {/* Baseline band and its center line. */}
        {geometry.bandPx ? (
          <>
            <path d={bandPath(geometry.bandPx)} fill={color} opacity={0.13} />
            <path
              d={linePath(geometry.bandPx.map((b) => ({ x: b.x, y: b.center })))}
              fill="none"
              stroke={color}
              strokeWidth={1}
              opacity={0.45}
            />
          </>
        ) : null}

        {/* Thresholds. */}
        {thresholds.map((t) => {
          const y = geometry.yScale(t.value);
          return (
            <g key={t.label}>
              <line
                x1={margin.left}
                x2={margin.left + plotW}
                y1={y}
                y2={y}
                stroke={toneColor(t.tone)}
                strokeWidth={1}
              />
              <text
                x={margin.left + plotW}
                y={y - 4}
                textAnchor="end"
                className="fill-muted text-[10px]"
              >
                {t.label}
              </text>
            </g>
          );
        })}

        {/* The series. */}
        <path
          d={linePath(geometry.px)}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {geometry.px.map((p, i) => {
          // Isolated points (gaps on both sides) need a dot or they vanish.
          const prev = geometry.px[i - 1]?.y ?? null;
          const next = geometry.px[i + 1]?.y ?? null;
          if (p.y === null || prev !== null || next !== null) return null;
          return <circle key={i} cx={p.x} cy={p.y} r={2.5} fill={color} />;
        })}

        {/* Direct labels: the maximum and the latest value. */}
        {annotate && !compact && lastIndex >= 0 && geometry.px[lastIndex]!.y !== null ? (
          <g>
            <circle
              cx={geometry.px[lastIndex]!.x}
              cy={geometry.px[lastIndex]!.y}
              r={4}
              fill={color}
              stroke="rgb(var(--raised))"
              strokeWidth={2}
            />
            <text
              x={geometry.px[lastIndex]!.x - 7}
              y={geometry.px[lastIndex]!.y - 9}
              textAnchor="end"
              className="num fill-ink text-[11px] font-semibold"
            >
              {yFormat(points[lastIndex]!.y!)}
            </text>
          </g>
        ) : null}
        {annotate &&
        !compact &&
        maxIndex >= 0 &&
        maxIndex !== lastIndex &&
        geometry.px[maxIndex]!.y !== null ? (
          <text
            x={
              geometry.px[maxIndex]!.x < margin.left + 36
                ? geometry.px[maxIndex]!.x + 6
                : geometry.px[maxIndex]!.x > margin.left + plotW - 36
                  ? geometry.px[maxIndex]!.x - 6
                  : geometry.px[maxIndex]!.x
            }
            y={geometry.px[maxIndex]!.y - 8}
            textAnchor={
              geometry.px[maxIndex]!.x < margin.left + 36
                ? 'start'
                : geometry.px[maxIndex]!.x > margin.left + plotW - 36
                  ? 'end'
                  : 'middle'
            }
            className="num fill-muted text-[10.5px] font-medium"
          >
            peak {yFormat(points[maxIndex]!.y!)}
          </text>
        ) : null}

        {/* Bars strip under the line. */}
        {barStrip ? (
          <g>
            <line
              x1={margin.left}
              x2={margin.left + plotW}
              y1={lineBottom + 10 + barStrip}
              y2={lineBottom + 10 + barStrip}
              stroke={AXIS}
              strokeWidth={1}
            />
            <text
              x={margin.left - 6}
              y={lineBottom + 10 + barStrip / 2}
              textAnchor="end"
              dominantBaseline="central"
              className="fill-muted text-[10px]"
            >
              {barsLabel.length > 10 ? barsLabel.slice(0, 9) : barsLabel}
            </text>
            {bars!.map((b, i) => {
              if (!b) return null;
              const h = Math.max(1.5, (b / geometry.barMax) * (barStrip - 6));
              const x = geometry.px[i]!.x - barW / 2;
              return (
                <path
                  key={i}
                  d={columnPath(x, lineBottom + 10 + barStrip - h, barW, h, 3)}
                  fill={color}
                  opacity={active === i ? 0.7 : 0.4}
                />
              );
            })}
          </g>
        ) : null}

        {/* X axis. */}
        <line
          x1={margin.left}
          x2={margin.left + plotW}
          y1={lineBottom}
          y2={lineBottom}
          stroke={AXIS}
          strokeWidth={1}
        />
        {geometry.xTickIdx.map((i) => (
          <text
            key={i}
            x={geometry.px[i]!.x}
            y={totalHeight - 6}
            textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}
            className="fill-muted text-[10.5px]"
          >
            {timeLabel(points[i]!.x, geometry.spanMs)}
          </text>
        ))}

        {/* Crosshair and active marker. */}
        {activePx ? (
          <g aria-hidden="true">
            <line
              x1={activePx.x}
              x2={activePx.x}
              y1={lineTop}
              y2={barStrip ? lineBottom + 10 + barStrip : lineBottom}
              stroke={AXIS}
              strokeWidth={1}
            />
            {activePx.y !== null ? (
              <circle
                cx={activePx.x}
                cy={activePx.y}
                r={4.5}
                fill={color}
                stroke="rgb(var(--raised))"
                strokeWidth={2}
              />
            ) : null}
          </g>
        ) : null}
      </svg>

      {activePoint && activePx ? (
        <ChartTooltip x={activePx.x} y={Math.max(0, (activePx.y ?? lineTop) - 8)} width={width}>
          <p className="mb-1 font-medium text-ink">{timeLabelLong(activePoint.x)}</p>
          <TooltipRow
            swatch={color}
            label={yLabel}
            value={activePoint.y === null ? 'No data' : yFormat(activePoint.y)}
          />
          {band && band[active!] && band[active!]!.low !== null ? (
            <TooltipRow
              label="Baseline"
              value={`${yFormat(band[active!]!.low!)} to ${yFormat(band[active!]!.high!)}`}
            />
          ) : null}
          {bars && bars[active!] != null ? (
            <TooltipRow label={barsLabel} value={formatInteger(bars[active!]!)} />
          ) : null}
        </ChartTooltip>
      ) : null}

      <DataTable caption={caption} columns={columns} rows={rows} />
      <span className={cx('sr-only')}>{band ? bandLabel : null}</span>
    </div>
  );
}

import { useId } from 'react';
import { linePath, linearScale } from './scales';
import { MARK } from './theme';

/**
 * A 12-point-ish trend beside a stat. The whole line is in the de-emphasis
 * tone and the latest point carries the accent, per the stat-tile contract.
 */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  label,
  color = MARK,
}: {
  values: Array<number | null>;
  width?: number;
  height?: number;
  label: string;
  color?: string;
}) {
  const titleId = useId();
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (finite.length < 2) {
    return (
      <svg width={width} height={height} role="img" aria-labelledby={titleId} className="block">
        <title id={titleId}>{label}: not enough points for a trend</title>
        <line
          x1={2}
          x2={width - 2}
          y1={height / 2}
          y2={height / 2}
          stroke="rgb(var(--ink) / 0.12)"
          strokeWidth={1}
        />
      </svg>
    );
  }
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const pad = 4;
  const x = linearScale([0, values.length - 1], [pad, width - pad]);
  const y = linearScale([min, max === min ? min + 1 : max], [height - pad, pad]);
  const pts = values.map((v, i) => ({ x: x(i), y: v === null ? null : y(v) }));
  let last = -1;
  for (let i = values.length - 1; i >= 0; i -= 1) {
    if (values[i] !== null) {
      last = i;
      break;
    }
  }
  const first = finite[0]!;
  const latest = finite[finite.length - 1]!;
  const direction = latest > first ? 'up' : latest < first ? 'down' : 'flat';

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-labelledby={titleId}
      className="block overflow-visible"
    >
      <title id={titleId}>
        {label}: {direction} over the period, from {first} to {latest}
      </title>
      <path
        d={linePath(pts)}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity={0.55}
      />
      {last >= 0 && pts[last]!.y !== null ? (
        <circle
          cx={pts[last]!.x}
          cy={pts[last]!.y!}
          r={3}
          fill={color}
          stroke="rgb(var(--raised))"
          strokeWidth={1.5}
        />
      ) : null}
    </svg>
  );
}

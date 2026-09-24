/** Evenly spaced "nice" ticks from 0 (or min) to max. */
function niceTicks(min: number, max: number, candidates: number[], maxTicks: number): number[] {
  const span = max - min;
  if (!(span > 0)) return [min];
  const step = candidates.find((c) => span / c <= maxTicks) ?? candidates[candidates.length - 1]!;
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + 1e-9; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return ticks;
}

export function timeTicks(duration: number, maxTicks = 8): number[] {
  return niceTicks(
    0,
    duration,
    [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600],
    maxTicks,
  );
}

export function frequencyTicks(minHz: number, maxHz: number, maxTicks = 5): number[] {
  return niceTicks(minHz, maxHz, [250, 500, 1000, 2000, 4000, 5000, 8000, 10000, 20000], maxTicks);
}

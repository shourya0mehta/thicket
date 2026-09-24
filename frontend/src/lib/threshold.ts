import { FALLBACK_RAW_THRESHOLD, THRESHOLD_MAX, THRESHOLD_STEP } from '../config';

/** Rounds to two decimals to remove floating point noise (0.15000000000000002). */
export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function thresholdBounds(rawThreshold: number | null | undefined): {
  min: number;
  max: number;
} {
  const min =
    typeof rawThreshold === 'number' &&
    Number.isFinite(rawThreshold) &&
    rawThreshold < THRESHOLD_MAX
      ? round2(rawThreshold)
      : FALLBACK_RAW_THRESHOLD;
  return { min, max: THRESHOLD_MAX };
}

/** Snaps to the slider grid (min + k * step) and clamps to [min, max]. */
export function snapThreshold(value: number, min: number, max = THRESHOLD_MAX): number {
  const steps = Math.round((value - min) / THRESHOLD_STEP);
  const snapped = round2(min + steps * THRESHOLD_STEP);
  return Math.min(max, Math.max(min, snapped));
}

export function thresholdPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function sameThreshold(a: number, b: number): boolean {
  return Math.abs(a - b) < 0.0005;
}

import type { Taxon } from '../../api/generated';

/**
 * Chart color roles. Series identity for taxa uses four fixed categorical
 * slots (never cycled) defined as CSS variables per theme in index.css and
 * validated with the dataviz palette checks; every taxon mark is also paired
 * with an icon and a label. Magnitude uses one hue (the forest mark color)
 * from light to dark. Status uses the ok, warn and danger tokens with an icon
 * and a label, never color alone.
 */
export const TAXON_SLOT: Record<Taxon, string> = {
  bird: 'var(--viz-bird)',
  amphibian: 'var(--viz-amphibian)',
  insect: 'var(--viz-insect)',
  mammal: 'var(--viz-mammal)',
  human: 'var(--viz-other)',
  domestic_animal: 'var(--viz-other)',
  anthropogenic: 'var(--viz-other)',
  environmental: 'var(--viz-other)',
  noise: 'var(--viz-other)',
};

/** Fixed display order for taxon series (slot order, never re-ranked by value). */
export const TAXON_ORDER: Taxon[] = ['bird', 'amphibian', 'insect', 'mammal'];

export const MARK = 'rgb(var(--mark))';
export const MARK_SOFT = 'rgb(var(--mark) / 0.12)';
export const INK = 'rgb(var(--ink))';
export const MUTED = 'rgb(var(--muted))';
export const SUBTLE = 'rgb(var(--subtle))';
export const GRID = 'rgb(var(--ink) / 0.09)';
export const AXIS = 'rgb(var(--ink) / 0.22)';
export const SURFACE = 'rgb(var(--raised))';
export const STATUS = {
  ok: 'rgb(var(--ok))',
  warn: 'rgb(var(--warn))',
  danger: 'rgb(var(--danger))',
  info: 'rgb(var(--info))',
} as const;

/** One-hue sequential fill: the mark color at an opacity that grows with t in [0, 1]. */
export function sequentialFill(t: number, floor = 0.08, ceiling = 0.92): string {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  const alpha = floor + (ceiling - floor) * clamped;
  return `rgb(var(--mark) / ${alpha.toFixed(3)})`;
}

export const CHART_FONT = 'text-[11px]';
export const CHART_FONT_SM = 'text-[10.5px]';

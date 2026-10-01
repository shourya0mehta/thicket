import { useId, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { Panel } from '../ui/Panel';

export interface DataColumn {
  key: string;
  label: string;
}

export type DataRow = Record<string, ReactNode>;

/** Visually hidden table twin of a chart: every value readable without the picture. */
export function DataTable({
  caption,
  columns,
  rows,
  className,
}: {
  caption: string;
  columns: DataColumn[];
  rows: DataRow[];
  className?: string;
}) {
  return (
    <div className={cx('sr-only', className)} data-testid="chart-data-table">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c, j) =>
                j === 0 ? (
                  <th key={c.key} scope="row">
                    {row[c.key]}
                  </th>
                ) : (
                  <td key={c.key}>{row[c.key]}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Card around a chart: eyebrow, title, a right-aligned note, the chart, then a
 * footnote. `headingId` is exposed so the SVG can be labelled by the title.
 */
export function ChartFrame({
  eyebrow,
  title,
  note,
  children,
  footer,
  className,
  bodyClassName,
  dimmed,
  testId,
  as = 'section',
  plain,
}: {
  eyebrow?: string;
  title: string;
  note?: ReactNode;
  children: (ids: { headingId: string }) => ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  dimmed?: boolean;
  testId?: string;
  as?: 'section' | 'div';
  /** Render without the panel chrome (for small multiples inside another panel). */
  plain?: boolean;
}) {
  const headingId = useId();
  const header = (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <div className="min-w-0">
        {eyebrow ? <p className="eyebrow mb-1">{eyebrow}</p> : null}
        <h3
          id={headingId}
          className={cx('font-semibold tracking-tight text-ink', plain ? 'text-sm' : 'text-base')}
        >
          {title}
        </h3>
      </div>
      {note ? <p className="text-xs text-muted">{note}</p> : null}
    </div>
  );
  const body = (
    <div
      className={cx('transition-opacity', dimmed ? 'opacity-60' : 'opacity-100', bodyClassName)}
      aria-busy={dimmed || undefined}
    >
      {children({ headingId })}
    </div>
  );
  const foot = footer ? (
    <div className="mt-3 text-xs leading-relaxed text-muted">{footer}</div>
  ) : null;

  if (plain) {
    return (
      <div className={className} data-testid={testId}>
        {header}
        {body}
        {foot}
      </div>
    );
  }
  return (
    <Panel as={as} labelledBy={headingId} className={cx('p-5 sm:p-6', className)}>
      <div data-testid={testId}>
        {header}
        {body}
        {foot}
      </div>
    </Panel>
  );
}

/** Floating readout for hover and keyboard focus; values lead, labels follow. */
export function ChartTooltip({
  x,
  y,
  width,
  children,
  align = 'auto',
}: {
  x: number;
  y: number;
  /** Container width, to keep the bubble inside. */
  width: number;
  children: ReactNode;
  align?: 'auto' | 'left' | 'right';
}) {
  const flip = align === 'right' || (align === 'auto' && x > width * 0.62);
  return (
    <div
      className="pointer-events-none absolute z-20 w-max max-w-[16rem] rounded-lg border border-line bg-raised px-3 py-2 text-xs shadow-lift"
      style={{
        top: y,
        left: flip ? undefined : x + 12,
        right: flip ? Math.max(0, width - x + 12) : undefined,
      }}
      aria-hidden="true"
      data-testid="chart-tooltip"
    >
      {children}
    </div>
  );
}

export function TooltipRow({
  swatch,
  label,
  value,
}: {
  swatch?: string;
  label: string;
  value: ReactNode;
}) {
  return (
    <p className="flex items-baseline justify-between gap-3">
      <span className="inline-flex items-center gap-1.5 text-muted">
        {swatch ? (
          <span
            className="inline-block h-0.5 w-3 rounded-full"
            style={{ backgroundColor: swatch }}
            aria-hidden="true"
          />
        ) : null}
        {label}
      </span>
      <span className="num font-semibold text-ink">{value}</span>
    </p>
  );
}

/** Legend item: a mark (rect for bars/areas, line for lines) beside a text label. */
export function LegendItem({
  color,
  shape = 'rect',
  children,
  icon,
}: {
  color: string;
  shape?: 'rect' | 'line' | 'band';
  children: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      {shape === 'line' ? (
        <span className="inline-block h-0.5 w-4 rounded-full" style={{ backgroundColor: color }} />
      ) : shape === 'band' ? (
        <span
          className="inline-block h-3 w-4 rounded-sm"
          style={{ backgroundColor: color, opacity: 0.35 }}
        />
      ) : (
        <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
      )}
      {icon}
      {children}
    </span>
  );
}

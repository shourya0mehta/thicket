import { useId, type ReactNode, type SelectHTMLAttributes, type InputHTMLAttributes } from 'react';
import type { FriendlyError } from '../../api/errors';
import { cx } from '../../lib/cx';
import { ErrorCallout } from '../feedback/ErrorCallout';
import { Sparkline } from '../charts/Sparkline';
import { ButtonLink } from '../ui/Button';
import { InfoTip } from '../ui/InfoTip';
import { Spinner } from '../ui/Spinner';

const NOT_A_CENSUS =
  'Counts are acoustic detection events, not animals. One animal can produce many events.';

/** Page title block shared by every platform page. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 max-w-3xl">
        {eyebrow ? <p className="eyebrow mb-1">{eyebrow}</p> : null}
        <h1 className="break-words text-[1.625rem] font-semibold leading-tight tracking-tight text-ink sm:text-[1.875rem]">
          {title}
        </h1>
        {description ? (
          <div className="mt-2 text-sm text-muted sm:text-base">{description}</div>
        ) : null}
        {children}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function KpiTile({
  label,
  value,
  unit,
  info,
  trend,
  trendLabel,
  href,
  testId,
}: {
  label: string;
  value: string;
  unit?: string;
  info: string;
  trend?: Array<number | null>;
  trendLabel?: string;
  href?: string;
  testId?: string;
}) {
  const figure = (
    <span className="text-[1.625rem] font-semibold leading-8 tracking-tight text-ink">
      {value}
      {unit ? <span className="ml-1 text-sm font-medium text-muted">{unit}</span> : null}
    </span>
  );
  return (
    <div className="well min-w-0 px-4 py-3" data-testid={testId}>
      <dt className="flex items-center gap-1 text-xs font-medium text-muted">
        <span>{label}</span>
        <InfoTip label={`About ${label.toLowerCase()}`}>
          {info} <span className="font-medium">{NOT_A_CENSUS}</span>
        </InfoTip>
      </dt>
      <dd className="mt-1 flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
        {href ? (
          <a href={href} className="rounded-lg hover:underline">
            {figure}
            <span className="sr-only"> (open the list)</span>
          </a>
        ) : (
          figure
        )}
        {trend && trend.length > 1 ? (
          <Sparkline values={trend} label={trendLabel ?? `${label} trend`} width={84} height={26} />
        ) : null}
      </dd>
    </div>
  );
}

export function LoadingState({ label = 'Loading...' }: { label?: string }) {
  return (
    <p className="flex items-center gap-2 py-6 text-sm text-muted" role="status">
      <Spinner size={14} /> {label}
    </p>
  );
}

export function EmptyState({
  title,
  children,
  action,
  testId,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <div
      className="rounded-2xl border border-dashed border-line-strong px-5 py-8 text-center"
      data-testid={testId}
    >
      <p className="text-sm font-semibold text-ink">{title}</p>
      {children ? <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div> : null}
      {action ? <div className="mt-4 flex justify-center gap-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  backHref,
  backLabel = 'Back to the dashboard',
}: {
  error: FriendlyError;
  onRetry?: () => void;
  backHref?: string;
  backLabel?: string;
}) {
  return (
    <div className="space-y-3">
      <ErrorCallout
        error={{ ...error, action: onRetry ? 'retry' : error.action }}
        onRetry={onRetry}
      />
      {backHref ? (
        <ButtonLink href={backHref} size="sm" variant="ghost">
          {backLabel}
        </ButtonLink>
      ) : null}
    </div>
  );
}

/** A labeled form control with hint and error text wired through aria. */
export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
  id: givenId,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  children: (props: {
    id: string;
    'aria-describedby': string | undefined;
    'aria-invalid': true | undefined;
  }) => ReactNode;
  className?: string;
  id?: string;
}) {
  const auto = useId();
  const id = givenId ?? auto;
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="field-label">
        {label}
        {required ? (
          <span className="ml-1 text-danger" aria-hidden="true">
            *
          </span>
        ) : null}
        {required ? <span className="sr-only"> (required)</span> : null}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {error ? (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="field-hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx('field-input', className)} {...rest}>
      {children}
    </select>
  );
}

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx('field-input', className)} {...rest} />;
}

export function Checkbox({
  label,
  hint,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className={cx('flex items-start gap-2.5', className)}>
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4 rounded border-line-strong accent-forest-600"
        {...rest}
      />
      <label htmlFor={id} className="text-sm text-ink">
        {label}
        {hint ? <span className="block text-xs text-muted">{hint}</span> : null}
      </label>
    </div>
  );
}

/** Two-column definition list for facts. */
export function Facts({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-xs text-muted">{item.label}</dt>
          <dd className="mt-0.5 break-words font-medium text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionHeading({
  id,
  eyebrow,
  children,
  note,
}: {
  id?: string;
  eyebrow?: string;
  children: ReactNode;
  note?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
      <div>
        {eyebrow ? <p className="eyebrow mb-1">{eyebrow}</p> : null}
        <h2 id={id} className="text-base font-semibold tracking-tight text-ink">
          {children}
        </h2>
      </div>
      {note ? <p className="text-xs text-muted">{note}</p> : null}
    </div>
  );
}

export function ReadOnlyNote({ children }: { children?: ReactNode }) {
  return (
    <p className="text-xs text-muted" data-testid="read-only-note">
      {children ?? 'Your role is read-only here. Ask an owner or manager to make changes.'}
    </p>
  );
}

import type { ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { AlertIcon, CheckCircleIcon, InfoIcon, XCircleIcon } from './icons';

export type CalloutTone = 'info' | 'ok' | 'warn' | 'danger';

const TONES: Record<CalloutTone, { box: string; icon: string }> = {
  info: { box: 'border-info/25 bg-info-soft', icon: 'text-info' },
  ok: { box: 'border-ok/25 bg-ok-soft', icon: 'text-ok' },
  warn: { box: 'border-warn/30 bg-warn-soft', icon: 'text-warn' },
  danger: { box: 'border-danger/30 bg-danger-soft', icon: 'text-danger' },
};

const ICONS: Record<CalloutTone, typeof InfoIcon> = {
  info: InfoIcon,
  ok: CheckCircleIcon,
  warn: AlertIcon,
  danger: XCircleIcon,
};

export function Callout({
  tone = 'info',
  title,
  children,
  actions,
  role,
  className,
  icon,
  titleAs: TitleTag = 'p',
}: {
  tone?: CalloutTone;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  role?: 'alert' | 'status';
  className?: string;
  icon?: ReactNode;
  titleAs?: 'p' | 'h2' | 'h3';
}) {
  const Icon = ICONS[tone];
  return (
    <div
      role={role}
      className={cx(
        'flex gap-3 rounded-2xl border px-4 py-3.5 text-sm',
        TONES[tone].box,
        className,
      )}
    >
      <span className={cx('mt-0.5 shrink-0', TONES[tone].icon)}>{icon ?? <Icon size={18} />}</span>
      <div className="min-w-0 flex-1">
        {title ? <TitleTag className="font-semibold text-ink">{title}</TitleTag> : null}
        {children ? (
          <div className={cx('text-ink/85 dark:text-ink/80', title ? 'mt-1' : '')}>{children}</div>
        ) : null}
        {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

import { cx } from '../../lib/cx';
import { formatMs } from '../../lib/format';
import type { StageItem, StageState } from '../../lib/stages';
import { CheckIcon, XIcon } from '../ui/icons';
import { Spinner } from '../ui/Spinner';

const STATE_TEXT: Record<StageState, string> = {
  done: 'done',
  active: 'in progress',
  pending: 'not started',
  failed: 'failed',
};

function StageMarker({ state }: { state: StageState }) {
  if (state === 'done') {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-mark text-white dark:text-forest-950">
        <CheckIcon size={14} strokeWidth={2.25} />
      </span>
    );
  }
  if (state === 'active') {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full border border-mark/50 bg-mark/10 text-accent">
        <Spinner size={14} />
      </span>
    );
  }
  if (state === 'failed') {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-danger text-white dark:text-forest-950">
        <XIcon size={14} strokeWidth={2.25} />
      </span>
    );
  }
  return <span className="block h-6 w-6 rounded-full border border-dashed border-line-strong" />;
}

export function StageList({ stages, className }: { stages: StageItem[]; className?: string }) {
  return (
    <ol
      aria-label="Analysis stages"
      className={cx('space-y-0', className)}
      data-testid="stage-list"
    >
      {stages.map((stage, index) => (
        <li
          key={stage.key}
          aria-current={stage.state === 'active' ? 'step' : undefined}
          data-state={stage.state}
          className="relative flex items-center gap-3 py-1.5"
        >
          {index < stages.length - 1 ? (
            <span
              aria-hidden="true"
              className={cx(
                'absolute left-[11.5px] top-[30px] h-[calc(100%-24px)] w-0 border-l',
                stage.state === 'done' ? 'border-mark/50' : 'border-dashed border-line-strong',
              )}
            />
          ) : null}
          <StageMarker state={stage.state} />
          <span
            className={cx(
              'text-sm',
              stage.state === 'active'
                ? 'font-semibold text-ink'
                : stage.state === 'done'
                  ? 'text-ink'
                  : stage.state === 'failed'
                    ? 'font-semibold text-danger'
                    : 'text-muted',
            )}
          >
            {stage.label}
            <span className="sr-only">, {STATE_TEXT[stage.state]}</span>
          </span>
          {stage.durationMs !== null ? (
            <span className="num ml-auto text-xs text-muted">{formatMs(stage.durationMs)}</span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

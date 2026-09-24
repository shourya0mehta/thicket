import { useId } from 'react';
import { DEFAULT_THRESHOLD, THRESHOLD_STEP } from '../../config';
import { cx } from '../../lib/cx';
import {
  sameThreshold,
  snapThreshold,
  thresholdBounds,
  thresholdPercent,
} from '../../lib/threshold';
import { InfoTip } from '../ui/InfoTip';
import { Spinner } from '../ui/Spinner';

export function ThresholdControl({
  value,
  applied,
  rawThreshold,
  onChange,
  updating,
  failed = false,
  className,
}: {
  /** Requested threshold (slider position). */
  value: number;
  /** Threshold the displayed results were computed with. */
  applied: number;
  rawThreshold: number | null | undefined;
  onChange: (value: number) => void;
  updating: boolean;
  /** The last recompute failed; results still show the applied threshold. */
  failed?: boolean;
  className?: string;
}) {
  const id = useId();
  const { min, max } = thresholdBounds(rawThreshold);
  const pending = !sameThreshold(value, applied);

  return (
    <div className={cx('min-w-0', className)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <label htmlFor={id} className="text-sm font-medium text-ink">
            Decision threshold
          </label>
          <InfoTip label="About the decision threshold">
            A detection window counts only when the model&apos;s confidence is at or above this
            value. Moving it recomputes events, species, metrics and exports on the server from the
            stored raw detections. Windows below the {thresholdPercent(min)} ingestion floor are
            never stored.
          </InfoTip>
        </div>
        <output
          htmlFor={id}
          className="num text-lg font-semibold tabular-nums text-ink"
          aria-live="off"
        >
          {thresholdPercent(value)}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={THRESHOLD_STEP}
        value={value}
        onChange={(event) => onChange(snapThreshold(Number(event.target.value), min, max))}
        aria-valuetext={thresholdPercent(value)}
        className="mt-2 h-1.5 w-full cursor-pointer accent-forest-600 dark:accent-forest-400"
      />
      <div
        className="num mt-1 flex justify-between text-[0.6875rem] text-subtle"
        aria-hidden="true"
      >
        <span>{thresholdPercent(min)}</span>
        <span>{thresholdPercent(max)}</span>
      </div>
      <p className="mt-1.5 flex min-h-5 items-center gap-2 text-xs text-muted" aria-live="polite">
        {updating || (pending && !failed) ? (
          <>
            <Spinner size={12} />
            <span>Updating results for {thresholdPercent(value)}...</span>
          </>
        ) : (
          <span>
            {failed && pending ? <span className="text-danger">Update failed. </span> : null}
            <span data-testid="applied-threshold">
              Showing results at {thresholdPercent(applied)}
            </span>
            {!sameThreshold(applied, DEFAULT_THRESHOLD) ? (
              <>
                {' · '}
                <button
                  type="button"
                  className="link text-xs"
                  onClick={() => onChange(snapThreshold(DEFAULT_THRESHOLD, min, max))}
                >
                  Reset to {thresholdPercent(DEFAULT_THRESHOLD)}
                </button>
              </>
            ) : null}
          </span>
        )}
      </p>
    </div>
  );
}

import { pluralize } from '../../lib/format';
import { thresholdPercent } from '../../lib/threshold';
import { Button } from '../ui/Button';
import { Panel } from '../ui/Panel';
import { LeafMark } from '../layout/LeafMark';

/**
 * A valid, completed result in which nothing counts at the decision threshold:
 * either no species was detected, or every wildlife event above it was
 * rejected in review or flagged unlikely (those are listed further down).
 */
export function NoDetections({
  threshold,
  lowerTo,
  onLower,
  excluded = 0,
}: {
  threshold: number;
  /** Suggested lower threshold, or null when already at the floor. */
  lowerTo: number | null;
  onLower: (value: number) => void;
  /** Wildlife events above the threshold that do not count (rejected or unlikely). */
  excluded?: number;
}) {
  return (
    <Panel labelledBy="no-detections-heading" className="p-6 sm:p-8">
      <div
        className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:gap-6"
        data-testid="no-detections"
      >
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-mark/10">
          <LeafMark className="h-8 w-8" />
        </span>
        <div className="min-w-0">
          <h3
            id="no-detections-heading"
            className="text-base font-semibold tracking-tight text-ink"
          >
            {excluded
              ? `No counted species at ${thresholdPercent(threshold)}`
              : `No detection events above ${thresholdPercent(threshold)}`}
          </h3>
          {excluded ? (
            <p className="mt-1 max-w-xl text-sm leading-relaxed text-muted">
              The model did detect wildlife at or above this decision threshold, but{' '}
              {excluded === 1 ? 'that event was' : `all ${pluralize(excluded, 'event')} were`}{' '}
              rejected in review or flagged as unlikely for this place and season, so no species
              count toward the metrics. {excluded === 1 ? 'It is' : 'They are'} listed below.
            </p>
          ) : (
            <p className="mt-1 max-w-xl text-sm leading-relaxed text-muted">
              The analysis finished normally; the model did not find any species at or above this
              decision threshold. Quiet recordings, distant or faint calls, and wind often look like
              this. You can lower the threshold to review weaker detections, which are more likely
              to be wrong.
            </p>
          )}
          {lowerTo !== null ? (
            <Button size="sm" variant="secondary" className="mt-3" onClick={() => onLower(lowerTo)}>
              Show results at {thresholdPercent(lowerTo)}
            </Button>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}

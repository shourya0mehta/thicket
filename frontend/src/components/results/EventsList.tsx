import { memo, useMemo } from 'react';
import type { DetectionEvent, ReviewStatus } from '../../api/types';
import { correctedCopy, eventsAtTime, isRejected, isRelabeled } from '../../lib/analysis';
import { cx } from '../../lib/cx';
import { formatClockPrecise, formatPercent, pluralize } from '../../lib/format';
import { TAXON_LABEL } from '../../lib/taxa';
import { thresholdPercent } from '../../lib/threshold';
import { usePlayback, usePlaybackTime } from '../../state/playbackContext';
import { Badge } from '../ui/Badge';
import { CheckIcon, PlayIcon, TaxonIcon, WaveformIcon, XIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';
import { Spinner } from '../ui/Spinner';

function ReviewBadge({ event }: { event: DetectionEvent }) {
  switch (event.review_status) {
    case 'accepted':
      return (
        <Badge tone="ok" icon={<CheckIcon size={12} />}>
          Accepted
        </Badge>
      );
    case 'rejected':
      return (
        <Badge tone="danger" icon={<XIcon size={12} />}>
          Rejected
        </Badge>
      );
    case 'corrected':
      return <Badge tone="info">{correctedCopy(event)}</Badge>;
    default:
      return <Badge tone="neutral">Not reviewed</Badge>;
  }
}

interface RowProps {
  event: DetectionEvent;
  active: boolean;
  selected: boolean;
  reviewing: boolean;
  reviewDisabledReason: string | null;
  onSelect: (event: DetectionEvent) => void;
  onReview: (eventId: string, status: ReviewStatus) => void;
}

const EventRow = memo(function EventRow({
  event,
  active,
  selected,
  reviewing,
  reviewDisabledReason,
  onSelect,
  onReview,
}: RowProps) {
  const excluded = !event.counted_in_metrics;
  const relabeled = isRelabeled(event);
  const status = event.review_status ?? 'unreviewed';
  const disabled = reviewing || reviewDisabledReason !== null;
  const range = `${formatClockPrecise(event.start_seconds)} to ${formatClockPrecise(event.end_seconds)}`;

  return (
    <tr
      aria-current={selected ? 'true' : undefined}
      data-active={active || undefined}
      data-selected={selected || undefined}
      data-testid="event-row"
      className={cx(
        'align-middle transition-colors',
        active ? 'bg-mark/10' : selected ? 'bg-mark/[0.06]' : 'hover:bg-surface-muted',
      )}
    >
      <td
        className={cx(
          'border-l-[3px] py-2.5 pl-4 pr-3 sm:pl-5',
          selected || active ? 'border-l-mark' : 'border-l-transparent',
        )}
      >
        <button
          type="button"
          onClick={() => onSelect(event)}
          className="num inline-flex items-center gap-2 whitespace-nowrap rounded-lg px-1.5 py-1 font-medium text-accent hover:bg-mark/10"
          aria-label={`Play ${event.common_name} from ${range}`}
        >
          <PlayIcon size={11} />
          <span>
            {formatClockPrecise(event.start_seconds)}
            <span className="hidden sm:inline"> to {formatClockPrecise(event.end_seconds)}</span>
          </span>
        </button>
        {active ? (
          <span className="ml-1.5 inline-flex items-center gap-1 text-xs font-medium text-accent">
            <WaveformIcon size={13} />
            Playing
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2.5">
        <span
          className={cx(
            'block font-medium text-ink',
            excluded && 'line-through decoration-danger/60',
          )}
        >
          {event.common_name}
        </span>
        <span className="sci block text-xs text-muted">{event.scientific_name}</span>
        {relabeled ? (
          <span className="block text-xs text-muted" data-testid="detected-as">
            Detected as {event.detected_common_name}
          </span>
        ) : null}
        <span className="num mt-0.5 block text-xs text-muted md:hidden">
          {formatPercent(event.max_confidence)} max · {TAXON_LABEL[event.taxon]}
          {status !== 'unreviewed'
            ? ` · ${status === 'accepted' ? 'Accepted' : status === 'rejected' ? 'Rejected' : correctedCopy(event)}`
            : ''}
        </span>
      </td>
      <td className="hidden whitespace-nowrap px-3 py-2.5 text-muted lg:table-cell">
        <span className="inline-flex items-center gap-1.5">
          <TaxonIcon taxon={event.taxon} size={14} className="text-subtle" />
          {TAXON_LABEL[event.taxon]}
        </span>
      </td>
      <td className="num hidden whitespace-nowrap px-3 py-2.5 text-right md:table-cell">
        <span className="font-semibold text-ink">{formatPercent(event.max_confidence)}</span>
        <span className="block text-xs text-muted">
          mean {formatPercent(event.mean_confidence)}
        </span>
      </td>
      <td className="num hidden px-3 py-2.5 text-right text-muted xl:table-cell">
        {event.n_windows}
      </td>
      <td className="hidden px-3 py-2.5 md:table-cell">
        <div className="flex flex-col items-start gap-1">
          <ReviewBadge event={event} />
          {excluded ? (
            <span className="text-[0.6875rem] text-muted">Excluded from metrics</span>
          ) : null}
        </div>
      </td>
      <td className="whitespace-nowrap py-2.5 pl-3 pr-4 text-right sm:pr-5">
        <div
          className="inline-flex items-center gap-1"
          role="group"
          aria-label={`Review ${event.common_name} at ${formatClockPrecise(event.start_seconds)}`}
          title={reviewDisabledReason ?? undefined}
        >
          {reviewing ? (
            <Spinner size={14} label="Saving review" className="mr-1 text-muted" />
          ) : null}
          <button
            type="button"
            disabled={disabled}
            aria-pressed={status === 'accepted'}
            onClick={() => onReview(event.id, status === 'accepted' ? 'unreviewed' : 'accepted')}
            className={cx(
              'inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              status === 'accepted'
                ? 'border-ok/40 bg-ok-soft text-ok'
                : 'border-line-strong text-ink hover:border-ok/50 hover:bg-ok-soft',
            )}
          >
            <CheckIcon size={13} />
            <span className="sr-only sm:not-sr-only">
              {status === 'accepted' ? 'Accepted' : 'Accept'}
            </span>
          </button>
          <button
            type="button"
            disabled={disabled}
            aria-pressed={status === 'rejected'}
            onClick={() => onReview(event.id, status === 'rejected' ? 'unreviewed' : 'rejected')}
            className={cx(
              'inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              status === 'rejected'
                ? 'border-danger/40 bg-danger-soft text-danger'
                : 'border-line-strong text-ink hover:border-danger/50 hover:bg-danger-soft',
            )}
          >
            <XIcon size={13} />
            <span className="sr-only sm:not-sr-only">
              {status === 'rejected' ? 'Rejected' : 'Reject'}
            </span>
          </button>
        </div>
      </td>
    </tr>
  );
});

export function EventsList({
  events,
  threshold,
  reviewingEventId,
  reviewDisabledReason,
  onReview,
  dimmed,
}: {
  events: DetectionEvent[];
  threshold: number;
  reviewingEventId: string | null;
  reviewDisabledReason: string | null;
  onReview: (eventId: string, status: ReviewStatus) => void;
  dimmed?: boolean;
}) {
  const { selectEvent, selectedEventId, playing } = usePlayback();
  const time = usePlaybackTime();
  const activeIds = useMemo(
    () => (playing ? eventsAtTime(events, time) : new Set<string>()),
    [events, time, playing],
  );
  const rejectedCount = events.filter(isRejected).length;
  const reviewedCount = events.filter(
    (e) => (e.review_status ?? 'unreviewed') !== 'unreviewed',
  ).length;

  return (
    <Panel labelledBy="events-heading" className="overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-2 px-5 pb-3 pt-5 sm:px-6">
        <div>
          <p className="eyebrow mb-1">Detection events</p>
          <h3 id="events-heading" className="text-base font-semibold tracking-tight text-ink">
            Review each detection event
          </h3>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Each row is a stretch of audio where one species was detected. Play it, then accept or
            reject it; rejected events are removed from the metrics.
          </p>
        </div>
        <p className="text-xs text-muted">
          {pluralize(events.length, 'event')} at {thresholdPercent(threshold)} · {reviewedCount}{' '}
          reviewed
          {rejectedCount ? ` · ${rejectedCount} rejected` : ''}
        </p>
      </div>
      <div
        className={cx(
          'max-h-[34rem] overflow-auto border-t border-line transition-opacity',
          dimmed ? 'opacity-60' : '',
        )}
      >
        <table className="w-full border-collapse text-sm" data-testid="events-table">
          <caption className="sr-only">
            Detection events at the {thresholdPercent(threshold)} decision threshold, in time order.
            Select a time to play that event.
          </caption>
          <thead className="sticky top-0 z-10 bg-raised text-xs text-muted shadow-[0_1px_0_rgb(var(--line))]">
            <tr>
              <th scope="col" className="py-2.5 pl-5 pr-3 text-left font-medium sm:pl-6">
                Time
              </th>
              <th scope="col" className="px-3 py-2.5 text-left font-medium">
                Species
              </th>
              <th scope="col" className="hidden px-3 py-2.5 text-left font-medium lg:table-cell">
                Taxon
              </th>
              <th scope="col" className="hidden px-3 py-2.5 text-right font-medium md:table-cell">
                Confidence
              </th>
              <th scope="col" className="hidden px-3 py-2.5 text-right font-medium xl:table-cell">
                Windows
              </th>
              <th scope="col" className="hidden px-3 py-2.5 text-left font-medium md:table-cell">
                Review status
              </th>
              <th scope="col" className="py-2.5 pl-3 pr-4 text-right font-medium sm:pr-5">
                Review
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {events.map((event) => (
              <EventRow
                key={event.id}
                event={event}
                active={activeIds.has(event.id)}
                selected={selectedEventId === event.id}
                reviewing={reviewingEventId === event.id}
                reviewDisabledReason={reviewDisabledReason}
                onSelect={selectEvent}
                onReview={onReview}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

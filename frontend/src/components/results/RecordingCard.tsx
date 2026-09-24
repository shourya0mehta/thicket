import type { ReactNode } from 'react';
import type { RecordingInfo } from '../../api/types';
import { hasValidCoordinates } from '../../lib/analysis';
import { cx } from '../../lib/cx';
import {
  formatBytes,
  formatCoordinate,
  formatDateTime,
  formatDuration,
  formatHz,
} from '../../lib/format';
import { Panel } from '../ui/Panel';
import { AudioControls } from './AudioControls';
import { Spectrogram } from './Spectrogram';

export function RecordingFacts({
  recording,
  className,
}: {
  recording: RecordingInfo;
  className?: string;
}) {
  const facts: Array<[string, ReactNode]> = [
    ['Duration', formatDuration(recording.duration_seconds)],
    ['Sample rate', formatHz(recording.sample_rate_hz)],
    [
      'Channels',
      recording.channels === 1
        ? 'Mono'
        : recording.channels === 2
          ? 'Stereo'
          : String(recording.channels),
    ],
    ['Format', recording.format ?? recording.content_type ?? 'Unknown'],
    ['File size', formatBytes(recording.byte_size)],
    [
      'Recorded',
      recording.captured_at
        ? formatDateTime(recording.captured_at, recording.timezone)
        : 'Not provided',
    ],
    [
      'Location',
      hasValidCoordinates(recording)
        ? `${formatCoordinate(recording.latitude, 'lat')}, ${formatCoordinate(recording.longitude, 'lon')}`
        : 'Location not provided',
    ],
  ];
  return (
    <dl className={cx('grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3', className)}>
      {facts.map(([term, value]) => (
        <div key={term} className="min-w-0">
          <dt className="text-xs text-muted">{term}</dt>
          <dd className="num mt-0.5 break-words font-medium text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RecordingCard({
  recording,
  spectrogramUrl,
  minHz,
  maxHz,
  headingId,
  eyebrow = 'Recording',
  headerExtra,
  audioUnavailableReason,
  children,
}: {
  recording: RecordingInfo;
  spectrogramUrl: string | null;
  minHz: number;
  maxHz: number;
  headingId: string;
  eyebrow?: string;
  headerExtra?: ReactNode;
  audioUnavailableReason?: string;
  children?: ReactNode;
}) {
  return (
    <Panel labelledBy={headingId} className="p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow mb-1">{eyebrow}</p>
          <h3
            id={headingId}
            className="truncate text-base font-semibold tracking-tight text-ink"
            title={recording.filename}
          >
            {recording.filename}
          </h3>
        </div>
        {headerExtra}
      </div>
      <Spectrogram
        src={spectrogramUrl}
        duration={recording.duration_seconds}
        minHz={minHz}
        maxHz={maxHz}
        label={`Spectrogram of ${recording.filename}`}
      />
      <AudioControls className="mt-4" unavailableReason={audioUnavailableReason} />
      <RecordingFacts recording={recording} className="mt-5 border-t border-line pt-5" />
      {children}
    </Panel>
  );
}

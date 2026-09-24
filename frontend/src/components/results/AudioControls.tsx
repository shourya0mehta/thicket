import { useId } from 'react';
import { cx } from '../../lib/cx';
import { formatClock } from '../../lib/format';
import { usePlayback, usePlaybackTime } from '../../state/playbackContext';
import { PauseIcon, PlayIcon, RewindIcon } from '../ui/icons';

export function AudioControls({
  unavailableReason,
  className,
}: {
  /** Shown instead of controls when there is no audio to play. */
  unavailableReason?: string;
  className?: string;
}) {
  const { hasAudio, playing, toggle, seek, duration, audioError } = usePlayback();
  const time = usePlaybackTime();
  const sliderId = useId();

  if (!hasAudio) {
    return (
      <p className={cx('text-sm text-muted', className)} data-testid="audio-unavailable">
        {audioError
          ? 'This audio could not be played in your browser. The analysis is unaffected.'
          : (unavailableReason ??
            'Audio is not stored on the server. Choose the original file to listen.')}
      </p>
    );
  }

  const max = duration > 0 ? duration : 0;

  return (
    <div className={cx('flex items-center gap-3', className)}>
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? 'Pause' : 'Play'}
        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-forest-600 text-white shadow-sm transition-colors hover:bg-forest-700 dark:hover:bg-forest-500"
      >
        {playing ? <PauseIcon size={16} /> : <PlayIcon size={16} className="translate-x-px" />}
      </button>
      <button
        type="button"
        onClick={() => seek(Math.max(0, time - 5))}
        aria-label="Back 5 seconds"
        title="Back 5 seconds"
        className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-muted hover:text-ink sm:inline-flex"
      >
        <RewindIcon size={16} />
      </button>
      <label htmlFor={sliderId} className="sr-only">
        Playback position
      </label>
      <input
        id={sliderId}
        type="range"
        min={0}
        max={max}
        step={0.1}
        value={Math.min(time, max)}
        onChange={(event) => seek(Number(event.target.value))}
        aria-valuetext={`${formatClock(time)} of ${formatClock(max)}`}
        className="h-1.5 min-w-0 flex-1 cursor-pointer accent-forest-600 dark:accent-forest-400"
      />
      <span className="num shrink-0 text-xs text-muted" aria-hidden="true">
        {formatClock(time)} / {formatClock(max)}
      </span>
    </div>
  );
}

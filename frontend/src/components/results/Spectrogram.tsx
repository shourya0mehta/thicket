import {
  memo,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from 'react';
import type { DetectionEvent } from '../../api/types';
import { useElementWidth } from '../../hooks/useElementWidth';
import { cx } from '../../lib/cx';
import { formatClock, formatClockPrecise, formatHz, formatPercent } from '../../lib/format';
import { frequencyTicks, timeTicks } from '../../lib/ticks';
import { usePlayback, usePlaybackTime } from '../../state/playbackContext';

export interface SpectrogramProps {
  src: string | null;
  /** Seconds covered horizontally by the image (0..duration). */
  duration: number;
  minHz: number;
  maxHz: number;
  /** Accessible name, e.g. "Spectrogram of dawn.wav". */
  label: string;
  /** CSS aspect ratio of the plot area. */
  aspect?: string;
  /** Detection events drawn as bands over the image. */
  events?: DetectionEvent[];
  activeIds?: ReadonlySet<string>;
  selectedId?: string | null;
  onEventSelect?: (event: DetectionEvent) => void;
  placeholder?: ReactNode;
  /** Tailwind width class for the frequency axis gutter; lets other rows align. */
  gutterClassName?: string;
  className?: string;
}

type ImageState = 'loading' | 'loaded' | 'error';

function pct(value: number, total: number): string {
  if (!(total > 0)) return '0%';
  return `${Math.min(100, Math.max(0, (value / total) * 100))}%`;
}

export function TimeAxis({ duration, className }: { duration: number; className?: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(480);
  // Roughly one label per 64px so labels never collide on narrow screens.
  const ticks = timeTicks(duration, Math.max(2, Math.min(8, Math.floor(width / 64))));
  return (
    <div ref={ref} className={cx('relative h-4', className)} aria-hidden="true">
      {ticks.map((t, i) => (
        <span
          key={t}
          className={cx(
            'num absolute whitespace-nowrap text-[0.6875rem] text-muted',
            i === 0 ? '' : t >= duration - 1e-6 ? '-translate-x-full' : '-translate-x-1/2',
          )}
          style={{ left: pct(t, duration) }}
        >
          {formatClock(t)}
        </span>
      ))}
    </div>
  );
}

export const Playhead = memo(function Playhead({
  duration,
  tone = 'dark',
}: {
  duration: number;
  /** "dark" draws on the spectrogram; "light" on a card surface. */
  tone?: 'dark' | 'light';
}) {
  const time = usePlaybackTime();
  const { playing } = usePlayback();
  if (!(duration > 0) || (time <= 0 && !playing)) return null;
  return (
    <div
      className={cx(
        'pointer-events-none absolute inset-y-0 z-20 w-px',
        tone === 'dark' ? 'bg-white/90 shadow-[0_0_0_1px_rgba(0,0,0,0.35)]' : 'bg-ink/80',
      )}
      style={{ left: pct(time, duration) }}
      data-testid="playhead"
      aria-hidden="true"
    >
      <span
        className={cx(
          'absolute -left-[4px] -top-px h-0 w-0 border-x-[4.5px] border-t-[6px] border-x-transparent',
          tone === 'dark' ? 'border-t-white' : 'border-t-ink/80',
        )}
      />
    </div>
  );
});

export function Spectrogram({
  src,
  duration,
  minHz,
  maxHz,
  label,
  aspect = '16 / 10',
  events,
  activeIds,
  selectedId,
  onEventSelect,
  placeholder,
  gutterClassName = 'w-11',
  className,
}: SpectrogramProps) {
  const { seek } = usePlayback();
  const plotRef = useRef<HTMLDivElement>(null);
  const [imageState, setImageState] = useState<ImageState>('loading');
  const [hover, setHover] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  useEffect(() => {
    setImageState('loading');
  }, [src]);

  const range = Math.max(1, maxHz - minHz);
  const fTicks = frequencyTicks(minHz, maxHz);

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const rect = plotRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    setHover({
      x: Math.min(rect.width, Math.max(0, event.clientX - rect.left)),
      y: Math.min(rect.height, Math.max(0, event.clientY - rect.top)),
      w: rect.width,
      h: rect.height,
    });
  };

  const onPlotClick = (event: MouseEvent<HTMLDivElement>) => {
    const rect = plotRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || !(duration > 0)) return;
    const fraction = (event.clientX - rect.left) / rect.width;
    seek(Math.min(duration, Math.max(0, fraction * duration)));
  };

  const hoverTime = hover ? (hover.x / hover.w) * duration : 0;
  const hoverHz = hover ? maxHz - (hover.y / hover.h) * range : 0;
  const showImage = Boolean(src) && imageState !== 'error';
  const description = `${label}. Time runs left to right from 0:00 to ${formatClock(duration)}; frequency runs bottom to top from ${formatHz(minHz)} to ${formatHz(maxHz)}.`;

  return (
    <figure className={cx('m-0 pt-1.5', className)}>
      <div className="flex">
        {/* Frequency axis: low frequencies at the bottom. */}
        <div className={cx('relative shrink-0', gutterClassName)} aria-hidden="true">
          {fTicks.map((hz) => (
            <span
              key={hz}
              className="num absolute right-2 -translate-y-1/2 whitespace-nowrap text-[0.6875rem] text-muted"
              style={{ top: pct(maxHz - hz, range) }}
            >
              {hz === 0 ? '0' : formatHz(hz).replace(' kHz', 'k')}
            </span>
          ))}
          <span className="absolute right-8 top-1/2 -translate-y-1/2 translate-x-1/2 -rotate-90 whitespace-nowrap text-[0.625rem] font-medium tracking-wide text-subtle">
            kHz
          </span>
        </div>

        <div className="min-w-0 flex-1">
          {/* Click-to-seek is a pointer convenience; keyboard users seek with the
              playback slider and the event lists. */}
          {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
          <div
            ref={plotRef}
            className="relative cursor-crosshair select-none overflow-hidden rounded-xl bg-viz ring-1 ring-black/10 dark:ring-white/10"
            style={{ aspectRatio: aspect }}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHover(null)}
            onClick={onPlotClick}
            data-testid="spectrogram-plot"
          >
            {showImage ? (
              <img
                src={src ?? undefined}
                alt={description}
                draggable={false}
                onLoad={() => setImageState('loaded')}
                onError={() => setImageState('error')}
                className={cx(
                  'pointer-events-none absolute inset-0 h-full w-full object-fill transition-opacity duration-300',
                  imageState === 'loaded' ? 'opacity-100' : 'opacity-0',
                )}
              />
            ) : null}

            {/* Quiet reference lines at the frequency ticks. */}
            {fTicks.map((hz) =>
              hz > minHz && hz < maxHz ? (
                <div
                  key={`grid-${hz}`}
                  className="pointer-events-none absolute inset-x-0 h-px bg-white/[0.07]"
                  style={{ top: pct(maxHz - hz, range) }}
                  aria-hidden="true"
                />
              ) : null,
            )}

            {!showImage || imageState === 'loading' ? (
              <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-viz-muted">
                {!src
                  ? (placeholder ??
                    'The spectrogram appears here after you generate it or run an analysis.')
                  : imageState === 'error'
                    ? 'The spectrogram image could not be loaded.'
                    : null}
              </div>
            ) : null}

            {events?.map((event) => {
              const highlighted = activeIds?.has(event.id) || selectedId === event.id;
              return (
                // Pointer shortcut only (aria-hidden); the timeline lanes are the keyboard path.
                <div
                  key={event.id}
                  className={cx(
                    'group absolute inset-y-0 z-10 transition-colors',
                    highlighted
                      ? 'border-x border-forest-200/80 bg-forest-200/[0.14]'
                      : 'hover:bg-white/[0.06]',
                  )}
                  style={{
                    left: pct(event.start_seconds, duration),
                    width: pct(event.end_seconds - event.start_seconds, duration),
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEventSelect?.(event);
                  }}
                  aria-hidden="true"
                  title={`${event.common_name}, ${formatClockPrecise(event.start_seconds)} to ${formatClockPrecise(event.end_seconds)}, max confidence ${formatPercent(event.max_confidence)}`}
                >
                  {/* Event extent marker along the top edge. */}
                  <span
                    className={cx(
                      'absolute inset-x-px top-1 h-1 rounded-full',
                      highlighted
                        ? 'bg-forest-100'
                        : 'bg-forest-200/45 group-hover:bg-forest-200/80',
                    )}
                  />
                </div>
              );
            })}

            <Playhead duration={duration} />

            {hover && duration > 0 ? (
              <>
                <div
                  className="pointer-events-none absolute inset-y-0 z-20 w-px bg-white/40"
                  style={{ left: hover.x }}
                  aria-hidden="true"
                />
                <div
                  className="num pointer-events-none absolute z-30 whitespace-nowrap rounded-md bg-black/75 px-2 py-1 text-[0.6875rem] font-medium text-white"
                  style={{
                    left: Math.min(hover.x + 10, hover.w - 118),
                    top: Math.max(6, Math.min(hover.y - 30, hover.h - 28)),
                  }}
                  aria-hidden="true"
                  data-testid="spectrogram-readout"
                >
                  {formatClockPrecise(hoverTime)} · {formatHz(Math.max(minHz, hoverHz))}
                </div>
              </>
            ) : null}
          </div>

          <TimeAxis duration={duration} className="mt-1.5" />
        </div>
      </div>
      <figcaption className="sr-only">
        Click the spectrogram to move playback to that time.
      </figcaption>
    </figure>
  );
}

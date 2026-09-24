import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ControlsContext, TimeContext, type PlaybackControls } from './playbackContext';

/**
 * Owns the one <audio> element of the workspace. Playback state is split into
 * two contexts so components that only need controls do not re-render on
 * every animation frame.
 */
export function PlaybackProvider({
  src,
  fallbackDuration,
  children,
}: {
  src: string | null;
  fallbackDuration: number;
  children: ReactNode;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const frame = useRef<number | null>(null);

  // Reset when the source changes (new file, new analysis).
  useEffect(() => {
    setCurrentTime(0);
    setMediaDuration(null);
    setPlaying(false);
    setAudioError(false);
    setSelectedEventId(null);
  }, [src]);

  // Smooth playhead while playing.
  useEffect(() => {
    if (!playing) return;
    const tick = () => {
      const audio = audioRef.current;
      if (audio) {
        setCurrentTime((prev) =>
          Math.abs(prev - audio.currentTime) >= 1 / 30 ? audio.currentTime : prev,
        );
      }
      frame.current = window.requestAnimationFrame(tick);
    };
    frame.current = window.requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) window.cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [playing]);

  const play = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !src) return;
    const result = audio.play() as Promise<void> | undefined;
    if (result && typeof result.catch === 'function') {
      result.catch(() => setPlaying(false));
    }
  }, [src]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) play();
    else pause();
  }, [play, pause]);

  const seek = useCallback((seconds: number) => {
    const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
    const audio = audioRef.current;
    if (audio) {
      try {
        audio.currentTime = safe;
      } catch {
        // Some browsers throw before metadata is available; the state still moves.
      }
    }
    setCurrentTime(safe);
  }, []);

  const selectEvent = useCallback(
    (event: { id: string; start_seconds: number }, options: { play?: boolean } = {}) => {
      setSelectedEventId(event.id);
      seek(event.start_seconds);
      if (options.play ?? true) play();
    },
    [play, seek],
  );

  const clearSelection = useCallback(() => setSelectedEventId(null), []);

  const duration =
    mediaDuration && Number.isFinite(mediaDuration) && mediaDuration > 0
      ? mediaDuration
      : fallbackDuration;

  const controls = useMemo<PlaybackControls>(
    () => ({
      src,
      playing,
      duration,
      hasAudio: Boolean(src) && !audioError,
      audioError,
      selectedEventId,
      play,
      pause,
      toggle,
      seek,
      selectEvent,
      clearSelection,
    }),
    [
      src,
      playing,
      duration,
      audioError,
      selectedEventId,
      play,
      pause,
      toggle,
      seek,
      selectEvent,
      clearSelection,
    ],
  );

  return (
    <ControlsContext.Provider value={controls}>
      <TimeContext.Provider value={currentTime}>
        {children}
        {src ? (
          // The element is a hidden playback engine for field recordings; there is no
          // speech track to caption. Visible controls live in AudioControls.
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <audio
            ref={audioRef}
            src={src}
            preload="metadata"
            data-testid="audio-element"
            onLoadedMetadata={(e) => setMediaDuration(e.currentTarget.duration)}
            onDurationChange={(e) => setMediaDuration(e.currentTarget.duration)}
            onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onError={() => {
              setAudioError(true);
              setPlaying(false);
            }}
          />
        ) : null}
      </TimeContext.Provider>
    </ControlsContext.Provider>
  );
}

import { createContext, useContext } from 'react';

export interface PlaybackControls {
  src: string | null;
  playing: boolean;
  /** Media duration once metadata is loaded, else the fallback (analysis) duration. */
  duration: number;
  hasAudio: boolean;
  audioError: boolean;
  selectedEventId: string | null;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (seconds: number) => void;
  /** Seek to an event's start, highlight it and start playback. */
  selectEvent: (event: { id: string; start_seconds: number }, options?: { play?: boolean }) => void;
  clearSelection: () => void;
}

export const ControlsContext = createContext<PlaybackControls | null>(null);
export const TimeContext = createContext<number>(0);

export function usePlayback(): PlaybackControls {
  const value = useContext(ControlsContext);
  if (!value) throw new Error('usePlayback must be used inside PlaybackProvider');
  return value;
}

export function usePlaybackTime(): number {
  return useContext(TimeContext);
}

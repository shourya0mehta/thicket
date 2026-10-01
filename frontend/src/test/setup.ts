import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

/** Mutable system preferences read by the matchMedia mock. */
export const media = { dark: false, reducedMotion: false };

function installMatchMedia() {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList => {
      const matches = query.includes('prefers-color-scheme: dark')
        ? media.dark
        : query.includes('prefers-reduced-motion')
          ? media.reducedMotion
          : query.includes('min-width');
      return {
        matches,
        media: query,
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      } as MediaQueryList;
    },
  });
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

let urlCounter = 0;

beforeEach(() => {
  // Most tests were written for a build that hides experimental models;
  // tests of the default (shown, badged) stub this flag themselves.
  vi.stubEnv('VITE_ENABLE_EXPERIMENTAL_MODELS', 'false');
  media.dark = false;
  media.reducedMotion = false;
  installMatchMedia();
  window.localStorage.clear();
  window.location.hash = '';
  document.documentElement.classList.remove('dark');
  vi.stubGlobal('ResizeObserver', ResizeObserverMock);
  window.scrollTo = vi.fn();
  URL.createObjectURL = vi.fn(() => `blob:thicket-test/${++urlCounter}`);
  URL.revokeObjectURL = vi.fn();
  // jsdom does not implement media playback; emit the events the app listens to.
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value(this: HTMLMediaElement) {
      this.dispatchEvent(new Event('play'));
      return Promise.resolve();
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value(this: HTMLMediaElement) {
      this.dispatchEvent(new Event('pause'));
    },
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

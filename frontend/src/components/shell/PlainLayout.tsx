import type { ReactNode, RefObject } from 'react';
import { homeHref } from '../../lib/routes';
import type { Theme } from '../../lib/theme';
import { DemoBanner } from '../layout/DemoBanner';
import { Footer } from '../layout/Footer';
import { LeafMark } from '../layout/LeafMark';
import { ThemeToggle } from '../layout/ThemeToggle';

/** Header, main and footer for pages outside an organization (sign-in, picker, invite). */
export function PlainLayout({
  theme,
  onToggleTheme,
  mainRef,
  demo,
  nav,
  children,
}: {
  theme: Theme;
  onToggleTheme: () => void;
  mainRef: RefObject<HTMLElement>;
  demo?: boolean;
  nav?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          mainRef.current?.focus();
        }}
        className="sr-only z-50 rounded-lg bg-raised px-3 py-2 text-sm font-medium text-ink shadow-lift focus:not-sr-only focus:fixed focus:left-4 focus:top-3"
      >
        Skip to main content
      </a>
      <header className="border-b border-line">
        <div className="mx-auto flex h-16 max-w-page items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <a href={homeHref()} className="flex min-w-0 items-center gap-2.5 rounded-lg">
            <LeafMark className="h-8 w-8" />
            <span className="min-w-0 leading-tight">
              <span className="block text-[1.0625rem] font-semibold tracking-tight text-ink">
                Thicket
              </span>
              <span className="block truncate text-xs text-muted">Listen to Nature</span>
            </span>
          </a>
          <div className="flex items-center gap-1 sm:gap-2">
            {nav}
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          </div>
        </div>
      </header>
      {demo ? <DemoBanner /> : null}
      <main
        id="main"
        ref={mainRef}
        tabIndex={-1}
        className="mx-auto w-full max-w-page flex-1 px-4 pt-6 focus:outline-none sm:px-6 sm:pt-8 lg:px-8"
      >
        {children}
      </main>
      <Footer />
    </div>
  );
}

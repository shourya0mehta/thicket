import { routeHref, type Route } from '../../hooks/useHashRoute';
import { cx } from '../../lib/cx';
import type { Theme } from '../../lib/theme';
import { LeafMark } from './LeafMark';
import { ThemeToggle } from './ThemeToggle';

function NavLink({ route, current, children }: { route: Route; current: Route; children: string }) {
  const active = route === current;
  return (
    <a
      href={routeHref(route)}
      aria-current={active ? 'page' : undefined}
      className={cx(
        'rounded-lg px-3 py-2 text-sm font-medium transition-colors',
        active ? 'text-ink' : 'text-muted hover:text-ink',
      )}
    >
      {children}
    </a>
  );
}

export function Header({
  route,
  theme,
  onToggleTheme,
  showHistory,
}: {
  route: Route;
  theme: Theme;
  onToggleTheme: () => void;
  showHistory: boolean;
}) {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex h-16 max-w-page items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <a href={routeHref('workspace')} className="flex min-w-0 items-center gap-2.5 rounded-lg">
          <LeafMark className="h-8 w-8" />
          <span className="min-w-0 leading-tight">
            <span className="block text-[1.0625rem] font-semibold tracking-tight text-ink">
              Thicket
            </span>
            <span className="block truncate text-xs text-muted">Listen to Nature</span>
          </span>
        </a>
        <div className="flex items-center gap-1 sm:gap-2">
          <nav aria-label="Main" className="flex items-center">
            {showHistory ? (
              <NavLink route="history" current={route}>
                History
              </NavLink>
            ) : null}
            <NavLink route="methods" current={route}>
              Methods
            </NavLink>
          </nav>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </div>
    </header>
  );
}

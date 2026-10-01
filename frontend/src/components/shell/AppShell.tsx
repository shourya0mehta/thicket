import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Organization, User } from '../../api/generated';
import { cx } from '../../lib/cx';
import { homeHref, orgHref, type OrgPage } from '../../lib/routes';
import type { Theme } from '../../lib/theme';
import { DemoBanner } from '../layout/DemoBanner';
import { Footer } from '../layout/Footer';
import { LeafMark } from '../layout/LeafMark';
import { ThemeToggle } from '../layout/ThemeToggle';
import {
  AlertIcon,
  BellIcon,
  CogIcon,
  DocumentIcon,
  GridIcon,
  MapPinIcon,
  MenuIcon,
  MicIcon,
  SignOutIcon,
  UploadIcon,
  WaveformIcon,
  XIcon,
  type IconProps,
  ChevronDownIcon,
  FileAudioIcon,
} from '../ui/icons';

export interface NavItem {
  page: OrgPage;
  label: string;
  Icon: (p: IconProps) => JSX.Element;
  badge?: number;
}

const PRIMARY: Array<Omit<NavItem, 'badge'>> = [
  { page: 'dashboard', label: 'Dashboard', Icon: GridIcon },
  { page: 'sites', label: 'Sites', Icon: MapPinIcon },
  { page: 'recordings', label: 'Recordings', Icon: WaveformIcon },
  { page: 'upload', label: 'Upload', Icon: UploadIcon },
  { page: 'analyze', label: 'Analyze one', Icon: FileAudioIcon },
  { page: 'alerts', label: 'Alerts', Icon: AlertIcon },
  { page: 'recorders', label: 'Recorders', Icon: MicIcon },
  { page: 'reports', label: 'Reports', Icon: DocumentIcon },
  { page: 'settings', label: 'Settings', Icon: CogIcon },
];

/** Pages that highlight a parent nav entry. */
const PARENT: Partial<Record<OrgPage, OrgPage>> = {
  site: 'sites',
  recording: 'recordings',
  recorder: 'recorders',
  report_new: 'reports',
};

function isActive(current: OrgPage, item: OrgPage): boolean {
  return current === item || PARENT[current] === item;
}

function useClickOutside(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);
  return ref;
}

function OrgSwitcher({
  org,
  organizations,
  currentPage,
}: {
  org: Organization;
  organizations: Organization[];
  currentPage: OrgPage;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  if (organizations.length <= 1) {
    return (
      <span className="min-w-0 truncate text-sm font-medium text-ink" data-testid="org-name">
        {org.name}
      </span>
    );
  }
  const keepPage: OrgPage = PARENT[currentPage] ?? currentPage;
  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex max-w-[14rem] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-medium text-ink hover:bg-surface-muted"
        data-testid="org-switcher"
      >
        <span className="truncate">{org.name}</span>
        <ChevronDownIcon size={14} className="shrink-0 text-muted" />
      </button>
      {open ? (
        <ul
          role="menu"
          aria-label="Switch organization"
          className="absolute left-0 top-full z-40 mt-1 w-64 overflow-hidden rounded-xl border border-line bg-raised py-1 shadow-lift"
        >
          {organizations.map((o) => (
            <li key={o.id} role="none">
              <a
                role="menuitem"
                href={orgHref(o.id, keepPage === 'dashboard' ? 'dashboard' : keepPage)}
                aria-current={o.id === org.id ? 'true' : undefined}
                onClick={() => setOpen(false)}
                className={cx(
                  'block px-3 py-2 text-sm hover:bg-surface-muted',
                  o.id === org.id ? 'font-semibold text-ink' : 'text-ink',
                )}
              >
                {o.name}
                <span className="block text-xs text-muted">{o.kind.replace(/_/g, ' ')}</span>
              </a>
            </li>
          ))}
          <li role="none" className="border-t border-line">
            <a
              role="menuitem"
              href={homeHref()}
              onClick={() => setOpen(false)}
              className="block px-3 py-2 text-sm text-muted hover:bg-surface-muted"
            >
              All organizations
            </a>
          </li>
        </ul>
      ) : null}
    </div>
  );
}

function UserMenu({
  user,
  onSignOut,
  canSignOut,
}: {
  user: User;
  onSignOut: () => void;
  canSignOut: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  const initials = user.name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.name}`}
        onClick={() => setOpen((v) => !v)}
        className="flex h-9 items-center gap-2 rounded-xl border border-line bg-surface pl-1 pr-2 text-sm hover:border-line-strong"
        data-testid="user-menu"
      >
        {user.picture_url ? (
          <img
            src={user.picture_url}
            alt=""
            width={28}
            height={28}
            className="h-7 w-7 rounded-lg object-cover"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-forest-100 text-xs font-semibold text-forest-800 dark:bg-forest-800 dark:text-forest-100">
            {initials || '?'}
          </span>
        )}
        <span className="hidden max-w-[9rem] truncate text-ink sm:inline">{user.name}</span>
        <ChevronDownIcon size={14} className="text-muted" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-full z-40 mt-1 w-64 overflow-hidden rounded-xl border border-line bg-raised py-1 shadow-lift"
        >
          <div className="border-b border-line px-3 py-2">
            <p className="truncate text-sm font-semibold text-ink">{user.name}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
          </div>
          <a
            role="menuitem"
            href="#/methods"
            onClick={() => setOpen(false)}
            className="block px-3 py-2 text-sm text-ink hover:bg-surface-muted"
          >
            Methods and limits
          </a>
          {canSignOut ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onSignOut();
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-ink hover:bg-surface-muted"
            >
              <SignOutIcon size={15} className="text-muted" /> Sign out
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function AppShell({
  org,
  organizations,
  user,
  page,
  theme,
  onToggleTheme,
  onSignOut,
  canSignOut,
  unread,
  openAlerts,
  demo,
  mainRef,
  children,
}: {
  org: Organization;
  organizations: Organization[];
  user: User;
  page: OrgPage;
  theme: Theme;
  onToggleTheme: () => void;
  onSignOut: () => void;
  canSignOut: boolean;
  unread: number;
  openAlerts?: number;
  demo: boolean;
  mainRef: React.RefObject<HTMLElement>;
  children: ReactNode;
}) {
  const [drawer, setDrawer] = useState(false);
  const drawerRef = useClickOutside(drawer, () => setDrawer(false));
  const items: NavItem[] = PRIMARY.map((item) => ({
    ...item,
    badge: item.page === 'alerts' ? openAlerts : undefined,
  }));
  const mobilePrimary = items.filter((i) =>
    ['dashboard', 'sites', 'recordings', 'alerts'].includes(i.page),
  );
  const mobileMore = items.filter((i) => !mobilePrimary.includes(i));

  useEffect(() => {
    setDrawer(false);
  }, [page]);

  const link = (item: NavItem, variant: 'side' | 'tab' | 'drawer') => {
    const active = isActive(page, item.page);
    const href = orgHref(org.id, item.page);
    if (variant === 'tab') {
      return (
        <a
          key={item.page}
          href={href}
          aria-current={active ? 'page' : undefined}
          className={cx(
            'relative flex flex-1 flex-col items-center gap-0.5 rounded-lg py-1.5 text-[0.6875rem] font-medium',
            active ? 'text-accent' : 'text-muted',
          )}
        >
          <item.Icon size={20} strokeWidth={active ? 2 : 1.75} />
          {item.label}
          {item.badge ? (
            <span className="absolute right-[18%] top-0.5 min-w-[1.1rem] rounded-full bg-danger px-1 text-center text-[0.625rem] font-semibold leading-4 text-white">
              {item.badge > 99 ? '99+' : item.badge}
            </span>
          ) : null}
        </a>
      );
    }
    return (
      <a
        key={item.page}
        href={href}
        aria-current={active ? 'page' : undefined}
        className={cx(
          'flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors',
          active
            ? 'bg-forest-600/10 text-ink dark:bg-white/10'
            : 'text-muted hover:bg-surface-muted hover:text-ink',
        )}
      >
        <item.Icon size={17} className={active ? 'text-accent' : 'text-subtle'} />
        <span className="flex-1">{item.label}</span>
        {item.badge ? (
          <span className="num rounded-full bg-danger-soft px-1.5 text-[0.6875rem] font-semibold text-danger">
            {item.badge}
          </span>
        ) : null}
      </a>
    );
  };

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
      <header className="sticky top-0 z-30 border-b border-line bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[96rem] items-center gap-3 px-4 sm:px-6">
          <a href={homeHref()} className="flex shrink-0 items-center gap-2 rounded-lg">
            <LeafMark className="h-7 w-7" />
            <span className="hidden text-[1rem] font-semibold tracking-tight text-ink sm:inline">
              Thicket
            </span>
          </a>
          <span className="hidden text-muted sm:inline" aria-hidden="true">
            /
          </span>
          <OrgSwitcher org={org} organizations={organizations} currentPage={page} />
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            <a
              href={orgHref(org.id, 'alerts')}
              aria-label={
                unread > 0 ? `${unread} unread notifications, open alerts` : 'Open alerts'
              }
              className="relative inline-flex h-9 w-9 items-center justify-center rounded-xl border border-line bg-surface text-muted hover:border-line-strong hover:text-ink"
              data-testid="notification-bell"
            >
              <BellIcon size={17} />
              {unread > 0 ? (
                <span
                  className="absolute -right-1 -top-1 min-w-[1.1rem] rounded-full bg-danger px-1 text-center text-[0.625rem] font-semibold leading-4 text-white"
                  data-testid="unread-badge"
                >
                  {unread > 99 ? '99+' : unread}
                </span>
              ) : null}
            </a>
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
            <UserMenu user={user} onSignOut={onSignOut} canSignOut={canSignOut} />
          </div>
        </div>
      </header>
      {demo ? <DemoBanner /> : null}

      <div className="mx-auto flex w-full max-w-[96rem] flex-1">
        <nav
          aria-label="Organization"
          className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-56 shrink-0 flex-col gap-0.5 self-start overflow-y-auto border-r border-line px-3 py-5 lg:flex"
        >
          {items.map((item) => link(item, 'side'))}
          <div className="mt-auto border-t border-line pt-3">
            <a
              href="#/methods"
              className="block rounded-xl px-3 py-2 text-sm font-medium text-muted hover:bg-surface-muted hover:text-ink"
            >
              Methods
            </a>
          </div>
        </nav>
        <main
          id="main"
          ref={mainRef}
          tabIndex={-1}
          className="min-w-0 flex-1 px-4 pb-24 pt-6 focus:outline-none sm:px-6 sm:pt-8 lg:px-8 lg:pb-10"
        >
          {children}
        </main>
      </div>

      <nav
        aria-label="Organization"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-canvas/95 backdrop-blur lg:hidden"
      >
        <div className="mx-auto flex max-w-xl items-stretch px-2 pb-[max(0.25rem,env(safe-area-inset-bottom))] pt-1">
          {mobilePrimary.map((item) => link(item, 'tab'))}
          <div ref={drawerRef} className="relative flex flex-1">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={drawer}
              onClick={() => setDrawer((v) => !v)}
              className={cx(
                'flex flex-1 flex-col items-center gap-0.5 rounded-lg py-1.5 text-[0.6875rem] font-medium',
                mobileMore.some((i) => isActive(page, i.page)) ? 'text-accent' : 'text-muted',
              )}
            >
              {drawer ? <XIcon size={20} /> : <MenuIcon size={20} />}
              More
            </button>
            {drawer ? (
              <div
                role="menu"
                aria-label="More pages"
                className="absolute bottom-full right-0 mb-2 w-56 overflow-hidden rounded-xl border border-line bg-raised py-1 shadow-lift"
              >
                {mobileMore.map((item) => (
                  <a
                    key={item.page}
                    role="menuitem"
                    href={orgHref(org.id, item.page)}
                    aria-current={isActive(page, item.page) ? 'page' : undefined}
                    className="flex items-center gap-2.5 px-3 py-2 text-sm text-ink hover:bg-surface-muted"
                  >
                    <item.Icon size={16} className="text-subtle" />
                    {item.label}
                  </a>
                ))}
                <a
                  role="menuitem"
                  href="#/methods"
                  className="flex items-center gap-2.5 border-t border-line px-3 py-2 text-sm text-muted hover:bg-surface-muted"
                >
                  Methods
                </a>
              </div>
            ) : null}
          </div>
        </div>
      </nav>
      <div className="pb-16 lg:pb-0">
        <Footer />
      </div>
    </div>
  );
}

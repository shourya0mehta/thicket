/**
 * Hash routes. Deep links keep working on static hosting because everything
 * lives after `#/`. Query parameters after the path are parsed into `query`.
 *
 *   #/                              home: sign-in, org picker or the standalone workspace
 *   #/history  #/methods            standalone pages (history only without auth)
 *   #/invite/:token                 accept an invitation
 *   #/orgs/:org                     dashboard
 *   #/orgs/:org/<page>[/:id]        the org pages below
 */

export type OrgPage =
  | 'dashboard'
  | 'sites'
  | 'site'
  | 'recordings'
  | 'recording'
  | 'upload'
  | 'analyze'
  | 'alerts'
  | 'recorders'
  | 'recorder'
  | 'reports'
  | 'report_new'
  | 'settings';

export type AppRoute =
  | { name: 'home' }
  | { name: 'history' }
  | { name: 'methods' }
  | { name: 'invite'; token: string }
  | { name: 'org'; org: string; page: OrgPage; id: string | null }
  | { name: 'not_found'; path: string };

export interface ParsedRoute {
  route: AppRoute;
  query: URLSearchParams;
}

const SIMPLE_PAGES: Record<string, OrgPage> = {
  sites: 'sites',
  recordings: 'recordings',
  upload: 'upload',
  analyze: 'analyze',
  alerts: 'alerts',
  recorders: 'recorders',
  reports: 'reports',
  settings: 'settings',
};

const DETAIL_PAGES: Partial<Record<OrgPage, OrgPage>> = {
  sites: 'site',
  recordings: 'recording',
  recorders: 'recorder',
};

export function parseAppRoute(hash: string): ParsedRoute {
  const raw = hash.replace(/^#/, '');
  const queryIndex = raw.indexOf('?');
  const pathPart = queryIndex >= 0 ? raw.slice(0, queryIndex) : raw;
  const query = new URLSearchParams(queryIndex >= 0 ? raw.slice(queryIndex + 1) : '');
  const segments = pathPart
    .split('/')
    .filter(Boolean)
    .map((s) => {
      try {
        return decodeURIComponent(s);
      } catch {
        return s;
      }
    });

  const [first, second, third, fourth] = segments;
  if (!first) return { route: { name: 'home' }, query };
  if (first === 'history' && !second) return { route: { name: 'history' }, query };
  if (first === 'methods' && !second) return { route: { name: 'methods' }, query };
  if (first === 'invite' && second && !third) {
    return { route: { name: 'invite', token: second }, query };
  }
  if (first === 'orgs' && second) {
    const org = second;
    if (!third) return { route: { name: 'org', org, page: 'dashboard', id: null }, query };
    if (third === 'reports' && fourth === 'new') {
      return { route: { name: 'org', org, page: 'report_new', id: null }, query };
    }
    const page = SIMPLE_PAGES[third];
    if (page && !fourth) return { route: { name: 'org', org, page, id: null }, query };
    const detail = page ? DETAIL_PAGES[page] : undefined;
    if (detail && fourth) return { route: { name: 'org', org, page: detail, id: fourth }, query };
  }
  return { route: { name: 'not_found', path: pathPart }, query };
}

const PAGE_SEGMENT: Record<OrgPage, string> = {
  dashboard: '',
  sites: 'sites',
  site: 'sites',
  recordings: 'recordings',
  recording: 'recordings',
  upload: 'upload',
  analyze: 'analyze',
  alerts: 'alerts',
  recorders: 'recorders',
  recorder: 'recorders',
  reports: 'reports',
  report_new: 'reports/new',
  settings: 'settings',
};

export function orgHref(
  org: string,
  page: OrgPage = 'dashboard',
  id?: string | null,
  query?: Record<string, string | null | undefined>,
): string {
  const segment = PAGE_SEGMENT[page];
  let href = `#/orgs/${encodeURIComponent(org)}`;
  if (segment) href += `/${segment}`;
  if (id) href += `/${encodeURIComponent(id)}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value != null && value !== '') params.set(key, value);
    }
    const text = params.toString();
    if (text) href += `?${text}`;
  }
  return href;
}

export function homeHref(): string {
  return '#/';
}

export function inviteHref(token: string): string {
  return `#/invite/${encodeURIComponent(token)}`;
}

/** Changes the hash (which fires hashchange) without adding duplicate entries. */
export function navigateTo(href: string): void {
  if (window.location.hash !== href) window.location.hash = href;
}

/** Replaces the current hash entry (used for redirects such as home to dashboard). */
export function replaceHash(href: string): void {
  if (window.location.hash === href) return;
  const url = `${window.location.pathname}${window.location.search}${href}`;
  try {
    window.history.replaceState(window.history.state, '', url);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } catch {
    window.location.hash = href;
  }
}

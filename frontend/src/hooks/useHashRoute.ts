import { useEffect, useState } from 'react';

export type Route = 'workspace' | 'history' | 'methods';

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#\/?/, '').split(/[?/]/)[0] ?? '';
  if (path === 'history') return 'history';
  if (path === 'methods') return 'methods';
  return 'workspace';
}

export function routeHref(route: Route): string {
  return route === 'workspace' ? '#/' : `#/${route}`;
}

/** Hash routing keeps deep links working on static hosts such as GitHub Pages. */
export function useHashRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  const navigate = (next: Route) => {
    const href = routeHref(next);
    if (window.location.hash !== href) window.location.hash = href;
    setRoute(next);
  };

  return [route, navigate];
}

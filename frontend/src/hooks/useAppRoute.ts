import { useEffect, useState } from 'react';
import { parseAppRoute, type ParsedRoute } from '../lib/routes';

/** The full hash route (path plus query), updated on every hashchange. */
export function useAppRoute(): ParsedRoute {
  const [parsed, setParsed] = useState<ParsedRoute>(() => parseAppRoute(window.location.hash));

  useEffect(() => {
    const onChange = () => setParsed(parseAppRoute(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  return parsed;
}

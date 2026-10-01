import { useCallback, useEffect, useMemo, type ReactNode } from 'react';
import type { Organization } from '../api/generated';
import { NOTIFICATION_POLL_INTERVAL_MS } from '../config';
import { useResource } from '../hooks/useResource';
import { permissionsFor } from '../lib/roles';
import { OrgContext, type OrgContextValue } from './orgContext';
import { usePlatform } from './platformContext';

/**
 * Caches the organization, its sites and recorders for every page under
 * #/orgs/:org. Pages that change them call `sites.reload()` or `setData`.
 */
export function OrgProvider({ org, children }: { org: Organization; children: ReactNode }) {
  const { api, me, demo } = usePlatform();
  const role = me?.roles[org.id] ?? null;
  const permissions = useMemo(() => permissionsFor(role), [role]);

  const sites = useResource((signal) => api.listSites(org.id, signal), `sites:${org.id}`);
  const recorders = useResource(
    (signal) => api.listRecorders(org.id, signal),
    `recorders:${org.id}`,
  );
  const notifications = useResource(
    (signal) => api.getNotifications(true, signal),
    `unread:${org.id}`,
    !demo,
  );

  useEffect(() => {
    if (demo) return;
    const timer = window.setInterval(notifications.reload, NOTIFICATION_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [demo, notifications.reload]);

  const siteName = useCallback(
    (id: string | null | undefined) =>
      (id && sites.data?.find((s) => s.id === id)?.name) || (id ? 'Unknown site' : 'No site'),
    [sites.data],
  );
  const recorderLabel = useCallback(
    (id: string | null | undefined) =>
      (id && recorders.data?.find((r) => r.id === id)?.label) ||
      (id ? 'Unknown recorder' : 'No recorder'),
    [recorders.data],
  );

  const value = useMemo<OrgContextValue>(
    () => ({
      org,
      permissions,
      sites,
      recorders,
      unread: notifications.data?.unread ?? me?.unread_notifications ?? 0,
      refreshUnread: notifications.reload,
      siteName,
      recorderLabel,
    }),
    [org, permissions, sites, recorders, notifications, me, siteName, recorderLabel],
  );

  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>;
}

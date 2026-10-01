import { createContext, useContext } from 'react';
import type { Organization, Recorder, Site } from '../api/generated';
import type { Resource } from '../hooks/useResource';
import type { Permissions } from '../lib/roles';

export interface OrgContextValue {
  org: Organization;
  permissions: Permissions;
  sites: Resource<Site[]>;
  recorders: Resource<Recorder[]>;
  /** Unread in-app notifications for the badge. */
  unread: number;
  refreshUnread: () => void;
  siteName: (id: string | null | undefined) => string;
  recorderLabel: (id: string | null | undefined) => string;
}

export const OrgContext = createContext<OrgContextValue | null>(null);

export function useOrg(): OrgContextValue {
  const value = useContext(OrgContext);
  if (!value) throw new Error('useOrg must be used inside OrgProvider');
  return value;
}

import { createContext, useContext } from 'react';
import type { FriendlyError } from '../api/errors';
import type { AuthConfig, Me, Organization } from '../api/generated';
import { PLATFORM_HINT_KEY } from '../config';
import { readStorage } from '../lib/storage';
import type { PlatformApi } from './api';

/**
 * Which app this deployment is:
 *   probing     the first request has not answered yet
 *   standalone  no platform routes on the server (older backend) or no demo file:
 *               the single-recording workspace, history and methods
 *   platform    organizations, sign-in and the dashboards
 */
export type PlatformPhase = 'probing' | 'standalone' | 'platform';

export type SessionStatus = 'idle' | 'loading' | 'signed_out' | 'signed_in' | 'error';

export interface PlatformState {
  phase: PlatformPhase;
  demo: boolean;
  config: AuthConfig | null;
  session: SessionStatus;
  me: Me | null;
  error: FriendlyError | null;
}

export interface PlatformContextValue extends PlatformState {
  api: PlatformApi;
  /** Sign in with the development email form (AUTH_MODE=dev). */
  signInDev: (email: string, name?: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Re-fetch /auth/me (after creating an organization or accepting an invite). */
  refreshMe: () => Promise<Me | null>;
  /** Merge a new or updated organization into the cached session. */
  rememberOrganization: (org: Organization, role?: Me['roles'][string]) => void;
  retry: () => void;
  lastOrgId: string | null;
  setLastOrgId: (id: string) => void;
}

export const PlatformContext = createContext<PlatformContextValue | null>(null);

export function readHint(): boolean {
  return readStorage(PLATFORM_HINT_KEY) === '1';
}

export function usePlatform(): PlatformContextValue {
  const value = useContext(PlatformContext);
  if (!value) throw new Error('usePlatform must be used inside PlatformProvider');
  return value;
}

/** True while the first visit's probe is still out: render the standalone app meanwhile. */
export function shouldRenderStandaloneWhileProbing(): boolean {
  return !readHint();
}

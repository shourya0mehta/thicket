import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError, setUnauthenticatedHandler } from '../api/client';
import { describeError } from '../api/errors';
import type { AuthConfig, Me, Organization } from '../api/generated';
import * as authApi from '../api/platform';
import { isDemoMode, LAST_ORG_KEY, PLATFORM_HINT_KEY } from '../config';
import { demoMe, demoPlatformApi, loadPlatformDemo } from '../lib/platformDemo';
import { readStorage, writeStorage } from '../lib/storage';
import { httpPlatformApi, type PlatformApi } from './api';
import {
  PlatformContext,
  readHint,
  type PlatformContextValue,
  type PlatformState,
} from './platformContext';

export function PlatformProvider({ children }: { children: ReactNode }) {
  const demo = isDemoMode();
  const [state, setState] = useState<PlatformState>(() => ({
    // A browser that saw the platform before waits for the probe instead of
    // flashing the standalone workspace; a first visit renders it right away.
    phase: 'probing',
    demo,
    config: null,
    session: 'idle',
    me: null,
    error: null,
  }));
  const [api, setApi] = useState<PlatformApi>(httpPlatformApi);
  const [attempt, setAttempt] = useState(0);
  const [lastOrgId, setLastOrg] = useState<string | null>(() => readStorage(LAST_ORG_KEY));
  const hinted = useRef(readHint());

  useEffect(() => {
    const ctrl = new AbortController();
    const run = async () => {
      if (demo) {
        const file = await loadPlatformDemo(ctrl.signal).catch(() => null);
        if (ctrl.signal.aborted) return;
        if (!file) {
          setState((s) => ({ ...s, phase: 'standalone' }));
          return;
        }
        setApi(demoPlatformApi(file));
        setState({
          phase: 'platform',
          demo: true,
          config: { mode: 'disabled' },
          session: 'signed_in',
          me: demoMe(file),
          error: null,
        });
        return;
      }

      let config: AuthConfig;
      try {
        config = await authApi.getAuthConfig(ctrl.signal);
      } catch (error) {
        if (ctrl.signal.aborted) return;
        const notFound =
          error instanceof ApiError && (error.status === 404 || error.status === 405);
        if (notFound || !hinted.current) {
          // An older backend without platform routes, or an unreachable server
          // on a first visit: the standalone workspace explains the rest.
          if (notFound) writeStorage(PLATFORM_HINT_KEY, '0');
          setState((s) => ({ ...s, phase: 'standalone' }));
          return;
        }
        setState((s) => ({
          ...s,
          phase: 'platform',
          session: 'error',
          error: describeError(error),
        }));
        return;
      }
      if (ctrl.signal.aborted) return;
      if (!config || typeof config.mode !== 'string') {
        setState((s) => ({ ...s, phase: 'standalone' }));
        return;
      }
      writeStorage(PLATFORM_HINT_KEY, '1');
      hinted.current = true;
      setState((s) => ({ ...s, phase: 'platform', config, session: 'loading', error: null }));

      try {
        const me = await authApi.getMe(ctrl.signal);
        if (ctrl.signal.aborted) return;
        setState((s) => ({ ...s, session: 'signed_in', me, error: null }));
      } catch (error) {
        if (ctrl.signal.aborted) return;
        if (error instanceof ApiError && error.code === 'unauthenticated') {
          setState((s) => ({ ...s, session: 'signed_out', me: null, error: null }));
          return;
        }
        setState((s) => ({ ...s, session: 'error', error: describeError(error) }));
      }
    };
    void run();
    return () => ctrl.abort();
  }, [demo, attempt]);

  // Any 401 from any request means the session ended: show sign-in.
  useEffect(() => {
    if (demo) return;
    setUnauthenticatedHandler(() => {
      setState((s) =>
        s.phase === 'platform' && s.session !== 'signed_out'
          ? { ...s, session: 'signed_out', me: null }
          : s,
      );
    });
    return () => setUnauthenticatedHandler(null);
  }, [demo]);

  const refreshMe = useCallback(async (): Promise<Me | null> => {
    try {
      const me = await api.getMe();
      setState((s) => ({ ...s, session: 'signed_in', me, error: null }));
      return me;
    } catch (error) {
      if (error instanceof ApiError && error.code === 'unauthenticated') {
        setState((s) => ({ ...s, session: 'signed_out', me: null }));
        return null;
      }
      setState((s) => ({ ...s, error: describeError(error) }));
      return null;
    }
  }, [api]);

  const signInDev = useCallback(async (email: string, name?: string) => {
    const me = await authApi.devLogin({ email, name: name?.trim() || null });
    setState((s) => ({ ...s, session: 'signed_in', me, error: null }));
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // The cookie may already be gone; the UI state is what matters here.
    }
    setState((s) => ({ ...s, session: 'signed_out', me: null }));
  }, []);

  const rememberOrganization = useCallback((org: Organization, role?: Me['roles'][string]) => {
    setState((s) => {
      if (!s.me) return s;
      const others = s.me.organizations.filter((o) => o.id !== org.id);
      return {
        ...s,
        me: {
          ...s.me,
          organizations: [...others, org],
          roles: { ...s.me.roles, [org.id]: role ?? s.me.roles[org.id] ?? 'owner' },
        },
      };
    });
  }, []);

  const setLastOrgId = useCallback((id: string) => {
    setLastOrg(id);
    writeStorage(LAST_ORG_KEY, id);
  }, []);

  const value = useMemo<PlatformContextValue>(
    () => ({
      ...state,
      api,
      signInDev,
      signOut,
      refreshMe,
      rememberOrganization,
      retry: () => setAttempt((n) => n + 1),
      lastOrgId,
      setLastOrgId,
    }),
    [state, api, signInDev, signOut, refreshMe, rememberOrganization, lastOrgId, setLastOrgId],
  );

  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

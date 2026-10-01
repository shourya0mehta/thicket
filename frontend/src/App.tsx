import { useEffect, useRef, useState } from 'react';
import type { Organization, OrganizationCreate } from './api/generated';
import { DemoBanner } from './components/layout/DemoBanner';
import { Footer } from './components/layout/Footer';
import { Header } from './components/layout/Header';
import { EmptyState, ErrorState, LoadingState } from './components/platform/primitives';
import { AppShell } from './components/shell/AppShell';
import { PlainLayout } from './components/shell/PlainLayout';
import { ButtonLink } from './components/ui/Button';
import { Spinner } from './components/ui/Spinner';
import { isDemoMode } from './config';
import { useAppRoute } from './hooks/useAppRoute';
import { parseRoute as parseLegacyRoute } from './hooks/useHashRoute';
import { useTheme } from './hooks/useTheme';
import { homeHref, orgHref, replaceHash, type AppRoute } from './lib/routes';
import type { Theme } from './lib/theme';
import { HistoryPage } from './pages/HistoryPage';
import { MethodsPage } from './pages/MethodsPage';
import { AlertsPage } from './pages/platform/AlertsPage';
import { AnalyzePage } from './pages/platform/AnalyzePage';
import { DashboardPage } from './pages/platform/DashboardPage';
import { InvitePage } from './pages/platform/InvitePage';
import { OrgPickerPage } from './pages/platform/OrgPickerPage';
import { RecorderPage } from './pages/platform/RecorderPage';
import { RecordersPage } from './pages/platform/RecordersPage';
import { RecordingPage } from './pages/platform/RecordingPage';
import { RecordingsPage } from './pages/platform/RecordingsPage';
import { ReportsPage } from './pages/platform/ReportsPage';
import { ReportWizardPage } from './pages/platform/ReportWizardPage';
import { SettingsPage } from './pages/platform/SettingsPage';
import { SignInPage } from './pages/platform/SignInPage';
import { SitePage } from './pages/platform/SitePage';
import { SitesPage } from './pages/platform/SitesPage';
import { UploadPage } from './pages/platform/UploadPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { OrgProvider } from './platform/OrgProvider';
import { useOrg } from './platform/orgContext';
import { PlatformProvider } from './platform/PlatformProvider';
import { shouldRenderStandaloneWhileProbing, usePlatform } from './platform/platformContext';
import { useWorkspace, type Workspace } from './state/useWorkspace';

export default function App() {
  return (
    <PlatformProvider>
      <AppRouter />
    </PlatformProvider>
  );
}

/** Moves focus to the page and scrolls up whenever the hash route changes. */
function useRouteFocus(mainRef: React.RefObject<HTMLElement>, key: string) {
  const previous = useRef(key);
  useEffect(() => {
    if (previous.current === key) return;
    previous.current = key;
    mainRef.current?.focus();
    window.scrollTo({ top: 0 });
  }, [key, mainRef]);
}

function AppRouter() {
  const platform = usePlatform();
  const { theme, toggle } = useTheme();
  const { route, query } = useAppRoute();
  const workspace = useWorkspace();
  const demo = isDemoMode();
  const mainRef = useRef<HTMLElement>(null);
  const [standaloneWhileProbing] = useState(shouldRenderStandaloneWhileProbing);
  useRouteFocus(mainRef, window.location.hash);

  const standalone =
    platform.phase === 'standalone' || (platform.phase === 'probing' && standaloneWhileProbing);

  if (standalone) {
    return (
      <StandaloneApp
        theme={theme}
        onToggleTheme={toggle}
        workspace={workspace}
        demo={demo}
        mainRef={mainRef}
      />
    );
  }

  if (
    platform.phase === 'probing' ||
    platform.session === 'loading' ||
    platform.session === 'idle'
  ) {
    return <BootScreen theme={theme} onToggleTheme={toggle} mainRef={mainRef} demo={demo} />;
  }

  if (platform.session === 'error' && platform.error) {
    return (
      <PlainLayout theme={theme} onToggleTheme={toggle} mainRef={mainRef} demo={demo}>
        <div className="mx-auto max-w-xl py-10">
          <ErrorState error={platform.error} onRetry={platform.retry} />
        </div>
      </PlainLayout>
    );
  }

  if (route.name === 'methods') {
    return (
      <PlainLayout
        theme={theme}
        onToggleTheme={toggle}
        mainRef={mainRef}
        demo={demo}
        nav={<BackNav />}
      >
        <MethodsPage />
      </PlainLayout>
    );
  }

  if (platform.session === 'signed_out' || !platform.me || !platform.config) {
    return (
      <PlainLayout theme={theme} onToggleTheme={toggle} mainRef={mainRef} demo={demo}>
        {platform.config ? (
          <SignInPage
            config={platform.config}
            onDevSignIn={platform.signInDev}
            nextHash={
              window.location.hash && window.location.hash !== '#/'
                ? window.location.hash
                : undefined
            }
          />
        ) : (
          <LoadingState />
        )}
      </PlainLayout>
    );
  }

  return (
    <SignedInRoutes
      route={route}
      query={query}
      theme={theme}
      onToggleTheme={toggle}
      workspace={workspace}
      demo={demo}
      mainRef={mainRef}
    />
  );
}

function BackNav() {
  return (
    <nav aria-label="Main" className="flex items-center">
      <a
        href={homeHref()}
        className="rounded-lg px-3 py-2 text-sm font-medium text-muted hover:text-ink"
      >
        Back to Thicket
      </a>
    </nav>
  );
}

function BootScreen({
  theme,
  onToggleTheme,
  mainRef,
  demo,
}: {
  theme: Theme;
  onToggleTheme: () => void;
  mainRef: React.RefObject<HTMLElement>;
  demo: boolean;
}) {
  return (
    <PlainLayout theme={theme} onToggleTheme={onToggleTheme} mainRef={mainRef} demo={demo}>
      <p className="flex items-center gap-2 py-16 text-sm text-muted" role="status">
        <Spinner size={14} /> Connecting to Thicket...
      </p>
    </PlainLayout>
  );
}

/** The single-recording app for a backend without platform routes. */
function StandaloneApp({
  theme,
  onToggleTheme,
  workspace,
  demo,
  mainRef,
}: {
  theme: Theme;
  onToggleTheme: () => void;
  workspace: Workspace;
  demo: boolean;
  mainRef: React.RefObject<HTMLElement>;
}) {
  const [route, setRoute] = useState(() => parseLegacyRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseLegacyRoute(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  const effectiveRoute = demo && route === 'history' ? 'workspace' : route;

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
      <Header
        route={effectiveRoute}
        theme={theme}
        onToggleTheme={onToggleTheme}
        showHistory={!demo}
      />
      {demo ? <DemoBanner /> : null}
      <main
        id="main"
        ref={mainRef}
        tabIndex={-1}
        className="mx-auto w-full max-w-page flex-1 px-4 pt-8 focus:outline-none sm:px-6 sm:pt-10 lg:px-8"
      >
        {effectiveRoute === 'history' ? (
          <HistoryPage
            entries={workspace.state.history}
            onOpen={(id) => {
              window.location.hash = '#/';
              void workspace.loadAnalysis(id);
            }}
            onHistoryChanged={workspace.refreshHistory}
          />
        ) : effectiveRoute === 'methods' ? (
          <MethodsPage />
        ) : (
          <WorkspacePage workspace={workspace} />
        )}
      </main>
      <Footer />
    </div>
  );
}

function findOrg(organizations: Organization[], key: string): Organization | null {
  return (
    organizations.find((o) => o.id === key) ?? organizations.find((o) => o.slug === key) ?? null
  );
}

function SignedInRoutes({
  route,
  query,
  theme,
  onToggleTheme,
  workspace,
  demo,
  mainRef,
}: {
  route: AppRoute;
  query: URLSearchParams;
  theme: Theme;
  onToggleTheme: () => void;
  workspace: Workspace;
  demo: boolean;
  mainRef: React.RefObject<HTMLElement>;
}) {
  const platform = usePlatform();
  const me = platform.me!;
  const config = platform.config!;
  const organizations = me.organizations;

  // Home: one organization opens straight away; several go to the last one used.
  useEffect(() => {
    if (route.name !== 'home') return;
    if (organizations.length === 1) replaceHash(orgHref(organizations[0]!.id));
    else if (organizations.length > 1 && platform.lastOrgId) {
      const last = findOrg(organizations, platform.lastOrgId);
      if (last) replaceHash(orgHref(last.id));
    }
  }, [route, organizations, platform.lastOrgId]);

  const createOrg = async (body: OrganizationCreate) => {
    const org = await platform.api.createOrganization(body);
    platform.rememberOrganization(org, 'owner');
    platform.setLastOrgId(org.id);
    window.location.hash = orgHref(org.id);
  };

  if (route.name === 'invite') {
    return (
      <PlainLayout theme={theme} onToggleTheme={onToggleTheme} mainRef={mainRef} demo={demo}>
        <InvitePage
          token={route.token}
          onAccept={async (token) => {
            const org = await platform.api.acceptInvite(token);
            platform.rememberOrganization(org);
            await platform.refreshMe();
            return org;
          }}
        />
      </PlainLayout>
    );
  }

  if (route.name === 'history') {
    if (config.mode !== 'disabled') {
      replaceHash(homeHref());
      return null;
    }
    return (
      <PlainLayout
        theme={theme}
        onToggleTheme={onToggleTheme}
        mainRef={mainRef}
        demo={demo}
        nav={<BackNav />}
      >
        <HistoryPage
          entries={workspace.state.history}
          onOpen={(id) => {
            const org = organizations[0];
            window.location.hash = org ? orgHref(org.id, 'analyze') : '#/';
            void workspace.loadAnalysis(id);
          }}
          onHistoryChanged={workspace.refreshHistory}
        />
      </PlainLayout>
    );
  }

  if (route.name === 'home') {
    const redirecting =
      organizations.length === 1 ||
      (organizations.length > 1 &&
        platform.lastOrgId &&
        findOrg(organizations, platform.lastOrgId));
    return (
      <PlainLayout theme={theme} onToggleTheme={onToggleTheme} mainRef={mainRef} demo={demo}>
        {redirecting ? (
          <LoadingState label="Opening your dashboard..." />
        ) : (
          <OrgPickerPage organizations={organizations} roles={me.roles} onCreate={createOrg} />
        )}
      </PlainLayout>
    );
  }

  if (route.name === 'not_found') {
    return (
      <PlainLayout theme={theme} onToggleTheme={onToggleTheme} mainRef={mainRef} demo={demo}>
        <div className="mx-auto max-w-xl py-10">
          <EmptyState
            title="There is nothing at this address"
            action={
              <ButtonLink href={homeHref()} variant="primary" size="sm">
                Go to your organizations
              </ButtonLink>
            }
          >
            The link may be old or mistyped: {route.path}
          </EmptyState>
        </div>
      </PlainLayout>
    );
  }

  if (route.name !== 'org') return null;
  const org = findOrg(organizations, route.org);
  if (!org) {
    return (
      <PlainLayout theme={theme} onToggleTheme={onToggleTheme} mainRef={mainRef} demo={demo}>
        <div className="mx-auto max-w-xl py-10">
          <EmptyState
            title="You are not a member of this organization"
            action={
              <ButtonLink href={homeHref()} variant="primary" size="sm">
                Your organizations
              </ButtonLink>
            }
            testId="org-forbidden"
          >
            Ask an owner for an invitation, or check that the link is right. If you were just added,
            sign out and back in.
          </EmptyState>
        </div>
      </PlainLayout>
    );
  }

  return (
    <OrgProvider key={org.id} org={org}>
      <OrgShell
        route={route}
        query={query}
        theme={theme}
        onToggleTheme={onToggleTheme}
        workspace={workspace}
        demo={demo}
        mainRef={mainRef}
        canSignOut={config.mode !== 'disabled' && !demo}
      />
    </OrgProvider>
  );
}

function OrgShell({
  route,
  query,
  theme,
  onToggleTheme,
  workspace,
  demo,
  mainRef,
  canSignOut,
}: {
  route: Extract<AppRoute, { name: 'org' }>;
  query: URLSearchParams;
  theme: Theme;
  onToggleTheme: () => void;
  workspace: Workspace;
  demo: boolean;
  mainRef: React.RefObject<HTMLElement>;
  canSignOut: boolean;
}) {
  const platform = usePlatform();
  const { org, unread, sites } = useOrg();
  const me = platform.me!;
  const openAlerts = sites.data?.reduce((acc, s) => acc + (s.stats.open_alerts ?? 0), 0);

  useEffect(() => {
    platform.setLastOrgId(org.id);
  }, [org.id, platform]);

  let page: React.ReactNode;
  switch (route.page) {
    case 'dashboard':
      page = <DashboardPage query={query} />;
      break;
    case 'sites':
      page = <SitesPage query={query} />;
      break;
    case 'site':
      page = <SitePage siteId={route.id!} query={query} />;
      break;
    case 'recordings':
      page = <RecordingsPage query={query} />;
      break;
    case 'recording':
      page = <RecordingPage recordingId={route.id!} workspace={workspace} />;
      break;
    case 'upload':
      page = <UploadPage query={query} />;
      break;
    case 'analyze':
      page = <AnalyzePage workspace={workspace} query={query} />;
      break;
    case 'alerts':
      page = <AlertsPage query={query} />;
      break;
    case 'recorders':
      page = <RecordersPage />;
      break;
    case 'recorder':
      page = <RecorderPage recorderId={route.id!} query={query} />;
      break;
    case 'reports':
      page = <ReportsPage />;
      break;
    case 'report_new':
      page = <ReportWizardPage />;
      break;
    case 'settings':
      page = <SettingsPage />;
      break;
    default:
      page = <DashboardPage query={query} />;
  }

  return (
    <AppShell
      org={org}
      organizations={me.organizations}
      user={me.user}
      page={route.page}
      theme={theme}
      onToggleTheme={onToggleTheme}
      onSignOut={() => void platform.signOut()}
      canSignOut={canSignOut}
      unread={unread}
      openAlerts={openAlerts && openAlerts > 0 ? openAlerts : undefined}
      demo={demo}
      mainRef={mainRef}
    >
      {page}
    </AppShell>
  );
}

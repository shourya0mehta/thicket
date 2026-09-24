import { useEffect, useRef } from 'react';
import { DemoBanner } from './components/layout/DemoBanner';
import { Footer } from './components/layout/Footer';
import { Header } from './components/layout/Header';
import { isDemoMode } from './config';
import { useHashRoute } from './hooks/useHashRoute';
import { useTheme } from './hooks/useTheme';
import { HistoryPage } from './pages/HistoryPage';
import { MethodsPage } from './pages/MethodsPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { useWorkspace } from './state/useWorkspace';

export default function App() {
  const { theme, toggle } = useTheme();
  const [route, navigate] = useHashRoute();
  const workspace = useWorkspace();
  const demo = isDemoMode();
  const mainRef = useRef<HTMLElement>(null);
  const previousRoute = useRef(route);

  // Move focus to the new page on navigation so screen readers announce it.
  useEffect(() => {
    if (previousRoute.current === route) return;
    previousRoute.current = route;
    mainRef.current?.focus();
    window.scrollTo({ top: 0 });
  }, [route]);

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
      <Header route={effectiveRoute} theme={theme} onToggleTheme={toggle} showHistory={!demo} />
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
              navigate('workspace');
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

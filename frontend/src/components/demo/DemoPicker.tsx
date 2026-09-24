import { useEffect, useRef, useState } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import { cx } from '../../lib/cx';
import { loadDemoIndex, type DemoEntry } from '../../lib/demo';
import { ErrorCallout } from '../feedback/ErrorCallout';
import { Panel } from '../ui/Panel';
import { Spinner } from '../ui/Spinner';

export function DemoPicker({
  activeId,
  onOpen,
}: {
  activeId: string | null;
  onOpen: (id: string) => void;
}) {
  const [entries, setEntries] = useState<DemoEntry[] | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const openedFirst = useRef(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    loadDemoIndex(ctrl.signal)
      .then((list) => {
        setEntries(list);
        const first = list[0];
        if (first && !openedFirst.current) {
          openedFirst.current = true;
          onOpen(first.id);
        }
      })
      .catch((err: unknown) => {
        const friendly = describeError(err);
        if (friendly) setError(friendly);
      });
    return () => ctrl.abort();
    // onOpen is stable (from useWorkspace); re-run only on explicit retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  const active = entries?.find((e) => e.id === activeId);

  return (
    <Panel labelledBy="demo-heading" className="p-5 sm:p-6">
      <p className="eyebrow mb-1">Demo recordings</p>
      <h2 id="demo-heading" className="text-base font-semibold tracking-tight text-ink">
        Choose a precomputed analysis
      </h2>
      {error ? (
        <ErrorCallout
          className="mt-4"
          error={{ ...error, title: 'The demo data could not be loaded', action: 'retry' }}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      ) : entries === null ? (
        <p className="mt-4 flex items-center gap-2 text-sm text-muted">
          <Spinner size={14} /> Loading demo recordings...
        </p>
      ) : entries.length === 0 ? (
        <p className="mt-4 text-sm text-muted">No demo analyses are published yet.</p>
      ) : (
        <>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map((entry) => {
              const selected = entry.id === activeId;
              return (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(entry.id)}
                    aria-pressed={selected}
                    className={cx(
                      'h-full w-full rounded-xl border px-4 py-3 text-left transition-colors',
                      selected
                        ? 'border-mark bg-mark/[0.07] ring-1 ring-mark/40'
                        : 'border-line-strong bg-raised hover:border-mark/50',
                    )}
                  >
                    <span className="block text-sm font-semibold text-ink">{entry.title}</span>
                    {entry.description ? (
                      <span className="mt-1 block text-xs leading-relaxed text-muted">
                        {entry.description}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
          {active && (active.attribution || active.license) ? (
            <p className="mt-3 text-xs text-muted" data-testid="demo-attribution">
              Recording: {active.attribution}
              {active.license ? ` · License: ${active.license}` : ''}
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

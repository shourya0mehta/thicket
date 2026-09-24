import { useCallback, useEffect, useState } from 'react';
import { deleteAnalysis, listAnalyses } from '../api/client';
import { describeError, type FriendlyError } from '../api/errors';
import type { AnalysisSummary } from '../api/types';
import { ErrorCallout } from '../components/feedback/ErrorCallout';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ArrowRightIcon, ShieldIcon, TrashIcon } from '../components/ui/icons';
import { Panel } from '../components/ui/Panel';
import { Spinner } from '../components/ui/Spinner';
import { formatDateTime, formatDuration, pluralize } from '../lib/format';
import { removeFromHistory, type HistoryEntry } from '../lib/history';
import { thresholdPercent } from '../lib/threshold';

function LocalHistory({
  entries,
  onOpen,
}: {
  entries: HistoryEntry[];
  onOpen: (id: string) => void;
}) {
  if (entries.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-sm text-muted">
        No analyses yet. Completed analyses appear here, up to the last three.
      </p>
    );
  }
  return (
    <ul className="grid gap-3 md:grid-cols-3" data-testid="local-history">
      {entries.map((entry) => (
        <li key={entry.id}>
          <button
            type="button"
            onClick={() => onOpen(entry.id)}
            className="group flex h-full w-full flex-col rounded-2xl border border-line-strong bg-raised p-4 text-left transition-colors hover:border-mark/60"
          >
            <span
              className="block truncate text-sm font-semibold text-ink"
              title={entry.filename ?? undefined}
            >
              {entry.site || entry.filename || 'Untitled recording'}
            </span>
            {entry.site && entry.filename ? (
              <span className="block truncate text-xs text-muted">{entry.filename}</span>
            ) : null}
            <span className="mt-1 block text-xs text-muted">
              {formatDateTime(entry.created_at)}
            </span>
            <span className="mt-3 block text-sm text-ink">
              {entry.richness === null
                ? 'Richness not available'
                : pluralize(entry.richness, 'species', 'species')}
            </span>
            {entry.top_species.length ? (
              <span className="mt-0.5 block text-xs text-muted">
                {entry.top_species.join(', ')}
              </span>
            ) : null}
            <span className="mt-auto inline-flex items-center gap-1 pt-3 text-xs font-medium text-accent">
              Open results{' '}
              <ArrowRightIcon
                size={13}
                className="transition-transform group-hover:translate-x-0.5"
              />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ServerList({
  onOpen,
  onDeleted,
}: {
  onOpen: (id: string) => void;
  onDeleted: (id: string) => void;
}) {
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setError(null);
    try {
      const list = await listAnalyses(signal);
      setItems(list.items);
    } catch (err) {
      const friendly = describeError(err);
      if (friendly) setError(friendly);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const remove = async (id: string) => {
    setDeleting(id);
    try {
      await deleteAnalysis(id);
      setItems((current) => current?.filter((i) => i.id !== id) ?? null);
      onDeleted(id);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setDeleting(null);
    }
  };

  if (error) return <ErrorCallout error={error} onRetry={() => void load()} />;
  if (items === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner size={14} /> Loading analyses stored on the server...
      </p>
    );
  }
  if (items.length === 0) {
    return <p className="text-sm text-muted">The server has no stored analyses.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-sm">
        <caption className="sr-only">Analyses stored on this Thicket server</caption>
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            <th scope="col" className="py-2 pr-3 text-left font-medium">
              Recording
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Created
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Status
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Species
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Events
            </th>
            <th scope="col" className="py-2 pl-3 text-right font-medium">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map((item) => (
            <tr key={item.id}>
              <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                <span className="block font-medium text-ink">
                  {item.site_name || item.filename || item.id}
                </span>
                <span className="block text-xs text-muted">
                  {item.filename ?? ''}
                  {item.duration_seconds != null
                    ? ` · ${formatDuration(item.duration_seconds)}`
                    : ''}
                  {` · at ${thresholdPercent(item.decision_threshold)}`}
                </span>
              </th>
              <td className="px-3 py-2.5 text-muted">{formatDateTime(item.created_at)}</td>
              <td className="px-3 py-2.5">
                <Badge
                  tone={
                    item.status === 'completed'
                      ? 'ok'
                      : item.status === 'failed'
                        ? 'danger'
                        : 'neutral'
                  }
                >
                  {item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                </Badge>
              </td>
              <td className="num px-3 py-2.5 text-right text-ink">
                {item.species_richness ?? 'n/a'}
              </td>
              <td className="num px-3 py-2.5 text-right text-ink">
                {item.total_detection_events ?? 'n/a'}
              </td>
              <td className="py-2.5 pl-3 text-right">
                <span className="inline-flex gap-1">
                  <Button size="sm" variant="secondary" onClick={() => onOpen(item.id)}>
                    Open
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void remove(item.id)}
                    disabled={deleting === item.id}
                    aria-label={`Delete ${item.filename ?? item.id} from the server`}
                  >
                    <TrashIcon size={14} />
                    Delete
                  </Button>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryPage({
  entries,
  onOpen,
  onHistoryChanged,
}: {
  entries: HistoryEntry[];
  onOpen: (id: string) => void;
  onHistoryChanged: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-[1.75rem] font-semibold tracking-tight text-ink">History</h1>
        <p className="mt-2 flex gap-2 text-sm text-muted">
          <ShieldIcon size={16} className="mt-0.5 shrink-0 text-subtle" />
          <span>
            This browser keeps short summaries of your last three analyses. Audio is not stored, and
            full results live on your local Thicket server, so opening an item loads it from there.
          </span>
        </p>
      </div>

      <Panel labelledBy="local-history-heading" className="p-5 sm:p-6">
        <h2
          id="local-history-heading"
          className="mb-4 text-base font-semibold tracking-tight text-ink"
        >
          Recent on this device
        </h2>
        <LocalHistory entries={entries} onOpen={onOpen} />
      </Panel>

      <Panel labelledBy="server-history-heading" className="p-5 sm:p-6">
        <h2 id="server-history-heading" className="text-base font-semibold tracking-tight text-ink">
          Stored on this server
        </h2>
        <p className="mb-4 mt-1 text-sm text-muted">
          Deleting removes the analysis and its derived files (spectrogram, exports) from the
          server.
        </p>
        <ServerList
          onOpen={onOpen}
          onDeleted={(id) => {
            removeFromHistory(id);
            onHistoryChanged();
          }}
        />
      </Panel>
    </div>
  );
}

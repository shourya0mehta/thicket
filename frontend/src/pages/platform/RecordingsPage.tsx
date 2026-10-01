import { useId, useState, type FormEvent } from 'react';
import type { QualityStatus } from '../../api/generated';
import { SiteSelect } from '../../components/platform/filters';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
  TextInput,
} from '../../components/platform/primitives';
import { RecordingsTable } from '../../components/platform/RecordingsTable';
import { Button, ButtonLink } from '../../components/ui/Button';
import { ChevronLeftIcon, ChevronRightIcon, UploadIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { useResource } from '../../hooks/useResource';
import { formatInteger } from '../../lib/format';
import { navigateTo, orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

const PAGE_SIZE = 25;
const QUALITY_OPTIONS: Array<{ value: QualityStatus | ''; label: string }> = [
  { value: '', label: 'Any audio quality' },
  { value: 'usable', label: 'Usable' },
  { value: 'usable_with_warnings', label: 'Usable with warnings' },
  { value: 'not_usable', label: 'Not usable' },
];

export function RecordingsPage({ query }: { query: URLSearchParams }) {
  const { api } = usePlatform();
  const { org, sites } = useOrg();
  const siteId = query.get('site_id');
  const from = query.get('from') ?? '';
  const to = query.get('to') ?? '';
  const quality = query.get('quality') ?? '';
  const species = query.get('species') ?? '';
  const page = Math.max(1, Number(query.get('page') ?? '1') || 1);
  const [draft, setDraft] = useState({ from, to, species });
  const ids = useId();

  const recordings = useResource(
    (signal) =>
      api.listRecordings(
        org.id,
        {
          site_id: siteId,
          from: from || null,
          to: to || null,
          quality: quality || null,
          species: species || null,
          page,
          page_size: PAGE_SIZE,
        },
        signal,
      ),
    `recordings:${org.id}:${siteId ?? ''}:${from}:${to}:${quality}:${species}:${page}`,
  );

  const setQuery = (patch: Record<string, string | null | undefined>) => {
    navigateTo(
      orgHref(org.id, 'recordings', null, {
        site_id: siteId,
        from,
        to,
        quality,
        species,
        page: null,
        ...patch,
      }),
    );
  };
  const applyDraft = (event: FormEvent) => {
    event.preventDefault();
    setQuery({
      from: draft.from || null,
      to: draft.to || null,
      species: draft.species.trim() || null,
    });
  };

  const total = recordings.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasFilters = Boolean(siteId || from || to || quality || species);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Recordings"
        description="Every analyzed file, newest first. Open one to review its detection events at any threshold."
        actions={
          <ButtonLink href={orgHref(org.id, 'upload')} variant="primary" size="sm">
            <UploadIcon size={14} /> Upload recordings
          </ButtonLink>
        }
      />

      <form
        onSubmit={applyDraft}
        className="flex flex-wrap items-end gap-x-4 gap-y-3"
        aria-label="Filter recordings"
        data-testid="recording-filters"
      >
        <SiteSelect
          sites={sites.data ?? []}
          value={siteId}
          onChange={(id) => setQuery({ site_id: id })}
        />
        <label htmlFor={`${ids}-from`} className="text-xs text-muted">
          From
          <TextInput
            id={`${ids}-from`}
            type="date"
            className="mt-0.5 h-8 w-40 py-1"
            value={draft.from}
            onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))}
          />
        </label>
        <label htmlFor={`${ids}-to`} className="text-xs text-muted">
          To
          <TextInput
            id={`${ids}-to`}
            type="date"
            className="mt-0.5 h-8 w-40 py-1"
            value={draft.to}
            onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))}
          />
        </label>
        <label htmlFor={`${ids}-quality`} className="text-xs text-muted">
          Audio quality
          <Select
            id={`${ids}-quality`}
            className="mt-0.5 h-8 w-auto py-1"
            value={quality}
            onChange={(e) => setQuery({ quality: e.target.value || null })}
          >
            {QUALITY_OPTIONS.map((q) => (
              <option key={q.value} value={q.value}>
                {q.label}
              </option>
            ))}
          </Select>
        </label>
        <label htmlFor={`${ids}-species`} className="text-xs text-muted">
          Species
          <TextInput
            id={`${ids}-species`}
            type="search"
            className="mt-0.5 h-8 w-48 py-1"
            placeholder="Scientific or common name"
            value={draft.species}
            onChange={(e) => setDraft((d) => ({ ...d, species: e.target.value }))}
          />
        </label>
        <Button type="submit" size="sm" variant="secondary">
          Apply
        </Button>
        {hasFilters ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setDraft({ from: '', to: '', species: '' });
              navigateTo(orgHref(org.id, 'recordings'));
            }}
          >
            Clear
          </Button>
        ) : null}
      </form>

      <Panel className="p-5 sm:p-6" label="Recordings list">
        {recordings.error ? (
          <ErrorState error={recordings.error} onRetry={recordings.reload} />
        ) : null}
        {recordings.loading ? <LoadingState label="Loading recordings..." /> : null}
        {recordings.data ? (
          recordings.data.items.length ? (
            <div className={recordings.busy ? 'opacity-60 transition-opacity' : ''}>
              <p className="mb-3 text-xs text-muted" data-testid="recordings-count">
                {formatInteger(total)} recordings{hasFilters ? ' match' : ''} · page {page} of{' '}
                {pages}
              </p>
              <RecordingsTable rows={recordings.data.items} orgId={org.id} />
              {pages > 1 ? (
                <nav className="mt-4 flex items-center justify-between" aria-label="Pages">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={page <= 1}
                    onClick={() => setQuery({ page: String(page - 1) })}
                  >
                    <ChevronLeftIcon size={14} /> Newer
                  </Button>
                  <span className="num text-xs text-muted">
                    {page} / {pages}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={page >= pages}
                    onClick={() => setQuery({ page: String(page + 1) })}
                  >
                    Older <ChevronRightIcon size={14} />
                  </Button>
                </nav>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title={hasFilters ? 'No recordings match these filters' : 'No recordings yet'}
            >
              {hasFilters
                ? 'Widen the dates or clear a filter.'
                : 'Upload a batch from a recorder card, or analyze a single file.'}
            </EmptyState>
          )
        ) : null}
      </Panel>
    </div>
  );
}

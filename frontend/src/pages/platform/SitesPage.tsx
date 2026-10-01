import { useMemo, useState } from 'react';
import type { Site, SiteComparisonRow } from '../../api/generated';
import { Sparkline } from '../../components/charts/Sparkline';
import { HealthPill } from '../../components/platform/pills';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  ReadOnlyNote,
  SectionHeading,
} from '../../components/platform/primitives';
import { SiteForm } from '../../components/platform/SiteForm';
import { habitatLabel } from '../../lib/labels';
import { Button, ButtonLink } from '../../components/ui/Button';
import { ArrowRightIcon, MapPinIcon, PlusIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { useResource } from '../../hooks/useResource';
import { periodFromQuery, relativeTime } from '../../lib/dates';
import { formatInteger, formatNumber, formatPercent } from '../../lib/format';
import { navigateTo, orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

function SiteCard({ site, orgId }: { site: Site; orgId: string }) {
  const s = site.stats;
  return (
    <li>
      <a
        href={orgHref(orgId, 'site', site.id)}
        className="group flex h-full flex-col rounded-2xl border border-line-strong bg-raised p-4 transition-colors hover:border-mark/60"
        data-testid="site-card"
      >
        <span className="flex items-start justify-between gap-2">
          <span className="min-w-0">
            <span className="block truncate text-base font-semibold text-ink">{site.name}</span>
            <span className="block text-xs text-muted">
              {habitatLabel(site.habitat_type)}
              {site.area_hectares != null ? ` · ${formatNumber(site.area_hectares, 1)} ha` : ''}
            </span>
          </span>
          <HealthPill status={s.health} />
        </span>
        <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt className="text-xs text-muted">Recordings</dt>
            <dd className="num font-semibold text-ink">{formatInteger(s.recordings ?? 0)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Species</dt>
            <dd className="num font-semibold text-ink">{formatInteger(s.species_counted ?? 0)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Open alerts</dt>
            <dd className="num font-semibold text-ink">{formatInteger(s.open_alerts ?? 0)}</dd>
          </div>
        </dl>
        <span className="mt-3 flex items-center justify-between text-xs text-muted">
          <span className="inline-flex items-center gap-1">
            <MapPinIcon size={12} />
            {site.latitude != null && site.longitude != null ? 'Mapped' : 'No coordinates'}
            {' · last recording '}
            {relativeTime(s.last_recording_at)}
          </span>
          <ArrowRightIcon size={13} className="transition-transform group-hover:translate-x-0.5" />
        </span>
      </a>
    </li>
  );
}

function ComparisonTable({ rows }: { rows: SiteComparisonRow[] }) {
  const maxEpm = Math.max(0.01, ...rows.map((r) => r.events_per_minute));
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <caption className="sr-only">Site comparison for the period</caption>
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            <th scope="col" className="py-2 pr-3 text-left font-medium">
              Site
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Recordings
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Minutes
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Species
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Shannon
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Events per minute
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Usable
            </th>
            <th scope="col" className="py-2 pl-3 text-left font-medium">
              Top species
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.site.id}>
              <th scope="row" className="py-2.5 pr-3 text-left font-medium text-ink">
                {r.site.name}
                <span className="block text-xs font-normal text-muted">
                  {habitatLabel(r.site.habitat_type)}
                </span>
              </th>
              <td className="num px-3 py-2.5 text-right">{formatInteger(r.recordings)}</td>
              <td className="num px-3 py-2.5 text-right">{formatInteger(r.minutes)}</td>
              <td className="num px-3 py-2.5 text-right font-semibold text-ink">
                {formatInteger(r.species_richness)}
              </td>
              <td className="num px-3 py-2.5 text-right">
                {r.shannon_index == null ? 'n/a' : formatNumber(r.shannon_index, 2)}
              </td>
              <td className="px-3 py-2.5">
                <span className="flex items-center gap-2">
                  <span
                    className="block h-2 rounded-r-full bg-mark"
                    style={{ width: `${Math.max(4, (r.events_per_minute / maxEpm) * 96)}px` }}
                    aria-hidden="true"
                  />
                  <span className="num text-ink">{formatNumber(r.events_per_minute, 1)}</span>
                </span>
              </td>
              <td className="num px-3 py-2.5 text-right">
                {r.usable_fraction == null ? 'n/a' : formatPercent(r.usable_fraction)}
              </td>
              <td className="py-2.5 pl-3 text-xs text-muted">
                {r.top_species.map((s) => s.common_name).join(', ') || 'None'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SitesPage({ query }: { query: URLSearchParams }) {
  const { api } = usePlatform();
  const { org, sites, permissions } = useOrg();
  const [adding, setAdding] = useState(query.get('new') === '1');
  const period = useMemo(() => periodFromQuery(query), [query]);
  const comparison = useResource(
    (signal) => api.compareSites(org.id, { from: period.from, to: period.to }, signal),
    `compare:${org.id}:${period.from}:${period.to}`,
    (sites.data?.length ?? 0) > 1,
  );

  const create = async (body: Parameters<typeof api.createSite>[1]) => {
    const site = await api.createSite(org.id, body);
    sites.setData((current) => [...(current ?? []), site]);
    setAdding(false);
    navigateTo(orgHref(org.id, 'site', site.id));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Sites"
        description="A site is a place you record: a pasture, a pond edge, a hedgerow. Recordings, baselines and alerts are kept per site."
        actions={
          permissions.canManage ? (
            <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
              <PlusIcon size={14} /> Add site
            </Button>
          ) : null
        }
      />

      {adding && permissions.canManage ? (
        <Panel className="p-5 sm:p-6" label="New site">
          <SectionHeading>New site</SectionHeading>
          <SiteForm onSubmit={create} onCancel={() => setAdding(false)} />
        </Panel>
      ) : null}

      {sites.error ? <ErrorState error={sites.error} onRetry={sites.reload} /> : null}
      {sites.loading ? <LoadingState label="Loading sites..." /> : null}
      {sites.data && sites.data.length === 0 && !adding ? (
        <EmptyState
          title="No sites yet"
          action={
            permissions.canManage ? (
              <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
                <PlusIcon size={14} /> Add your first site
              </Button>
            ) : null
          }
          testId="sites-empty"
        >
          Add the places where recorders go. Coordinates are optional but needed for maps and
          range-aware species checks.
          {!permissions.canManage ? <ReadOnlyNote /> : null}
        </EmptyState>
      ) : null}
      {sites.data && sites.data.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="site-list">
          {sites.data.map((s) => (
            <SiteCard key={s.id} site={s} orgId={org.id} />
          ))}
        </ul>
      ) : null}

      {(sites.data?.length ?? 0) > 1 ? (
        <Panel className="p-5 sm:p-6" labelledBy="compare-heading">
          <SectionHeading
            id="compare-heading"
            eyebrow="Compare"
            note={
              <a className="link" href={orgHref(org.id, 'dashboard')}>
                Change the period on the dashboard
              </a>
            }
          >
            Sites side by side
          </SectionHeading>
          {comparison.error ? (
            <ErrorState error={comparison.error} onRetry={comparison.reload} />
          ) : comparison.data ? (
            comparison.data.rows.length ? (
              <>
                <ComparisonTable rows={comparison.data.rows} />
                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {comparison.data.rows.slice(0, 8).map((r) => (
                    <div key={r.site.id} className="well px-3 py-2">
                      <p className="truncate text-xs font-medium text-ink">{r.site.name}</p>
                      <div className="mt-1 flex items-end justify-between gap-2">
                        <span className="num text-lg font-semibold text-ink">
                          {formatInteger(r.species_richness)}
                          <span className="ml-1 text-xs font-normal text-muted">species</span>
                        </span>
                        <Sparkline
                          values={[r.minutes, r.recordings, r.species_richness]}
                          label={`${r.site.name}: minutes, recordings and species`}
                          width={56}
                          height={22}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-muted">
                  Effort differs between sites. Compare events per minute and presence, not raw
                  event totals, and only across the same season.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">No recordings in this period to compare.</p>
            )
          ) : (
            <LoadingState label="Comparing sites..." />
          )}
        </Panel>
      ) : null}

      {sites.data?.length ? (
        <p className="text-xs text-muted">
          <ButtonLink href={orgHref(org.id, 'upload')} size="sm" variant="secondary">
            Upload recordings to a site
          </ButtonLink>
        </p>
      ) : null}
    </div>
  );
}

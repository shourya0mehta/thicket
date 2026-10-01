import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { SiteUpdate } from '../../api/generated';
import { AccumulationChart } from '../../components/charts/AccumulationChart';
import { ChartFrame, LegendItem } from '../../components/charts/ChartFrame';
import { PhenologyRibbon } from '../../components/charts/PhenologyRibbon';
import { TimeSeriesChart } from '../../components/charts/TimeSeriesChart';
import { MARK } from '../../components/charts/theme';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { SeverityPill, HealthPill } from '../../components/platform/pills';
import { habitatLabel, kindLabel } from '../../lib/labels';
import {
  EmptyState,
  ErrorState,
  Facts,
  LoadingState,
  PageHeader,
  SectionHeading,
  Select,
} from '../../components/platform/primitives';
import { RecordingsTable } from '../../components/platform/RecordingsTable';
import { SiteForm } from '../../components/platform/SiteForm';
import { Button, ButtonLink } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { MapPinIcon, TrashIcon, UploadIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { Spinner } from '../../components/ui/Spinner';
import { useResource } from '../../hooks/useResource';
import { buildDaySeries } from '../../lib/dashboard';
import { longDate, periodFromQuery, relativeTime } from '../../lib/dates';
import { formatCoordinate, formatDateTime, formatInteger, formatNumber } from '../../lib/format';
import { navigateTo, orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

const SiteMap = lazy(() => import('../../components/platform/SiteMap'));

export function SitePage({ siteId, query }: { siteId: string; query: URLSearchParams }) {
  const { api } = usePlatform();
  const { org, sites, permissions, recorderLabel } = useOrg();
  const [editing, setEditing] = useState(false);
  const [deleteError, setDeleteError] = useState<FriendlyError | null>(null);
  const [deleting, setDeleting] = useState(false);
  const period = useMemo(() => periodFromQuery(query), [query]);

  const site = useResource((signal) => api.getSite(siteId, signal), `site:${siteId}`);
  const dashboard = useResource(
    (signal) =>
      api.getDashboard(org.id, { from: period.from, to: period.to, site_id: siteId }, signal),
    `site-dash:${siteId}:${period.from}:${period.to}`,
  );
  const accumulation = useResource(
    (signal) => api.getAccumulation(siteId, signal),
    `accumulation:${siteId}`,
  );
  const deployments = useResource(
    (signal) => api.listDeployments(org.id, {}, signal),
    `deployments:${org.id}`,
  );
  const recordings = useResource(
    (signal) => api.listRecordings(org.id, { site_id: siteId, page: 1, page_size: 8 }, signal),
    `site-recordings:${siteId}`,
  );
  const alerts = useResource(
    (signal) => api.listAlerts(org.id, { status: 'open', site_id: siteId }, signal),
    `site-alerts:${siteId}`,
  );

  const dashboardSpecies = dashboard.data?.species;
  const topSpecies = useMemo(
    () =>
      (dashboardSpecies ?? [])
        .slice()
        .sort((a, b) => b.presence_fraction - a.presence_fraction)
        .slice(0, 8),
    [dashboardSpecies],
  );
  const [speciesPick, setSpeciesPick] = useState<string | null>(null);
  const chosen = speciesPick ?? topSpecies[0]?.scientific_name ?? null;
  useEffect(() => {
    if (speciesPick && !topSpecies.some((s) => s.scientific_name === speciesPick)) {
      setSpeciesPick(null);
    }
  }, [speciesPick, topSpecies]);
  const phenology = useResource(
    (signal) =>
      api.getPhenology(org.id, { scientific_name: chosen!, site_id: siteId, years: 3 }, signal),
    `phenology:${siteId}:${chosen ?? ''}`,
    chosen !== null,
  );

  const s = site.data;
  const series = useMemo(
    () =>
      dashboard.data
        ? buildDaySeries(
            dashboard.data.richness_by_day,
            dashboard.data.period_start,
            dashboard.data.period_end,
          )
        : null,
    [dashboard.data],
  );
  const siteDeployments = (deployments.data ?? []).filter((d) => d.site_id === siteId);

  const save = async (body: SiteUpdate) => {
    const updated = await api.updateSite(siteId, body);
    site.setData(updated);
    sites.setData((current) => (current ?? []).map((x) => (x.id === updated.id ? updated : x)));
    setEditing(false);
  };

  const remove = async () => {
    if (!s) return;
    if (!window.confirm(`Delete ${s.name}? This only works for a site without recordings.`)) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteSite(siteId);
      sites.setData((current) => (current ?? []).filter((x) => x.id !== siteId));
      navigateTo(orgHref(org.id, 'sites'));
    } catch (err) {
      setDeleteError(describeError(err));
    } finally {
      setDeleting(false);
    }
  };

  if (site.error) {
    return (
      <ErrorState
        error={site.error}
        onRetry={site.reload}
        backHref={orgHref(org.id, 'sites')}
        backLabel="Back to sites"
      />
    );
  }
  if (!s) return <LoadingState label="Loading the site..." />;

  const mapped = s.latitude != null && s.longitude != null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <a href={orgHref(org.id, 'sites')} className="hover:underline">
            Sites
          </a>
        }
        title={s.name}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{habitatLabel(s.habitat_type)}</span>
            {s.area_hectares != null ? <span>{formatNumber(s.area_hectares, 1)} ha</span> : null}
            <span className="inline-flex items-center gap-1">
              <MapPinIcon size={14} className="text-subtle" />
              {mapped
                ? `${formatCoordinate(s.latitude!, 'lat')}, ${formatCoordinate(s.longitude!, 'lon')}`
                : 'No coordinates'}
            </span>
            <HealthPill status={s.stats.health} />
          </span>
        }
        actions={
          <>
            <ButtonLink
              href={orgHref(org.id, 'upload', null, { site_id: s.id })}
              variant="primary"
              size="sm"
            >
              <UploadIcon size={14} /> Upload here
            </ButtonLink>
            {permissions.canManage ? (
              <Button variant="secondary" size="sm" onClick={() => setEditing((v) => !v)}>
                {editing ? 'Close editor' : 'Edit site'}
              </Button>
            ) : null}
          </>
        }
      />

      {editing && permissions.canManage ? (
        <Panel className="p-5 sm:p-6" label="Edit site">
          <SectionHeading>Edit site</SectionHeading>
          <SiteForm site={s} onSubmit={save} onCancel={() => setEditing(false)} />
          <div className="mt-6 border-t border-line pt-4">
            <p className="text-sm text-muted">
              Deleting is only possible for a site without recordings. To retire a site that has
              data, end its deployments instead; its history stays available.
            </p>
            {deleteError ? <ErrorCallout className="mt-3" error={deleteError} /> : null}
            <Button
              variant="danger"
              size="sm"
              className="mt-3"
              onClick={() => void remove()}
              disabled={deleting}
            >
              <TrashIcon size={14} /> Delete site
            </Button>
          </div>
        </Panel>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-12">
        <Panel className="p-5 sm:p-6 lg:col-span-5 min-w-0" labelledBy="site-facts-heading">
          <SectionHeading id="site-facts-heading" eyebrow="Site">
            Facts
          </SectionHeading>
          <Facts
            items={[
              { label: 'Recordings', value: formatInteger(s.stats.recordings ?? 0) },
              { label: 'Minutes recorded', value: formatInteger(s.stats.minutes_recorded ?? 0) },
              { label: 'Species counted', value: formatInteger(s.stats.species_counted ?? 0) },
              {
                label: 'First recording',
                value: formatDateTime(s.stats.first_recording_at, org.timezone),
              },
              { label: 'Last recording', value: relativeTime(s.stats.last_recording_at) },
              { label: 'Open alerts', value: formatInteger(s.stats.open_alerts ?? 0) },
              { label: 'FSA field', value: s.fsa_field_number || 'Not set' },
              { label: 'Paddock', value: s.paddock_id || 'Not set' },
            ]}
          />
          {s.notes ? <p className="mt-4 text-sm text-muted">{s.notes}</p> : null}
          <h3 className="mt-6 text-sm font-semibold text-ink">Deployments</h3>
          {siteDeployments.length ? (
            <ul className="mt-2 divide-y divide-line text-sm">
              {siteDeployments.map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-3 py-2">
                  <a href={orgHref(org.id, 'recorder', d.recorder_id)} className="link">
                    {recorderLabel(d.recorder_id)}
                  </a>
                  <span className="text-xs text-muted">
                    {longDate(d.started_at.slice(0, 10))} to{' '}
                    {d.ended_at ? longDate(d.ended_at.slice(0, 10)) : 'now'}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted">
              No recorder has been deployed here yet.{' '}
              <a className="link" href={orgHref(org.id, 'recorders')}>
                Manage recorders
              </a>
            </p>
          )}
        </Panel>
        <div className="lg:col-span-7 min-w-0">
          {mapped ? (
            <Suspense
              fallback={
                <p className="flex items-center gap-2 text-sm text-muted">
                  <Spinner size={14} /> Loading map...
                </p>
              }
            >
              <SiteMap
                latitude={s.latitude!}
                longitude={s.longitude!}
                name={s.name}
                className="h-64 lg:h-full lg:min-h-[18rem]"
              />
            </Suspense>
          ) : (
            <EmptyState title="No coordinates for this site">
              Add latitude and longitude to see the site on a map and to let species checks use the
              local range and season.
            </EmptyState>
          )}
        </div>
      </div>

      {dashboard.error ? <ErrorState error={dashboard.error} onRetry={dashboard.reload} /> : null}
      <div className="grid gap-5 xl:grid-cols-12">
        <ChartFrame
          eyebrow="Seasonal view"
          title="Species richness by day"
          note={`${longDate(period.from)} to ${longDate(period.to)}`}
          className="xl:col-span-7 min-w-0"
          dimmed={dashboard.busy}
          testId="site-richness-chart"
          footer={
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <LegendItem color={MARK} shape="line">
                Species richness
              </LegendItem>
              <LegendItem color={MARK} shape="band">
                14-day rolling median plus or minus MAD (browser-computed)
              </LegendItem>
              <LegendItem color={MARK}>Recordings per day</LegendItem>
            </div>
          }
        >
          {() =>
            series ? (
              <TimeSeriesChart
                points={series.dates.map((x, i) => ({ x, y: series.richness[i] ?? null }))}
                band={series.baseline.map((b) => ({ low: b.low, high: b.high, center: b.center }))}
                bars={series.recordings}
                yLabel="Species richness"
                title={`Species richness by day at ${s.name}`}
                description={`Daily species richness at ${s.name} with a rolling median band and recordings per day.`}
                caption={`Species richness by day at ${s.name}`}
              />
            ) : (
              <LoadingState />
            )
          }
        </ChartFrame>
        <ChartFrame
          eyebrow="Effort"
          title="Species accumulation"
          note="Cumulative species against recordings"
          className="xl:col-span-5 min-w-0"
          testId="accumulation-chart"
          footer={
            accumulation.data?.note ??
            'A curve that keeps climbing means more recordings would still add species; a flat tail means the effort has found most of what this method detects.'
          }
        >
          {() =>
            accumulation.error ? (
              <ErrorState error={accumulation.error} onRetry={accumulation.reload} />
            ) : accumulation.data ? (
              <AccumulationChart
                points={accumulation.data.points}
                title={`Species accumulation at ${s.name}`}
                caption={`Cumulative species by recording at ${s.name}`}
              />
            ) : (
              <LoadingState />
            )
          }
        </ChartFrame>
      </div>

      <ChartFrame
        eyebrow="Phenology"
        title="When a species is heard"
        note={
          topSpecies.length ? (
            <label className="flex items-center gap-2">
              Species
              <Select
                className="h-8 w-auto py-1"
                value={chosen ?? ''}
                onChange={(e) => setSpeciesPick(e.target.value)}
                aria-label="Species for the phenology ribbon"
              >
                {topSpecies.map((sp) => (
                  <option key={sp.scientific_name} value={sp.scientific_name}>
                    {sp.common_name}
                  </option>
                ))}
              </Select>
            </label>
          ) : null
        }
        testId="phenology-chart"
        footer="Each row is a year, each cell an ISO week. Shading is the share of that week's recordings with a detection, so it reads the same whether you recorded two mornings or twenty."
      >
        {() =>
          !chosen ? (
            <p className="text-sm text-muted">
              The ribbon appears once this site has counted species.
            </p>
          ) : phenology.error ? (
            <ErrorState error={phenology.error} onRetry={phenology.reload} />
          ) : phenology.data ? (
            <PhenologyRibbon
              phenology={phenology.data}
              caption={`${phenology.data.species.common_name} presence by ISO week at ${s.name}`}
            />
          ) : (
            <LoadingState />
          )
        }
      </ChartFrame>

      <div className="grid items-start gap-5 xl:grid-cols-12">
        <Panel className="p-5 sm:p-6 xl:col-span-8 min-w-0" labelledBy="site-recordings-heading">
          <SectionHeading
            id="site-recordings-heading"
            eyebrow="Recordings"
            note={
              <a className="link" href={orgHref(org.id, 'recordings', null, { site_id: s.id })}>
                All recordings at this site
              </a>
            }
          >
            Latest recordings
          </SectionHeading>
          {recordings.error ? (
            <ErrorState error={recordings.error} onRetry={recordings.reload} />
          ) : recordings.data ? (
            recordings.data.items.length ? (
              <RecordingsTable
                rows={recordings.data.items}
                orgId={org.id}
                showSite={false}
                compact
              />
            ) : (
              <p className="text-sm text-muted">No recordings here yet.</p>
            )
          ) : (
            <LoadingState />
          )}
        </Panel>
        <Panel className="p-5 sm:p-6 xl:col-span-4 min-w-0" labelledBy="site-alerts-heading">
          <SectionHeading id="site-alerts-heading" eyebrow="Alerts">
            Open alerts
          </SectionHeading>
          {alerts.data?.items.length ? (
            <ul className="divide-y divide-line">
              {alerts.data.items.map((a) => (
                <li key={a.id} className="py-2.5">
                  <a href={orgHref(org.id, 'alerts', null, { alert: a.id })} className="block">
                    <span className="flex flex-wrap items-center gap-2">
                      <SeverityPill severity={a.severity} />
                      <span className="text-sm font-medium text-ink">{a.title}</span>
                    </span>
                    <span className="mt-1 block text-xs text-muted">
                      {kindLabel(a.kind)} · {relativeTime(a.last_seen_at)}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Nothing open for this site.</p>
          )}
        </Panel>
      </div>

      <Callout tone="info">
        Site charts use this site&apos;s own recordings. Compare with other sites only across the
        same season and similar effort.
      </Callout>
    </div>
  );
}

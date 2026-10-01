import { useMemo, useState } from 'react';
import type { Alert, Dashboard } from '../../api/generated';
import { ChartFrame, LegendItem } from '../../components/charts/ChartFrame';
import { ActivityHeatmap } from '../../components/charts/Heatmap';
import { RankedBars } from '../../components/charts/RankedBars';
import { StackedBar } from '../../components/charts/StackedBar';
import { TimeSeriesChart } from '../../components/charts/TimeSeriesChart';
import { MARK, STATUS, TAXON_ORDER, TAXON_SLOT } from '../../components/charts/theme';
import { PeriodPicker, SiteSelect } from '../../components/platform/filters';
import { SeverityPill } from '../../components/platform/pills';
import { kindLabel } from '../../lib/labels';
import {
  EmptyState,
  ErrorState,
  KpiTile,
  LoadingState,
  PageHeader,
  SectionHeading,
} from '../../components/platform/primitives';
import { ButtonLink } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { TaxonIcon, UploadIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { useResource } from '../../hooks/useResource';
import {
  INDEX_META,
  bucketize,
  buildDaySeries,
  indexSeries,
  qualityCounts,
} from '../../lib/dashboard';
import { longDate, periodFromQuery, relativeTime, type PeriodPreset } from '../../lib/dates';
import { formatInteger, formatNumber, formatPercent } from '../../lib/format';
import { navigateTo, orgHref } from '../../lib/routes';
import { TAXON_LABEL } from '../../lib/taxa';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

const QUALITY_LABEL: Record<string, string> = {
  usable: 'Usable',
  usable_with_warnings: 'Usable with warnings',
  not_usable: 'Not usable',
};
const QUALITY_COLOR: Record<string, string> = {
  usable: STATUS.ok,
  usable_with_warnings: STATUS.warn,
  not_usable: STATUS.danger,
};

export function DashboardPage({ query }: { query: URLSearchParams }) {
  const { api } = usePlatform();
  const { org, sites } = useOrg();
  const period = useMemo(() => periodFromQuery(query), [query]);
  const siteId = query.get('site_id');
  const [activeDay, setActiveDay] = useState<number | null>(null);

  const dashboard = useResource(
    (signal) =>
      api.getDashboard(org.id, { from: period.from, to: period.to, site_id: siteId }, signal),
    `dashboard:${org.id}:${period.from}:${period.to}:${siteId ?? ''}`,
  );
  const alerts = useResource(
    (signal) => api.listAlerts(org.id, { status: 'open', site_id: siteId }, signal),
    `dash-alerts:${org.id}:${siteId ?? ''}`,
  );

  const setQuery = (patch: Record<string, string | null | undefined>) => {
    const next: Record<string, string | null | undefined> = {
      period: period.preset === 'custom' ? null : period.preset,
      from: period.preset === 'custom' ? period.from : null,
      to: period.preset === 'custom' ? period.to : null,
      site_id: siteId,
      ...patch,
    };
    navigateTo(orgHref(org.id, 'dashboard', null, next));
  };
  const onPeriod = (next: { preset: PeriodPreset; from?: string; to?: string }) => {
    if (next.preset === 'custom') setQuery({ period: null, from: next.from, to: next.to });
    else setQuery({ period: next.preset, from: null, to: null });
  };

  const d = dashboard.data;
  const series = useMemo(
    () => (d ? buildDaySeries(d.richness_by_day, d.period_start, d.period_end) : null),
    [d],
  );
  const site = siteId ? sites.data?.find((s) => s.id === siteId) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title={site ? `${site.name}` : 'Dashboard'}
        description={
          <>
            What your recorders heard from {longDate(period.from)} to {longDate(period.to)}. Counts
            are detection events, not animals.
          </>
        }
        actions={
          <ButtonLink href={orgHref(org.id, 'upload')} variant="primary" size="sm">
            <UploadIcon size={14} /> Upload recordings
          </ButtonLink>
        }
      />

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3" data-testid="dashboard-filters">
        <PeriodPicker period={period} onChange={onPeriod} />
        <SiteSelect
          sites={sites.data ?? []}
          value={siteId}
          onChange={(id) => setQuery({ site_id: id })}
        />
      </div>

      {dashboard.error ? <ErrorState error={dashboard.error} onRetry={dashboard.reload} /> : null}
      {dashboard.loading && !d ? <LoadingState label="Loading the dashboard..." /> : null}

      {d && series ? (
        <DashboardBody
          d={d}
          series={series}
          dimmed={dashboard.busy}
          orgId={org.id}
          siteId={siteId}
          activeDay={activeDay}
          onActiveDay={setActiveDay}
          openAlerts={alerts.data?.items ?? []}
          generatedAt={d.generated_at}
        />
      ) : null}
    </div>
  );
}

function DashboardBody({
  d,
  series,
  dimmed,
  orgId,
  siteId,
  activeDay,
  onActiveDay,
  openAlerts,
  generatedAt,
}: {
  d: Dashboard;
  series: ReturnType<typeof buildDaySeries>;
  dimmed: boolean;
  orgId: string;
  siteId: string | null;
  activeDay: number | null;
  onActiveDay: (i: number | null) => void;
  openAlerts: Alert[];
  generatedAt: string;
}) {
  const empty = d.recordings === 0;
  const points = series.dates.map((x, i) => ({ x, y: series.richness[i] ?? null }));
  const band = series.baseline.map((b) => ({ low: b.low, high: b.high, center: b.center }));
  const bandDays = series.baseline.filter((b) => b.center !== null).length;

  const taxonSegments = TAXON_ORDER.map((taxon) => {
    const row = d.by_taxon.find((t) => t.taxon === taxon);
    return {
      key: taxon,
      label: TAXON_LABEL[taxon],
      value: row?.detection_events ?? 0,
      color: TAXON_SLOT[taxon],
      icon: <TaxonIcon taxon={taxon} size={13} className="text-subtle" />,
      note: row ? `${formatInteger(row.species)} species` : undefined,
    };
  }).concat(
    d.by_taxon
      .filter((t) => !TAXON_ORDER.includes(t.taxon))
      .map((t) => ({
        key: t.taxon,
        label: TAXON_LABEL[t.taxon] ?? t.taxon,
        value: t.detection_events,
        color: TAXON_SLOT[t.taxon] ?? 'var(--viz-other)',
        icon: <TaxonIcon taxon={t.taxon} size={13} className="text-subtle" />,
        note: `${formatInteger(t.species)} species`,
      })),
  );

  const speciesRows = d.species
    .slice()
    .sort(
      (a, b) =>
        b.presence_fraction - a.presence_fraction || b.detection_events - a.detection_events,
    )
    .map((s) => ({
      key: s.scientific_name,
      label: s.common_name,
      sublabel: s.scientific_name,
      taxon: s.taxon,
      value: s.presence_fraction,
      valueText: formatPercent(s.presence_fraction),
      flagged: s.is_priority ?? false,
      flagLabel: 'Priority species',
      detail: (
        <>
          <p className="flex justify-between gap-3">
            <span className="text-muted">Recordings with detection</span>
            <span className="num font-semibold text-ink">
              {formatInteger(s.recordings_with_detection)} of {formatInteger(s.recordings_total)}
            </span>
          </p>
          <p className="flex justify-between gap-3">
            <span className="text-muted">Detection events</span>
            <span className="num font-semibold text-ink">{formatInteger(s.detection_events)}</span>
          </p>
          {s.last_detected_at ? (
            <p className="mt-0.5 text-muted">Last heard {relativeTime(s.last_detected_at)}</p>
          ) : null}
        </>
      ),
    }));

  const quality = qualityCounts(d);
  const indexSets = INDEX_META.map((meta) => ({
    meta,
    values: indexSeries(d.indices_by_day, series.dates, meta.key),
  })).filter((set) => set.values.some((v) => v !== null));

  return (
    <div className="space-y-6" data-testid="dashboard">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5" data-testid="kpi-row">
        <KpiTile
          label="Recordings"
          value={formatInteger(d.recordings)}
          info="Audio files analyzed in the period, across the selected sites."
          trend={bucketize(series.recordings)}
          trendLabel="Recordings per period slice"
          testId="kpi-recordings"
        />
        <KpiTile
          label="Minutes recorded"
          value={formatInteger(d.minutes_recorded)}
          info="Total length of the analyzed audio. Per-minute rates divide by this."
          trend={bucketize(series.minutes)}
          trendLabel="Minutes per period slice"
          testId="kpi-minutes"
        />
        <KpiTile
          label="Species counted"
          value={formatInteger(d.species_counted)}
          info="Distinct species with at least one counted detection event in the period."
          trend={bucketize(series.richness, 12, 'max')}
          trendLabel="Daily species richness, highest per slice"
          testId="kpi-species"
        />
        <KpiTile
          label="Detection events"
          value={formatInteger(d.detection_events)}
          info="Stretches of audio in which a species was detected above the recorded threshold."
          trend={bucketize(series.events)}
          trendLabel="Detection events per period slice"
          testId="kpi-events"
        />
        <KpiTile
          label="Open alerts"
          value={formatInteger(d.open_alerts)}
          info="Ecology, audio quality and recorder alerts that nobody has acknowledged or resolved."
          href={orgHref(orgId, 'alerts', null, { status: 'open', site_id: siteId })}
          testId="kpi-alerts"
        />
      </dl>

      {empty ? (
        <EmptyState
          title="No recordings in this period"
          action={
            <ButtonLink href={orgHref(orgId, 'upload')} variant="primary" size="sm">
              <UploadIcon size={14} /> Upload recordings
            </ButtonLink>
          }
          testId="dashboard-empty"
        >
          Upload a batch from a recorder card or widen the period to see charts here.
        </EmptyState>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-12">
        <ChartFrame
          eyebrow="Seasonal view"
          title="Species richness by day"
          note={
            series.multiSite
              ? 'Highest site value per day; recordings add up across sites'
              : 'Species with at least one counted detection event that day'
          }
          dimmed={dimmed}
          className="xl:col-span-8 min-w-0"
          testId="richness-chart"
          footer={
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <LegendItem color={MARK} shape="line">
                Species richness
              </LegendItem>
              <LegendItem color={MARK} shape="band">
                Rolling baseline: 14-day median plus or minus MAD, computed in your browser from
                this series{bandDays ? '' : ' (needs 5 recorded days)'}
              </LegendItem>
              <LegendItem color={MARK}>Recordings per day</LegendItem>
            </div>
          }
        >
          {() => (
            <TimeSeriesChart
              points={points}
              band={band}
              bars={series.recordings}
              barsLabel="Recordings"
              yLabel="Species richness"
              title="Species richness by day"
              description={`Daily count of species with a counted detection event from ${longDate(series.dates[0] ?? d.period_start)} to ${longDate(series.dates[series.dates.length - 1] ?? d.period_end)}, with a 14-day rolling median band and recordings per day underneath.`}
              caption="Species richness, baseline band and recordings by day"
              activeIndex={activeDay}
              onActiveChange={onActiveDay}
            />
          )}
        </ChartFrame>

        <div className="space-y-5 xl:col-span-4 min-w-0">
          <Panel className="p-5 sm:p-6" label="How to read the baseline">
            <p className="eyebrow mb-1">Baseline</p>
            <p className="text-sm leading-relaxed text-ink">{d.baseline_note}</p>
            <p className="mt-2 text-xs text-muted">
              Baselines use the median and MAD, never the mean, so one loud morning does not move
              them. Generated {relativeTime(generatedAt)}.
            </p>
          </Panel>
          <ChartFrame
            eyebrow="Quality"
            title="Audio usability"
            note={`${formatInteger(d.recordings)} recordings`}
            dimmed={dimmed}
            testId="quality-chart"
          >
            {() => (
              <StackedBar
                segments={quality.map((q) => ({
                  key: q.key,
                  label: QUALITY_LABEL[q.key] ?? q.key.replace(/_/g, ' '),
                  value: q.count,
                  color: QUALITY_COLOR[q.key] ?? 'var(--viz-other)',
                }))}
                title="Recordings by audio usability"
                description={quality
                  .map((q) => `${QUALITY_LABEL[q.key] ?? q.key}: ${formatInteger(q.count)}`)
                  .join('; ')}
                caption="Recordings by audio usability status"
                valueLabel="Recordings"
                emptyText="No quality checks in this period."
              />
            )}
          </ChartFrame>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-12">
        <div className="min-w-0 space-y-5 xl:col-span-7">
          <ChartFrame
            eyebrow="Activity"
            title="Activity by time of day"
            note="Detection events per recorded minute"
            dimmed={dimmed}
            testId="heatmap-chart"
            footer="Local time in the organization zone. A dark dawn band is normal for birds; frogs and insects fill the evenings."
          >
            {() => (
              <ActivityHeatmap
                cells={d.activity_heatmap}
                title="Activity by weekday and hour"
                caption="Detection events per minute by weekday and hour"
              />
            )}
          </ChartFrame>
          <ChartFrame
            eyebrow="By taxon"
            title="Detection events by taxon"
            dimmed={dimmed}
            testId="taxon-chart"
          >
            {() => (
              <StackedBar
                segments={taxonSegments}
                title="Detection events by taxon"
                description={taxonSegments
                  .filter((s) => s.value > 0)
                  .map((s) => `${s.label}: ${formatInteger(s.value)} events`)
                  .join('; ')}
                caption="Detection events and species by taxon"
                valueLabel="Detection events"
                emptyText="No counted detection events in this period."
              />
            )}
          </ChartFrame>
        </div>
        <ChartFrame
          eyebrow="Species"
          title="Species by presence"
          note="Share of recordings with a detection"
          dimmed={dimmed}
          testId="species-chart"
          className="min-w-0 xl:col-span-5"
        >
          {() => (
            <RankedBars
              rows={speciesRows}
              asFraction
              valueLabel="Presence"
              title="Species ranked by presence"
              description={speciesRows
                .slice(0, 12)
                .map((r) => `${r.label}: present in ${r.valueText} of recordings`)
                .join('; ')}
              caption="Species ranked by the share of recordings with a detection"
              moreHref={orgHref(orgId, 'recordings', null, { site_id: siteId })}
            />
          )}
        </ChartFrame>
      </div>

      <div className="grid gap-5 xl:grid-cols-12">
        <ChartFrame
          eyebrow="Soundscape"
          title="Soundscape indices by day"
          note="Context only, not species counts"
          dimmed={dimmed}
          className="xl:col-span-7 min-w-0"
          testId="indices-chart"
          footer="Signal-level indices respond to weather, wind and insects as well as wildlife. Each panel has its own scale."
        >
          {() =>
            indexSets.length ? (
              <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
                {indexSets.map(({ meta, values }) => (
                  <ChartFrame key={meta.key} plain title={`${meta.label} (${meta.short})`}>
                    {() => (
                      <TimeSeriesChart
                        compact
                        points={series.dates.map((x, i) => ({ x, y: values[i] ?? null }))}
                        yLabel={meta.short}
                        yMin={meta.min}
                        yFormat={(v) => formatNumber(v, meta.digits)}
                        title={`${meta.label} by day`}
                        description={`Daily ${meta.label.toLowerCase()} (${meta.short}) across the period.`}
                        caption={`${meta.label} by day`}
                        activeIndex={activeDay}
                        onActiveChange={onActiveDay}
                      />
                    )}
                  </ChartFrame>
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">
                No index values in this period.
              </p>
            )
          }
        </ChartFrame>

        <Panel className="p-5 sm:p-6 xl:col-span-5 min-w-0" labelledBy="recent-alerts-heading">
          <SectionHeading
            id="recent-alerts-heading"
            eyebrow="Alerts"
            note={
              <a className="link" href={orgHref(orgId, 'alerts', null, { site_id: siteId })}>
                Open the inbox
              </a>
            }
          >
            Open alerts
          </SectionHeading>
          {openAlerts.length ? (
            <ul className="divide-y divide-line" data-testid="recent-alerts">
              {openAlerts.slice(0, 6).map((a) => (
                <li key={a.id} className="py-2.5">
                  <a
                    href={orgHref(orgId, 'alerts', null, { alert: a.id })}
                    className="block rounded-lg"
                  >
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
            <p className="text-sm text-muted">
              Nothing open. New alerts appear here and in the inbox.
            </p>
          )}
          {d.open_alerts > 6 ? (
            <p className="mt-2 text-xs text-muted">
              {formatInteger(d.open_alerts - 6)} more in the inbox.
            </p>
          ) : null}
        </Panel>
      </div>

      <Callout tone="info">
        Every number here is derived from detection events at each recording&apos;s own threshold.
        Loud or frequent callers produce more events, so these numbers describe calling activity,
        not how many animals are present.
      </Callout>
    </div>
  );
}

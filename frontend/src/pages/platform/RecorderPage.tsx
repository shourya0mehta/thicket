import { useMemo, useState, type FormEvent } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type {
  Deployment,
  DeploymentCreate,
  HealthCheck,
  RecorderCreate,
  SeriesPoint,
} from '../../api/generated';
import { ChartFrame, LegendItem } from '../../components/charts/ChartFrame';
import { GapsTimeline } from '../../components/charts/GapsTimeline';
import { TimeSeriesChart, type BandInput } from '../../components/charts/TimeSeriesChart';
import { MARK } from '../../components/charts/theme';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { HealthPill, SeverityPill, type HealthStatus } from '../../components/platform/pills';
import { kindLabel } from '../../lib/labels';
import {
  ErrorState,
  Facts,
  Field,
  LoadingState,
  PageHeader,
  SectionHeading,
  Select,
  TextInput,
} from '../../components/platform/primitives';
import { Button } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { AlertIcon, CheckCircleIcon, InfoIcon, XCircleIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { useResource } from '../../hooks/useResource';
import { cx } from '../../lib/cx';
import { longDate, relativeTime, toDatetimeLocal } from '../../lib/dates';
import { formatDateTime, formatInteger, formatNumber, formatPercent } from '../../lib/format';
import { deviceName } from '../../lib/labels';
import { mad, median } from '../../lib/stats';
import { orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';
import { RecorderForm } from './RecordersPage';

const CHECK_ICON: Record<
  HealthCheck['status'],
  { Icon: typeof InfoIcon; tone: string; label: string }
> = {
  good: { Icon: CheckCircleIcon, tone: 'text-ok', label: 'Good' },
  watch: { Icon: AlertIcon, tone: 'text-warn', label: 'Watch' },
  attention: { Icon: XCircleIcon, tone: 'text-danger', label: 'Needs attention' },
  unknown: { Icon: InfoIcon, tone: 'text-subtle', label: 'No data' },
};

/** 2 rather than 2.00; 14.2 rather than 14.20; 0.11 keeps two decimals. */
function checkValue(value: number): string {
  if (Number.isInteger(value)) return formatInteger(value);
  return formatNumber(value, Math.abs(value) >= 10 ? 1 : 2);
}

function humanize(name: string): string {
  return kindLabel(name);
}

function toPoints(series: SeriesPoint[]) {
  return series
    .slice()
    .sort((a, b) => a.t.localeCompare(b.t))
    .map((p) => ({ x: p.t, y: Number.isFinite(p.v) ? p.v : null }));
}

/** Deployment baseline: the median plus or minus MAD of the whole series, as a flat band. */
function flatBand(series: SeriesPoint[]): BandInput[] | null {
  const values = series.map((p) => p.v).filter((v) => Number.isFinite(v));
  if (values.length < 5) return null;
  const center = median(values)!;
  const spread = mad(values)!;
  return series.map(() => ({ low: center - spread, high: center + spread, center }));
}

function DeploymentForm({
  recorderId,
  onSubmit,
  onCancel,
}: {
  recorderId: string;
  onSubmit: (body: DeploymentCreate) => Promise<void>;
  onCancel: () => void;
}) {
  const { sites } = useOrg();
  const [siteId, setSiteId] = useState('');
  const [startedAt, setStartedAt] = useState(toDatetimeLocal(new Date().toISOString()));
  const [interval, setInterval_] = useState('');
  const [clip, setClip] = useState('');
  const [schedule, setSchedule] = useState('');
  const [gain, setGain] = useState('');
  const [height, setHeight] = useState('');
  const [orientation, setOrientation] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<FriendlyError | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!siteId) {
      setFieldError('Choose the site this recorder was placed at.');
      return;
    }
    const started = new Date(startedAt);
    if (Number.isNaN(started.getTime())) {
      setFieldError('Enter the date and time the recorder was switched on.');
      return;
    }
    setFieldError(null);
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        recorder_id: recorderId,
        site_id: siteId,
        started_at: started.toISOString(),
        expected_interval_minutes: interval ? Number(interval) : null,
        expected_clip_seconds: clip ? Number(clip) : null,
        schedule_description: schedule.trim() || null,
        gain_setting: gain.trim() || null,
        mount_height_m: height ? Number(height) : null,
        orientation: orientation.trim() || null,
        notes: notes.trim() || null,
      });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="space-y-4"
      noValidate
      data-testid="deployment-form"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Site" required error={fieldError}>
          {(props) => (
            <Select {...props} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              <option value="">Choose a site</option>
              {(sites.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Started" required>
          {(props) => (
            <TextInput
              {...props}
              type="datetime-local"
              value={startedAt}
              onChange={(e) => setStartedAt(e.target.value)}
            />
          )}
        </Field>
        <Field
          label="Expected interval"
          hint="Minutes between recordings; enables gap and schedule checks."
        >
          {(props) => (
            <TextInput
              {...props}
              inputMode="numeric"
              className="num"
              value={interval}
              onChange={(e) => setInterval_(e.target.value)}
            />
          )}
        </Field>
        <Field label="Expected clip length" hint="Seconds per recording.">
          {(props) => (
            <TextInput
              {...props}
              inputMode="numeric"
              className="num"
              value={clip}
              onChange={(e) => setClip(e.target.value)}
            />
          )}
        </Field>
        <Field label="Schedule" hint="For example: 1 min every 5 min, 04:30 to 09:30.">
          {(props) => (
            <TextInput {...props} value={schedule} onChange={(e) => setSchedule(e.target.value)} />
          )}
        </Field>
        <Field label="Gain setting">
          {(props) => (
            <TextInput {...props} value={gain} onChange={(e) => setGain(e.target.value)} />
          )}
        </Field>
        <Field label="Mount height" hint="Meters.">
          {(props) => (
            <TextInput
              {...props}
              inputMode="decimal"
              className="num"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
            />
          )}
        </Field>
        <Field label="Orientation">
          {(props) => (
            <TextInput
              {...props}
              value={orientation}
              onChange={(e) => setOrientation(e.target.value)}
            />
          )}
        </Field>
        <Field label="Notes" className="sm:col-span-2">
          {(props) => (
            <textarea
              {...props}
              className="field-input min-h-[4rem]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          )}
        </Field>
      </div>
      {error ? <ErrorCallout error={error} /> : null}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Saving...' : 'Start deployment'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function HealthChecks({ checks }: { checks: HealthCheck[] }) {
  if (!checks.length) return <p className="text-sm text-muted">No checks have run yet.</p>;
  return (
    <ul className="divide-y divide-line" data-testid="health-checks">
      {checks.map((c) => {
        const meta = CHECK_ICON[c.status];
        return (
          <li key={c.name} className="flex gap-2.5 py-2">
            <meta.Icon size={16} className={cx('mt-0.5 shrink-0', meta.tone)} />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-ink">
                <span className="font-medium">{humanize(c.name)}</span>
                <span className="sr-only">: {meta.label}.</span>
                {c.value != null ? (
                  <span className="num ml-2 text-xs text-muted">
                    {checkValue(c.value)}
                    {c.baseline != null ? ` vs ${checkValue(c.baseline)} baseline` : ''}
                  </span>
                ) : null}
              </p>
              <p className="text-xs text-muted">{c.message}</p>
            </div>
            <span className={cx('text-xs font-medium', meta.tone)} aria-hidden="true">
              {meta.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function RecorderPage({
  recorderId,
  query,
}: {
  recorderId: string;
  query: URLSearchParams;
}) {
  const { api } = usePlatform();
  const { org, recorders, permissions, siteName } = useOrg();
  const days = Number(query.get('days') ?? '30') || 30;
  const [editing, setEditing] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [actionError, setActionError] = useState<FriendlyError | null>(null);

  const recorder = useResource(
    (signal) => api.getRecorder(recorderId, signal),
    `recorder:${recorderId}`,
  );
  const health = useResource(
    (signal) => api.getRecorderHealth(recorderId, days, signal),
    `health:${recorderId}:${days}`,
  );
  const deployments = useResource(
    (signal) => api.listDeployments(org.id, {}, signal),
    `deployments:${org.id}:${recorderId}`,
  );
  const mine = useMemo(
    () =>
      (deployments.data ?? [])
        .filter((d) => d.recorder_id === recorderId)
        .sort((a, b) => b.started_at.localeCompare(a.started_at)),
    [deployments.data, recorderId],
  );

  const r = recorder.data;
  const h = health.data;

  const save = async (body: RecorderCreate) => {
    const updated = await api.updateRecorder(recorderId, body);
    recorder.setData(updated);
    recorders.setData((current) => (current ?? []).map((x) => (x.id === updated.id ? updated : x)));
    setEditing(false);
  };
  const startDeployment = async (body: DeploymentCreate) => {
    const created = await api.createDeployment(org.id, body);
    deployments.setData((current) => [created, ...(current ?? [])]);
    setDeploying(false);
    health.reload();
  };
  const endDeployment = async (d: Deployment) => {
    setActionError(null);
    try {
      const updated = await api.updateDeployment(d.id, { ended_at: new Date().toISOString() });
      deployments.setData((current) =>
        (current ?? []).map((x) => (x.id === updated.id ? updated : x)),
      );
      health.reload();
    } catch (err) {
      setActionError(describeError(err));
    }
  };

  if (recorder.error) {
    return (
      <ErrorState
        error={recorder.error}
        onRetry={recorder.reload}
        backHref={orgHref(org.id, 'recorders')}
        backLabel="Back to recorders"
      />
    );
  }
  if (!r) return <LoadingState label="Loading the recorder..." />;

  const windowEnd = new Date();
  const windowStart = new Date(windowEnd.getTime() - days * 86_400_000);
  const status: HealthStatus = h?.status ?? r.health ?? 'unknown';

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <a href={orgHref(org.id, 'recorders')} className="hover:underline">
            Recorders
          </a>
        }
        title={r.label}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{deviceName(r.make, r.model)}</span>
            {r.serial ? <span className="num">Serial {r.serial}</span> : null}
            {r.firmware ? <span>Firmware {r.firmware}</span> : null}
            <HealthPill status={status} prefix="Health" />
          </span>
        }
        actions={
          permissions.canManage ? (
            <>
              <Button variant="primary" size="sm" onClick={() => setDeploying((v) => !v)}>
                {deploying ? 'Close' : 'New deployment'}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setEditing((v) => !v)}>
                {editing ? 'Close editor' : 'Edit'}
              </Button>
            </>
          ) : null
        }
      />

      {editing && permissions.canManage ? (
        <Panel className="p-5 sm:p-6" label="Edit recorder">
          <SectionHeading>Edit recorder</SectionHeading>
          <RecorderForm recorder={r} onSubmit={save} onCancel={() => setEditing(false)} />
        </Panel>
      ) : null}
      {deploying && permissions.canManage ? (
        <Panel className="p-5 sm:p-6" label="New deployment">
          <SectionHeading>New deployment</SectionHeading>
          <DeploymentForm
            recorderId={r.id}
            onSubmit={startDeployment}
            onCancel={() => setDeploying(false)}
          />
        </Panel>
      ) : null}
      {actionError ? <ErrorCallout error={actionError} /> : null}
      {health.error ? <ErrorState error={health.error} onRetry={health.reload} /> : null}

      <div className="grid gap-5 xl:grid-cols-12">
        <Panel className="p-5 sm:p-6 xl:col-span-5 min-w-0" labelledBy="health-heading">
          <SectionHeading
            id="health-heading"
            eyebrow="Health"
            note={
              <label htmlFor="health-window" className="flex items-center gap-2">
                Window
                <Select
                  id="health-window"
                  className="h-8 w-auto py-1"
                  value={String(days)}
                  onChange={(e) =>
                    (window.location.hash = orgHref(org.id, 'recorder', r.id, {
                      days: e.target.value,
                    }))
                  }
                >
                  <option value="7">7 days</option>
                  <option value="30">30 days</option>
                  <option value="90">90 days</option>
                </Select>
              </label>
            }
          >
            Checks
          </SectionHeading>
          {h ? (
            <>
              <Facts
                items={[
                  { label: 'Last recording', value: relativeTime(h.last_recording_at) },
                  {
                    label: 'Recordings, 7 days',
                    value:
                      h.expected_last_7d != null
                        ? `${formatInteger(h.recordings_last_7d)} of ${formatInteger(h.expected_last_7d)} expected`
                        : formatInteger(h.recordings_last_7d),
                  },
                  {
                    label: 'Uptime, 7 days',
                    value:
                      h.uptime_fraction_7d == null ? 'n/a' : formatPercent(h.uptime_fraction_7d),
                  },
                  {
                    label: 'Median interval',
                    value:
                      h.median_interval_minutes == null
                        ? 'n/a'
                        : `${formatNumber(h.median_interval_minutes, 0)} min`,
                  },
                  {
                    label: 'Deployment',
                    value: h.deployment ? (
                      <a className="link" href={orgHref(org.id, 'site', h.deployment.site_id)}>
                        {siteName(h.deployment.site_id)}
                      </a>
                    ) : (
                      'None active'
                    ),
                  },
                  { label: 'Gaps', value: formatInteger(h.gaps.length) },
                ]}
              />
              <div className="mt-4">
                <HealthChecks checks={h.checks} />
              </div>
              <p className="mt-3 text-xs text-muted">{h.baseline_note}</p>
            </>
          ) : (
            <LoadingState />
          )}
        </Panel>

        <div className="space-y-5 xl:col-span-7 min-w-0">
          <div className="grid gap-5 md:grid-cols-2">
            <ChartFrame eyebrow="Power" title="Battery" note="Volts" testId="battery-chart">
              {() =>
                h ? (
                  <TimeSeriesChart
                    compact
                    points={toPoints(h.battery)}
                    yLabel="Battery (V)"
                    yMin={null}
                    yFormat={(v) => formatNumber(v, 2)}
                    thresholds={[{ value: 3.6, label: 'low', tone: 'warn' }]}
                    title="Battery voltage over the window"
                    description="Battery voltage read from each recording's telemetry."
                    caption="Battery voltage by recording"
                  />
                ) : (
                  <LoadingState />
                )
              }
            </ChartFrame>
            <ChartFrame
              eyebrow="Environment"
              title="Temperature"
              note="Degrees C"
              testId="temperature-chart"
            >
              {() =>
                h ? (
                  <TimeSeriesChart
                    compact
                    points={toPoints(h.temperature)}
                    yLabel="Temperature (C)"
                    yMin={null}
                    yFormat={(v) => formatNumber(v, 1)}
                    title="Temperature over the window"
                    description="Temperature read from each recording's telemetry."
                    caption="Temperature by recording"
                  />
                ) : (
                  <LoadingState />
                )
              }
            </ChartFrame>
          </div>
          <ChartFrame
            eyebrow="Microphone"
            title="Level and high-band fraction"
            note="Against the deployment baseline"
            testId="level-chart"
            footer={
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <LegendItem color={MARK} shape="line">
                  Value per recording
                </LegendItem>
                <LegendItem color={MARK} shape="band">
                  Deployment median plus or minus MAD (same series)
                </LegendItem>
                <span>
                  A level that drifts 6 dB from the band, or a high-band fraction that sinks below
                  it, points to a wet or blocked microphone.
                </span>
              </div>
            }
          >
            {() =>
              h ? (
                <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
                  <ChartFrame plain title="RMS level (dBFS)">
                    {() => (
                      <TimeSeriesChart
                        compact
                        points={toPoints(h.level_dbfs)}
                        band={flatBand(h.level_dbfs)}
                        yLabel="Level (dBFS)"
                        yMin={null}
                        yFormat={(v) => formatNumber(v, 1)}
                        title="RMS level by recording"
                        description="RMS level in dBFS per recording with the deployment median band."
                        caption="RMS level by recording"
                      />
                    )}
                  </ChartFrame>
                  <ChartFrame plain title="High-band energy fraction">
                    {() => (
                      <TimeSeriesChart
                        compact
                        points={toPoints(h.high_band_fraction)}
                        band={flatBand(h.high_band_fraction)}
                        yLabel="High-band fraction"
                        yFormat={(v) => formatNumber(v, 2)}
                        title="High-band fraction by recording"
                        description="Share of energy above 4 kHz per recording with the deployment median band."
                        caption="High-band energy fraction by recording"
                      />
                    )}
                  </ChartFrame>
                </div>
              ) : (
                <LoadingState />
              )
            }
          </ChartFrame>
          <div className="grid gap-5 md:grid-cols-2">
            <ChartFrame
              eyebrow="Signal"
              title="Clipping"
              note="Fraction of samples"
              testId="clipping-chart"
            >
              {() =>
                h ? (
                  <TimeSeriesChart
                    compact
                    points={toPoints(h.clipping_fraction)}
                    yLabel="Clipping fraction"
                    yFormat={(v) => formatPercent(v, 1)}
                    thresholds={[{ value: 0.01, label: '1%', tone: 'warn' }]}
                    title="Clipping fraction by recording"
                    description="Share of clipped samples per recording."
                    caption="Clipping fraction by recording"
                  />
                ) : (
                  <LoadingState />
                )
              }
            </ChartFrame>
            <ChartFrame
              eyebrow="Schedule"
              title="Recording gaps"
              note={`Last ${days} days`}
              testId="gaps-chart"
            >
              {() =>
                h ? (
                  <GapsTimeline
                    gaps={h.gaps}
                    from={windowStart.toISOString()}
                    to={windowEnd.toISOString()}
                    caption="Recording gaps in the health window"
                  />
                ) : (
                  <LoadingState />
                )
              }
            </ChartFrame>
          </div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-12">
        <Panel className="p-5 sm:p-6 xl:col-span-7 min-w-0" labelledBy="deployments-heading">
          <SectionHeading id="deployments-heading" eyebrow="Placements">
            Deployments
          </SectionHeading>
          {mine.length ? (
            <ul className="divide-y divide-line" data-testid="deployment-list">
              {mine.map((d) => (
                <li
                  key={d.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm"
                >
                  <span className="min-w-0">
                    <a
                      className="font-medium text-ink hover:underline"
                      href={orgHref(org.id, 'site', d.site_id)}
                    >
                      {siteName(d.site_id)}
                    </a>
                    <span className="block text-xs text-muted">
                      {longDate(d.started_at.slice(0, 10))} to{' '}
                      {d.ended_at ? longDate(d.ended_at.slice(0, 10)) : 'now'}
                      {d.expected_interval_minutes
                        ? ` · every ${d.expected_interval_minutes} min`
                        : ''}
                      {d.schedule_description ? ` · ${d.schedule_description}` : ''}
                    </span>
                  </span>
                  {!d.ended_at && permissions.canManage ? (
                    <Button size="sm" variant="secondary" onClick={() => void endDeployment(d)}>
                      End deployment
                    </Button>
                  ) : d.ended_at ? (
                    <span className="text-xs text-muted">Ended</span>
                  ) : (
                    <span className="text-xs text-ok">Active</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              This recorder has not been deployed yet. Start a deployment when it goes out so health
              baselines and gap checks have a schedule to compare against.
            </p>
          )}
        </Panel>
        <Panel className="p-5 sm:p-6 xl:col-span-5 min-w-0" labelledBy="recorder-alerts-heading">
          <SectionHeading id="recorder-alerts-heading" eyebrow="Alerts">
            Open alerts
          </SectionHeading>
          {h?.open_alerts.length ? (
            <ul className="divide-y divide-line">
              {h.open_alerts.map((a) => (
                <li key={a.id} className="py-2.5">
                  <a href={orgHref(org.id, 'alerts', null, { alert: a.id })} className="block">
                    <span className="flex flex-wrap items-center gap-2">
                      <SeverityPill severity={a.severity} />
                      <span className="text-sm font-medium text-ink">{a.title}</span>
                    </span>
                    <span className="mt-1 block text-xs text-muted">
                      {kindLabel(a.kind)} · {formatDateTime(a.last_seen_at)}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Nothing open for this recorder.</p>
          )}
        </Panel>
      </div>
      {r.notes ? <Callout tone="info">{r.notes}</Callout> : null}
    </div>
  );
}

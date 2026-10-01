import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { Alert, AlertStatus, AlertUpdate } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { SiteSelect } from '../../components/platform/filters';
import { AlertStatusPill, SeverityPill } from '../../components/platform/pills';
import { CATEGORY_LABEL, kindLabel } from '../../lib/labels';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  ReadOnlyNote,
  Select,
} from '../../components/platform/primitives';
import { Button } from '../../components/ui/Button';
import { ChevronDownIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { useResource } from '../../hooks/useResource';
import { cx } from '../../lib/cx';
import { relativeTime } from '../../lib/dates';
import { formatDateTime, formatInteger, formatNumber } from '../../lib/format';
import { navigateTo, orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

const STATUS_OPTIONS: Array<{ value: AlertStatus | 'all'; label: string }> = [
  { value: 'open', label: 'Open' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'snoozed', label: 'Snoozed' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
];

const CATEGORIES: Array<Alert['category']> = ['ecology', 'quality', 'recorder'];

const EVIDENCE_LABEL: Record<string, string> = {
  observed: 'Observed',
  baseline: 'Baseline (median)',
  baseline_median: 'Baseline (median)',
  mad: 'MAD',
  baseline_mad: 'Baseline MAD',
  n: 'Comparable recordings',
  sample_size: 'Comparable recordings',
  threshold: 'Threshold',
  recordings: 'Recordings',
  consecutive: 'Consecutive recordings',
  hours: 'Hours',
  expected_recordings: 'Recordings expected',
  median_interval_minutes: 'Median interval (min)',
  presence_fraction: 'Presence fraction',
  battery_v: 'Battery (V)',
  temperature_c: 'Temperature (C)',
  level_dbfs: 'Level (dBFS)',
  high_band_fraction: 'High-band fraction',
  clipping_fraction: 'Clipping fraction',
  max_confidence: 'Max confidence',
};

function formatEvidence(value: unknown): string {
  if (typeof value === 'number')
    return Number.isInteger(value) ? formatInteger(value) : formatNumber(value, 2);
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (value === null || value === undefined) return 'n/a';
  if (Array.isArray(value)) return value.map(formatEvidence).join(', ');
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function EvidenceTable({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence);
  if (!entries.length) return null;
  return (
    <table className="w-full max-w-md text-sm" data-testid="evidence-table">
      <caption className="sr-only">Evidence behind this alert</caption>
      <tbody className="divide-y divide-line">
        {entries.map(([key, value]) => (
          <tr key={key}>
            <th scope="row" className="py-1 pr-3 text-left text-xs font-medium text-muted">
              {EVIDENCE_LABEL[key] ?? key.replace(/_/g, ' ')}
            </th>
            <td className="num py-1 text-right text-ink">{formatEvidence(value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SnoozeControl({
  onSnooze,
  disabled,
}: {
  onSnooze: (until: string) => void;
  disabled: boolean;
}) {
  const [days, setDays] = useState('7');
  return (
    <span className="inline-flex items-center gap-1.5">
      <Select
        aria-label="Snooze for"
        className="h-8 w-auto py-1 text-xs"
        value={days}
        onChange={(e) => setDays(e.target.value)}
        disabled={disabled}
      >
        <option value="1">1 day</option>
        <option value="3">3 days</option>
        <option value="7">7 days</option>
        <option value="30">30 days</option>
      </Select>
      <Button
        size="sm"
        variant="ghost"
        disabled={disabled}
        onClick={() => {
          const until = new Date(Date.now() + Number(days) * 86_400_000);
          onSnooze(until.toISOString());
        }}
      >
        Snooze
      </Button>
    </span>
  );
}

function AlertRow({
  alert,
  expanded,
  onToggle,
  onUpdate,
  canAct,
  busy,
  orgId,
  siteName,
  recorderLabel,
}: {
  alert: Alert;
  expanded: boolean;
  onToggle: () => void;
  onUpdate: (update: AlertUpdate) => void;
  canAct: boolean;
  busy: boolean;
  orgId: string;
  siteName: (id: string | null | undefined) => string;
  recorderLabel: (id: string | null | undefined) => string;
}) {
  const [note, setNote] = useState(alert.note ?? '');
  const panelId = `alert-detail-${alert.id}`;
  const links: ReactNode[] = [];
  if (alert.site_id) {
    links.push(
      <a key="site" className="link" href={orgHref(orgId, 'site', alert.site_id)}>
        {siteName(alert.site_id)}
      </a>,
    );
  }
  if (alert.recorder_id) {
    links.push(
      <a key="rec" className="link" href={orgHref(orgId, 'recorder', alert.recorder_id)}>
        {recorderLabel(alert.recorder_id)}
      </a>,
    );
  }
  if (alert.species) {
    links.push(
      <a
        key="sp"
        className="link"
        href={orgHref(orgId, 'recordings', null, {
          species: alert.species.scientific_name,
          site_id: alert.site_id,
        })}
      >
        {alert.species.common_name}{' '}
        <span className="sci text-muted">{alert.species.scientific_name}</span>
      </a>,
    );
  }

  return (
    <li className="py-3" data-testid="alert-row" data-alert-id={alert.id}>
      <div className="flex flex-wrap items-start gap-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={panelId}
          className="flex min-w-0 flex-1 items-start gap-2 rounded-lg text-left"
        >
          <ChevronDownIcon
            size={16}
            className={cx(
              'mt-0.5 shrink-0 text-subtle transition-transform',
              expanded ? 'rotate-180' : '',
            )}
          />
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <SeverityPill severity={alert.severity} />
              <span className="text-sm font-semibold text-ink">{alert.title}</span>
              {alert.status !== 'open' ? <AlertStatusPill status={alert.status} /> : null}
            </span>
            <span className="mt-1 block text-xs text-muted">
              {kindLabel(alert.kind)}
              {alert.site_id ? ` · ${siteName(alert.site_id)}` : ''}
              {alert.recorder_id ? ` · ${recorderLabel(alert.recorder_id)}` : ''}
              {' · last seen '}
              {relativeTime(alert.last_seen_at)}
              {alert.occurrences && alert.occurrences > 1
                ? ` · seen ${alert.occurrences} times`
                : ''}
            </span>
          </span>
        </button>
        {canAct ? (
          <span className="flex flex-wrap items-center gap-1.5">
            {alert.status === 'open' || alert.status === 'snoozed' ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => onUpdate({ status: 'acknowledged', note: note.trim() || null })}
              >
                Acknowledge
              </Button>
            ) : null}
            {alert.status !== 'resolved' ? (
              <Button
                size="sm"
                variant="primary"
                disabled={busy}
                onClick={() => onUpdate({ status: 'resolved', note: note.trim() || null })}
              >
                Resolve
              </Button>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onUpdate({ status: 'open' })}
              >
                Reopen
              </Button>
            )}
            {alert.status === 'open' || alert.status === 'acknowledged' ? (
              <SnoozeControl
                disabled={busy}
                onSnooze={(until) =>
                  onUpdate({ status: 'snoozed', snoozed_until: until, note: note.trim() || null })
                }
              />
            ) : null}
          </span>
        ) : null}
      </div>
      <div id={panelId} hidden={!expanded} className="ml-6 mt-3 space-y-3">
        <p className="max-w-3xl text-sm leading-relaxed text-ink">{alert.detail}</p>
        <EvidenceTable evidence={alert.evidence} />
        {alert.suggested_action ? (
          <p className="max-w-3xl rounded-xl bg-surface-muted px-3 py-2 text-sm text-ink">
            <span className="font-medium">Suggested next step: </span>
            {alert.suggested_action}
          </p>
        ) : null}
        {links.length ? <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">{links}</p> : null}
        {alert.recording_ids?.length ? (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>Recordings involved:</span>
            {alert.recording_ids.slice(0, 8).map((id) => (
              <a key={id} className="link" href={orgHref(orgId, 'recording', id)}>
                {id}
              </a>
            ))}
            {alert.recording_ids.length > 8 ? (
              <span>and {alert.recording_ids.length - 8} more</span>
            ) : null}
          </p>
        ) : null}
        <p className="text-xs text-muted">
          First seen {formatDateTime(alert.first_seen_at)}
          {alert.snoozed_until ? ` · snoozed until ${formatDateTime(alert.snoozed_until)}` : ''}
          {alert.acknowledged_by ? ` · acknowledged by ${alert.acknowledged_by}` : ''}
        </p>
        {canAct ? (
          <label className="block max-w-md text-xs text-muted">
            Note (saved with the next action)
            <textarea
              className="field-input mt-1 min-h-[3rem] text-sm"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={busy}
            />
          </label>
        ) : alert.note ? (
          <p className="text-sm text-muted">Note: {alert.note}</p>
        ) : null}
      </div>
    </li>
  );
}

export function AlertsPage({ query }: { query: URLSearchParams }) {
  const { api } = usePlatform();
  const { org, sites, permissions, siteName, recorderLabel, refreshUnread, unread } = useOrg();
  const status = (query.get('status') as AlertStatus | 'all' | null) ?? 'open';
  const siteId = query.get('site_id');
  const focus = query.get('alert');
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(focus ? [focus] : []));
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<FriendlyError | null>(null);

  const alerts = useResource(
    (signal) =>
      api.listAlerts(org.id, { status: status === 'all' ? null : status, site_id: siteId }, signal),
    `alerts:${org.id}:${status}:${siteId ?? ''}`,
  );

  useEffect(() => {
    if (focus) setExpanded((s) => new Set([...s, focus]));
  }, [focus]);

  // Opening the inbox counts as reading the in-app notifications behind the bell badge.
  useEffect(() => {
    if (unread <= 0 || api.readOnly) return;
    api
      .markNotificationsRead({ all: true, organization_id: org.id })
      .then(refreshUnread)
      .catch(() => undefined);
  }, [unread, api, refreshUnread, org.id]);

  const setQuery = (patch: Record<string, string | null | undefined>) =>
    navigateTo(orgHref(org.id, 'alerts', null, { status, site_id: siteId, ...patch }));

  const grouped = useMemo(() => {
    const items = alerts.data?.items ?? [];
    return CATEGORIES.map((category) => ({
      category,
      items: items.filter((a) => a.category === category),
    }));
  }, [alerts.data]);

  const update = async (alert: Alert, body: AlertUpdate) => {
    setBusyId(alert.id);
    setActionError(null);
    try {
      const updated = await api.updateAlert(alert.id, body);
      alerts.setData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((a) => (a.id === updated.id ? { ...a, ...updated } : a)),
            }
          : current,
      );
      refreshUnread();
    } catch (err) {
      setActionError(describeError(err));
    } finally {
      setBusyId(null);
    }
  };

  const counts = alerts.data?.counts_by_status ?? {};

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Alerts"
        description="Changes worth a look: ecology shifts against each site's own baseline, audio quality streaks and recorder health. Every alert states the observed value, the baseline and the sample size."
      />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3" data-testid="alert-filters">
        <div
          role="group"
          aria-label="Status"
          className="scrollbar-thin inline-flex max-w-full overflow-x-auto rounded-xl border border-line bg-surface-muted p-0.5"
        >
          {STATUS_OPTIONS.map((s) => (
            <button
              key={s.value}
              type="button"
              aria-pressed={status === s.value}
              onClick={() => setQuery({ status: s.value })}
              className={cx(
                'h-8 shrink-0 whitespace-nowrap rounded-[0.6rem] px-3 text-[0.8125rem] font-medium transition-colors',
                status === s.value
                  ? 'bg-raised text-ink shadow-sm ring-1 ring-black/5 dark:bg-white/10 dark:ring-white/10'
                  : 'text-muted hover:text-ink',
              )}
            >
              {s.label}
              {s.value !== 'all' && counts[s.value] != null ? (
                <span className="num ml-1 text-xs text-muted">{counts[s.value]}</span>
              ) : null}
            </button>
          ))}
        </div>
        <SiteSelect
          sites={sites.data ?? []}
          value={siteId}
          onChange={(id) => setQuery({ site_id: id })}
        />
        {!permissions.canReview ? (
          <ReadOnlyNote>Viewers can read alerts; reviewers can act on them.</ReadOnlyNote>
        ) : null}
      </div>

      {actionError ? <ErrorCallout error={actionError} /> : null}
      {alerts.error ? <ErrorState error={alerts.error} onRetry={alerts.reload} /> : null}
      {alerts.loading ? <LoadingState label="Loading alerts..." /> : null}
      {alerts.data && alerts.data.items.length === 0 ? (
        <EmptyState
          title={status === 'open' ? 'Nothing open' : 'No alerts here'}
          testId="alerts-empty"
        >
          {status === 'open'
            ? 'New alerts appear after each analysis and after the nightly checks.'
            : 'Try another status or site.'}
        </EmptyState>
      ) : null}

      {grouped.map(({ category, items }) =>
        items.length ? (
          <Panel key={category} className="p-5 sm:p-6" labelledBy={`alerts-${category}`}>
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h2
                id={`alerts-${category}`}
                className="text-base font-semibold tracking-tight text-ink"
              >
                {CATEGORY_LABEL[category]}
              </h2>
              <span className="num text-xs text-muted">{formatInteger(items.length)}</span>
            </div>
            <ul
              className={cx('divide-y divide-line', alerts.busy ? 'opacity-60' : '')}
              data-testid={`alerts-${category}`}
            >
              {items.map((a) => (
                <AlertRow
                  key={a.id}
                  alert={a}
                  expanded={expanded.has(a.id)}
                  onToggle={() =>
                    setExpanded((s) => {
                      const next = new Set(s);
                      if (next.has(a.id)) next.delete(a.id);
                      else next.add(a.id);
                      return next;
                    })
                  }
                  onUpdate={(body) => void update(a, body)}
                  canAct={permissions.canReview && !api.readOnly}
                  busy={busyId === a.id}
                  orgId={org.id}
                  siteName={siteName}
                  recorderLabel={recorderLabel}
                />
              ))}
            </ul>
          </Panel>
        ) : null,
      )}
    </div>
  );
}

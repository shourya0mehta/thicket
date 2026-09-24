import type { QualityCheck, QualityReport, QualityStatus } from '../../api/types';
import { cx } from '../../lib/cx';
import { sanitizeCopy } from '../../lib/models';
import { formatNumber, formatPercent } from '../../lib/format';
import { Badge, type BadgeTone } from '../ui/Badge';
import { AlertIcon, CheckCircleIcon, ShieldIcon, XCircleIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';

const QUALITY_LABEL: Record<QualityStatus, string> = {
  usable: 'Usable',
  usable_with_warnings: 'Usable with warnings',
  not_usable: 'Not usable',
};

const QUALITY_TONE: Record<QualityStatus, BadgeTone> = {
  usable: 'ok',
  usable_with_warnings: 'warn',
  not_usable: 'danger',
};

export function QualityBadge({ status }: { status: QualityStatus }) {
  const Icon =
    status === 'usable' ? CheckCircleIcon : status === 'not_usable' ? XCircleIcon : AlertIcon;
  return (
    <Badge tone={QUALITY_TONE[status]} icon={<Icon size={12} />}>
      Audio: {QUALITY_LABEL[status]}
    </Badge>
  );
}

function CheckRow({ check }: { check: QualityCheck }) {
  const Icon =
    check.status === 'pass' ? CheckCircleIcon : check.status === 'warn' ? AlertIcon : XCircleIcon;
  const tone =
    check.status === 'pass' ? 'text-ok' : check.status === 'warn' ? 'text-warn' : 'text-danger';
  const statusText =
    check.status === 'pass' ? 'Pass' : check.status === 'warn' ? 'Warning' : 'Fail';
  return (
    <li className="flex gap-2.5 py-2">
      <Icon size={16} className={cx('mt-0.5 shrink-0', tone)} />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-ink">
          <span className="font-medium">{humanize(check.name)}</span>
          <span className="sr-only">: {statusText}.</span>
          {check.value != null ? (
            <span className="num ml-2 text-xs text-muted">
              {formatCheckValue(check.value, check.unit)}
            </span>
          ) : null}
        </p>
        <p className="text-xs text-muted">{sanitizeCopy(check.message)}</p>
      </div>
    </li>
  );
}

const ACRONYMS: Record<string, string> = { dc: 'DC', snr: 'SNR', rms: 'RMS', lf: 'LF' };

function humanize(name: string): string {
  const words = name.replace(/[_-]+/g, ' ').trim().split(/\s+/);
  const text = words.map((w) => ACRONYMS[w.toLowerCase()] ?? w).join(' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** 0.889 fraction becomes 88.9%; 48000.0 Hz becomes 48,000 Hz. */
function formatCheckValue(value: number, unit: string | null | undefined): string {
  if (unit === 'fraction' || unit === 'probability' || unit === 'ratio') {
    return formatPercent(value, value > 0 && value < 0.01 ? 2 : 1);
  }
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) < 1 ? 3 : 1;
  const text = value.toLocaleString('en-US', { maximumFractionDigits: digits });
  return unit ? `${text} ${unit}` : text;
}

export function QualityPanel({ quality }: { quality: QualityReport | null }) {
  if (!quality) {
    return (
      <Panel labelledBy="quality-heading" className="p-5 sm:p-6">
        <p className="eyebrow mb-1">Audio quality</p>
        <h3 id="quality-heading" className="text-base font-semibold text-ink">
          Quality checks
        </h3>
        <p className="mt-2 text-sm text-muted">No quality report is available for this analysis.</p>
      </Panel>
    );
  }

  const stats: Array<[string, string]> = [
    ['Peak level', `${formatNumber(quality.peak_dbfs, 1)} dBFS`],
    ['RMS level', `${formatNumber(quality.rms_dbfs, 1)} dBFS`],
    ['Clipping', formatPercent(quality.clipping_fraction, 2)],
    ['Silence', formatPercent(quality.silence_fraction, 0)],
    ['Energy below 200 Hz', formatPercent(quality.low_frequency_energy_fraction, 0)],
  ];

  return (
    <Panel labelledBy="quality-heading" className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow mb-1">Audio quality</p>
          <h3 id="quality-heading" className="text-base font-semibold tracking-tight text-ink">
            Quality checks
          </h3>
        </div>
        <QualityBadge status={quality.status} />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <div
          className="h-2 flex-1 overflow-hidden rounded-full bg-mark/15"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(quality.score * 100)}
          aria-label="Usability score"
        >
          <div
            className={cx(
              'h-full rounded-full',
              quality.status === 'usable'
                ? 'bg-mark'
                : quality.status === 'usable_with_warnings'
                  ? 'bg-warn'
                  : 'bg-danger',
            )}
            style={{ width: `${Math.round(quality.score * 100)}%` }}
          />
        </div>
        <span className="num text-sm font-semibold text-ink">
          {Math.round(quality.score * 100)}
          <span className="text-xs font-normal text-muted"> / 100</span>
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        Heuristic usability score, not a measure of accuracy.
      </p>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        {stats.map(([term, value]) => (
          <div key={term}>
            <dt className="text-xs text-muted">{term}</dt>
            <dd className="num font-medium text-ink">{value}</dd>
          </div>
        ))}
      </dl>

      {quality.checks.length ? (
        <ul className="mt-4 divide-y divide-line border-t border-line" aria-label="Quality checks">
          {quality.checks.map((check) => (
            <CheckRow key={check.name} check={check} />
          ))}
        </ul>
      ) : null}

      {quality.warnings.length ? (
        <div className="mt-4 rounded-xl bg-warn-soft px-3.5 py-3">
          <p className="text-xs font-semibold text-warn">Warnings</p>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-ink">
            {quality.warnings.map((w) => (
              <li key={w}>{sanitizeCopy(w)}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {quality.speech_detected ? (
        <p className="mt-4 flex gap-2 rounded-xl border border-line px-3.5 py-3 text-xs text-muted">
          <ShieldIcon size={15} className="mt-px shrink-0 text-subtle" />
          <span>
            <span className="font-medium text-ink">Speech may be present.</span> Uploaded audio is
            not kept by default. If this recording captured people, delete the analysis when you are
            done.
          </span>
        </p>
      ) : null}
    </Panel>
  );
}

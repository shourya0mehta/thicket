import type {
  AlertSeverity,
  AlertStatus,
  AnalysisStatus,
  BatchItemStatus,
  QualityStatus,
  Report,
} from '../../api/generated';
import { Badge, type BadgeTone } from '../ui/Badge';
import {
  AlertIcon,
  CheckCircleIcon,
  CheckIcon,
  InfoIcon,
  MoonIcon,
  XCircleIcon,
} from '../ui/icons';

export type HealthStatus = 'good' | 'watch' | 'attention' | 'unknown';

const HEALTH: Record<HealthStatus, { label: string; tone: BadgeTone; Icon: typeof InfoIcon }> = {
  good: { label: 'Good', tone: 'ok', Icon: CheckCircleIcon },
  watch: { label: 'Watch', tone: 'warn', Icon: AlertIcon },
  attention: { label: 'Needs attention', tone: 'danger', Icon: XCircleIcon },
  unknown: { label: 'No data yet', tone: 'neutral', Icon: InfoIcon },
};

/** Health is encoded by icon and label, with color as reinforcement. */
export function HealthPill({
  status,
  prefix,
}: {
  status: HealthStatus | null | undefined;
  prefix?: string;
}) {
  const h = HEALTH[status ?? 'unknown'];
  return (
    <Badge tone={h.tone} icon={<h.Icon size={12} />}>
      {prefix ? `${prefix}: ` : ''}
      {h.label}
    </Badge>
  );
}

const SEVERITY: Record<AlertSeverity, { label: string; tone: BadgeTone; Icon: typeof InfoIcon }> = {
  info: { label: 'Info', tone: 'info', Icon: InfoIcon },
  watch: { label: 'Watch', tone: 'warn', Icon: AlertIcon },
  warning: { label: 'Warning', tone: 'danger', Icon: XCircleIcon },
};

export function SeverityPill({ severity }: { severity: AlertSeverity }) {
  const s = SEVERITY[severity];
  return (
    <Badge tone={s.tone} icon={<s.Icon size={12} />}>
      {s.label}
    </Badge>
  );
}

const ALERT_STATUS: Record<AlertStatus, { label: string; tone: BadgeTone; Icon: typeof InfoIcon }> =
  {
    open: { label: 'Open', tone: 'accent', Icon: AlertIcon },
    acknowledged: { label: 'Acknowledged', tone: 'info', Icon: CheckIcon },
    resolved: { label: 'Resolved', tone: 'ok', Icon: CheckCircleIcon },
    snoozed: { label: 'Snoozed', tone: 'neutral', Icon: MoonIcon },
  };

export function AlertStatusPill({ status }: { status: AlertStatus }) {
  const s = ALERT_STATUS[status];
  return (
    <Badge tone={s.tone} icon={<s.Icon size={12} />}>
      {s.label}
    </Badge>
  );
}

const QUALITY: Record<QualityStatus, { label: string; tone: BadgeTone; Icon: typeof InfoIcon }> = {
  usable: { label: 'Usable', tone: 'ok', Icon: CheckCircleIcon },
  usable_with_warnings: { label: 'Usable with warnings', tone: 'warn', Icon: AlertIcon },
  not_usable: { label: 'Not usable', tone: 'danger', Icon: XCircleIcon },
};

export function QualityPill({ status }: { status: QualityStatus | null | undefined }) {
  if (!status) return <Badge tone="neutral">Not analyzed</Badge>;
  const q = QUALITY[status];
  return (
    <Badge tone={q.tone} icon={<q.Icon size={12} />}>
      {q.label}
    </Badge>
  );
}

export function AnalysisStatusPill({ status }: { status: AnalysisStatus | null | undefined }) {
  if (!status) return <Badge tone="neutral">Not analyzed</Badge>;
  const tone: BadgeTone =
    status === 'completed' ? 'ok' : status === 'failed' ? 'danger' : 'neutral';
  const label =
    status === 'completed'
      ? 'Analyzed'
      : status === 'failed'
        ? 'Failed'
        : status === 'processing'
          ? 'Processing'
          : 'Queued';
  return <Badge tone={tone}>{label}</Badge>;
}

export function BatchItemPill({ status }: { status: BatchItemStatus }) {
  const map: Record<BatchItemStatus, { label: string; tone: BadgeTone }> = {
    queued: { label: 'Queued', tone: 'neutral' },
    processing: { label: 'Processing', tone: 'info' },
    completed: { label: 'Done', tone: 'ok' },
    failed: { label: 'Failed', tone: 'danger' },
    skipped: { label: 'Skipped', tone: 'warn' },
  };
  return <Badge tone={map[status].tone}>{map[status].label}</Badge>;
}

export function ReportStatusPill({ status }: { status: Report['status'] }) {
  const map: Record<Report['status'], { label: string; tone: BadgeTone }> = {
    queued: { label: 'Queued', tone: 'neutral' },
    rendering: { label: 'Rendering', tone: 'info' },
    ready: { label: 'Ready', tone: 'ok' },
    failed: { label: 'Failed', tone: 'danger' },
  };
  return <Badge tone={map[status].tone}>{map[status].label}</Badge>;
}

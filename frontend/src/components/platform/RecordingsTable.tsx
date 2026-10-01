import type { RecordingSummary } from '../../api/generated';
import { formatDate, formatDuration, formatInteger, formatTime } from '../../lib/format';
import { orgHref } from '../../lib/routes';
import { ArrowRightIcon } from '../ui/icons';
import { AnalysisStatusPill, QualityPill } from './pills';

const SOURCE_LABEL: Record<RecordingSummary['captured_at_source'], string> = {
  filename: 'from file name',
  file_metadata: 'from file metadata',
  user: 'entered by hand',
  browser_last_modified: 'from the file date',
  unknown: 'unknown',
};

export function RecordingsTable({
  rows,
  orgId,
  showSite = true,
  compact = false,
}: {
  rows: RecordingSummary[];
  orgId: string;
  showSite?: boolean;
  compact?: boolean;
}) {
  return (
    <div className="relative overflow-x-auto">
      <table
        className={`w-full text-sm ${compact ? 'min-w-[34rem]' : 'min-w-[42rem]'}`}
        data-testid="recordings-table"
      >
        <caption className="sr-only">Recordings</caption>
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            <th scope="col" className="py-2 pr-3 text-left font-medium">
              Captured
            </th>
            {showSite ? (
              <th scope="col" className="px-3 py-2 text-left font-medium">
                Site
              </th>
            ) : null}
            <th scope="col" className="px-3 py-2 text-left font-medium">
              File
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Length
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Audio
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Species
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Events
            </th>
            {!compact ? (
              <th scope="col" className="py-2 pl-3 text-right font-medium">
                <span className="sr-only">Open</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => {
            const href = orgHref(orgId, 'recording', r.id);
            return (
              <tr key={r.id} data-testid="recording-row">
                <th scope="row" className="whitespace-nowrap py-2.5 pr-3 text-left font-normal">
                  <a href={href} className="font-medium text-ink hover:underline">
                    {r.captured_at ? formatDate(r.captured_at, r.timezone) : 'Unknown time'}
                  </a>
                  {r.captured_at ? (
                    <span className="num block text-xs text-ink/80">
                      {formatTime(r.captured_at, r.timezone)}
                    </span>
                  ) : null}
                  {!compact ? (
                    <span className="block text-xs text-muted">
                      {SOURCE_LABEL[r.captured_at_source]}
                      {r.telemetry?.battery_v != null
                        ? ` · ${r.telemetry.battery_v.toFixed(1)} V`
                        : ''}
                      {r.telemetry?.temperature_c != null
                        ? ` · ${Math.round(r.telemetry.temperature_c)} C`
                        : ''}
                    </span>
                  ) : null}
                </th>
                {showSite ? (
                  <td className="px-3 py-2.5 text-ink">{r.site_name ?? 'No site'}</td>
                ) : null}
                <td className="max-w-[14rem] truncate px-3 py-2.5 text-muted" title={r.filename}>
                  {r.filename}
                </td>
                <td className="num whitespace-nowrap px-3 py-2.5 text-right text-ink">
                  {formatDuration(r.duration_seconds)}
                </td>
                <td className="px-3 py-2.5">
                  {r.analysis_status === 'completed' || r.quality_status ? (
                    <QualityPill status={r.quality_status} />
                  ) : (
                    <AnalysisStatusPill status={r.analysis_status} />
                  )}
                </td>
                <td className="num px-3 py-2.5 text-right text-ink">
                  {r.species_richness == null ? 'n/a' : formatInteger(r.species_richness)}
                </td>
                <td className="num px-3 py-2.5 text-right text-ink">
                  {r.total_detection_events == null
                    ? 'n/a'
                    : formatInteger(r.total_detection_events)}
                </td>
                {!compact ? (
                  <td className="py-2.5 pl-3 text-right">
                    <a
                      href={href}
                      className="inline-flex items-center gap-1 text-xs font-medium text-accent"
                      aria-label={`Open ${r.filename}`}
                    >
                      Open <ArrowRightIcon size={12} />
                    </a>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

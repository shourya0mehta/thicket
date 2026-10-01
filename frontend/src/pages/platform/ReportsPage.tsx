import { useEffect, useState } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { Report } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { ReportStatusPill } from '../../components/platform/pills';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  ReadOnlyNote,
} from '../../components/platform/primitives';
import { Button, ButtonLink } from '../../components/ui/Button';
import { DocumentIcon, DownloadIcon, PlusIcon, TrashIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { REPORT_POLL_INTERVAL_MS } from '../../config';
import { useResource } from '../../hooks/useResource';
import { longDate } from '../../lib/dates';
import { formatDateTime, formatInteger, shortHash } from '../../lib/format';
import { TEMPLATE_LABEL } from '../../lib/labels';
import { orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

export function ReportDownloads({ report }: { report: Report }) {
  const { api } = usePlatform();
  if (report.status !== 'ready') return null;
  const pdf = api.reportDownloadUrl(report, 'pdf');
  const json = api.reportDownloadUrl(report, 'json');
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {pdf ? (
        <ButtonLink href={pdf} size="sm" variant="primary" download data-testid="download-pdf">
          <DownloadIcon size={14} /> PDF
        </ButtonLink>
      ) : null}
      {json ? (
        <ButtonLink href={json} size="sm" variant="secondary" download data-testid="download-json">
          <DownloadIcon size={14} /> JSON bundle
        </ButtonLink>
      ) : null}
    </span>
  );
}

export function ReportsPage() {
  const { api } = usePlatform();
  const { org, permissions, siteName } = useOrg();
  const reports = useResource((signal) => api.listReports(org.id, signal), `reports:${org.id}`);
  const [error, setError] = useState<FriendlyError | null>(null);
  const items = reports.data?.items ?? [];
  const pending = items.some((r) => r.status === 'queued' || r.status === 'rendering');

  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(reports.reload, REPORT_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [pending, reports.reload]);

  const remove = async (report: Report) => {
    if (!window.confirm(`Delete "${report.title}"? The PDF and its JSON bundle are removed.`))
      return;
    setError(null);
    try {
      await api.deleteReport(report.id);
      reports.setData((current) =>
        current ? { items: current.items.filter((r) => r.id !== report.id) } : current,
      );
    } catch (err) {
      setError(describeError(err));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Reports"
        description="PDF packages built from your analyses for planners, certifiers and your own files. Every page states the analysis ids, software version and the checksum of its data bundle."
        actions={
          permissions.canReview && !api.readOnly ? (
            <ButtonLink href={orgHref(org.id, 'report_new')} variant="primary" size="sm">
              <PlusIcon size={14} /> New report
            </ButtonLink>
          ) : null
        }
      />
      {error ? <ErrorCallout error={error} /> : null}
      {reports.error ? <ErrorState error={reports.error} onRetry={reports.reload} /> : null}
      {reports.loading ? <LoadingState label="Loading reports..." /> : null}
      {reports.data && items.length === 0 ? (
        <EmptyState
          title="No reports yet"
          action={
            permissions.canReview && !api.readOnly ? (
              <ButtonLink href={orgHref(org.id, 'report_new')} variant="primary" size="sm">
                <DocumentIcon size={14} /> Build the first report
              </ButtonLink>
            ) : null
          }
          testId="reports-empty"
        >
          Pick a template, a period and the sites it should cover. Thicket fills in every number and
          you add what it cannot know, such as who prepared it.
          {!permissions.canReview ? (
            <ReadOnlyNote>Reviewers and above can build reports.</ReadOnlyNote>
          ) : null}
        </EmptyState>
      ) : null}
      {items.length ? (
        <Panel className="p-5 sm:p-6" label="Reports list">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[44rem] text-sm" data-testid="reports-table">
              <caption className="sr-only">Reports for {org.name}</caption>
              <thead className="border-b border-line text-xs text-muted">
                <tr>
                  <th scope="col" className="py-2 pr-3 text-left font-medium">
                    Report
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    Period
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Analyses
                  </th>
                  <th scope="col" className="py-2 pl-3 text-right font-medium">
                    Files
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((r) => (
                  <tr key={r.id} data-testid="report-row">
                    <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                      <span className="block font-medium text-ink">{r.title}</span>
                      <span className="block text-xs text-muted">
                        {TEMPLATE_LABEL[r.template]} · created {formatDateTime(r.created_at)}
                        {r.site_ids.length
                          ? ` · ${r.site_ids.map(siteName).join(', ')}`
                          : ' · all sites'}
                      </span>
                      {r.status === 'ready' && r.checksum_sha256 ? (
                        <span className="num block text-xs text-muted">
                          {r.page_count ? `${r.page_count} pages · ` : ''}bundle{' '}
                          {shortHash(r.checksum_sha256)}
                        </span>
                      ) : null}
                      {r.status === 'failed' && r.error_message ? (
                        <span className="block text-xs text-danger">{r.error_message}</span>
                      ) : null}
                      {r.missing_fields?.length ? (
                        <span className="block text-xs text-warn">
                          Left blank: {r.missing_fields.join(', ')}
                        </span>
                      ) : null}
                    </th>
                    <td className="px-3 py-2.5 text-muted">
                      {longDate(r.period_start.slice(0, 10))} to{' '}
                      {longDate(r.period_end.slice(0, 10))}
                    </td>
                    <td className="px-3 py-2.5">
                      <ReportStatusPill status={r.status} />
                    </td>
                    <td className="num px-3 py-2.5 text-right">
                      {formatInteger(r.analysis_count)}
                    </td>
                    <td className="py-2.5 pl-3 text-right">
                      <span className="inline-flex items-center gap-1.5">
                        <ReportDownloads report={r} />
                        {permissions.canManage && !api.readOnly ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={`Delete ${r.title}`}
                            onClick={() => void remove(r)}
                          >
                            <TrashIcon size={14} />
                          </Button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

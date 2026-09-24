import { useEffect, useMemo, useState } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import { API_SCHEMA_VERSION, type Analysis } from '../../api/types';
import { analysisToCsv, analysisToExportJson, exportFilename } from '../../lib/csv';
import { exportUrls } from '../../lib/exports';
import { thresholdPercent } from '../../lib/threshold';
import { Button, ButtonLink } from '../ui/Button';
import { DownloadIcon, TrashIcon } from '../ui/icons';
import { Panel } from '../ui/Panel';

function useBlobUrl(content: string | null, type: string): string | null {
  const url = useMemo(
    () => (content === null ? null : URL.createObjectURL(new Blob([content], { type }))),
    [content, type],
  );
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

export function ExportBar({
  analysis,
  clientSide,
  onDelete,
}: {
  analysis: Analysis;
  /** Demo mode: build files in the browser from the loaded analysis. */
  clientSide: boolean;
  onDelete?: () => Promise<void>;
}) {
  const threshold = analysis.settings.decision_threshold;
  const csvText = useMemo(
    () => (clientSide ? analysisToCsv(analysis) : null),
    [clientSide, analysis],
  );
  const jsonText = useMemo(
    () => (clientSide ? analysisToExportJson(analysis, API_SCHEMA_VERSION) : null),
    [clientSide, analysis],
  );
  const csvBlob = useBlobUrl(csvText, 'text/csv');
  const jsonBlob = useBlobUrl(jsonText, 'application/json');
  const server = clientSide ? null : exportUrls(analysis);
  const csvHref = clientSide ? csvBlob : server?.csv;
  const jsonHref = clientSide ? jsonBlob : server?.json;

  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<FriendlyError | null>(null);

  const doDelete = async () => {
    if (!onDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete();
    } catch (error) {
      setDeleteError(describeError(error));
      setDeleting(false);
    }
  };

  return (
    <Panel labelledBy="export-heading" className="px-5 py-4 sm:px-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 lg:max-w-xl">
          <h2 id="export-heading" className="text-base font-semibold tracking-tight text-ink">
            Export at {thresholdPercent(threshold)}
          </h2>
          <p className="mt-0.5 text-sm text-muted">
            CSV has one row per detection event. JSON is the full analysis with provenance. Both use
            the decision threshold shown on this page.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:shrink-0 lg:flex-nowrap">
          {csvHref ? (
            <ButtonLink
              href={csvHref}
              download={exportFilename(analysis, 'csv')}
              variant="primary"
              data-testid="export-csv"
            >
              <DownloadIcon size={16} />
              Download CSV
            </ButtonLink>
          ) : null}
          {jsonHref ? (
            <ButtonLink
              href={jsonHref}
              download={exportFilename(analysis, 'json')}
              variant="secondary"
              data-testid="export-json"
            >
              <DownloadIcon size={16} />
              Download JSON
            </ButtonLink>
          ) : null}
          {onDelete ? (
            confirming ? (
              <span className="flex flex-wrap items-center gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3 py-1.5">
                <span className="text-sm text-ink">Delete this analysis from the server?</span>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => void doDelete()}
                  disabled={deleting}
                >
                  {deleting ? 'Deleting...' : 'Delete'}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirming(false)}
                  disabled={deleting}
                >
                  Keep
                </Button>
              </span>
            ) : (
              <Button variant="ghost" onClick={() => setConfirming(true)}>
                <TrashIcon size={16} />
                Delete from server
              </Button>
            )
          ) : null}
        </div>
      </div>
      {deleteError ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {deleteError.title}. {deleteError.body}
        </p>
      ) : null}
    </Panel>
  );
}

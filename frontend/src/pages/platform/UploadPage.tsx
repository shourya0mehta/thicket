import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { ApiError, isAbortError } from '../../api/client';
import { describeError, type FriendlyError } from '../../api/errors';
import type { BatchJob } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { ModelSelector } from '../../components/intake/ModelSelector';
import { BatchItemPill } from '../../components/platform/pills';
import {
  EmptyState,
  Field,
  LoadingState,
  PageHeader,
  ReadOnlyNote,
  SectionHeading,
  Select,
  TextInput,
} from '../../components/platform/primitives';
import { Badge, type BadgeTone } from '../../components/ui/Badge';
import { Button, ButtonLink } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { TrashIcon, UploadIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import {
  BATCH_POLL_INTERVAL_MS,
  DEFAULT_THRESHOLD,
  MAX_BATCH_BYTES,
  MAX_BATCH_FILES,
  experimentalModelsEnabled,
} from '../../config';
import { useModels } from '../../hooks/useModels';
import { useResource } from '../../hooks/useResource';
import {
  classifyUploadFile,
  describeTimestamp,
  parseFilenameTimestamp,
  type UploadFileKind,
} from '../../lib/filenames';
import { formatBytes, formatDateTime, formatInteger } from '../../lib/format';
import {
  COMBINED_SELECTION,
  defaultSelection,
  isSelectable,
  modelsForSelection,
} from '../../lib/models';
import { orgHref } from '../../lib/routes';
import { thresholdPercent } from '../../lib/threshold';
import { isValidTimeZone, timeZoneOptions, zonedLocalToIso } from '../../lib/validation';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

interface Picked {
  id: string;
  file: File;
  kind: UploadFileKind;
}

const KIND_TONE: Record<UploadFileKind, { label: string; tone: BadgeTone }> = {
  audio: { label: 'Audio', tone: 'ok' },
  zip: { label: 'Archive', tone: 'info' },
  sidecar: { label: 'Recorder log', tone: 'neutral' },
  unsupported: { label: 'Unsupported', tone: 'danger' },
};

const THRESHOLDS = Array.from({ length: 18 }, (_, i) => (i + 1) * 0.05);

let pickCounter = 0;

function isTerminal(job: BatchJob): boolean {
  return (
    job.status === 'completed' || job.status === 'completed_with_errors' || job.status === 'failed'
  );
}

/** Consecutive failed polls tolerated before the page gives up (network blips, restarts). */
const MAX_POLL_FAILURES = 5;

/** Errors that will not go away by asking again. */
function isFinalPollError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.code === 'unauthenticated' || err.code === 'forbidden' || err.code === 'not_found')
  );
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer);
        const e = new Error('Aborted');
        e.name = 'AbortError';
        reject(e);
      },
      { once: true },
    );
  });
}

export function UploadPage({ query }: { query: URLSearchParams }) {
  const { api, demo } = usePlatform();
  const { org, sites, recorders, permissions } = useOrg();
  const experimental = experimentalModelsEnabled();
  const modelsState = useModels(!demo);
  const inputRef = useRef<HTMLInputElement>(null);

  const [picked, setPicked] = useState<Picked[]>([]);
  const [dragging, setDragging] = useState(false);
  const [siteId, setSiteId] = useState(query.get('site_id') ?? '');
  const [deploymentId, setDeploymentId] = useState('');
  const [recorderId, setRecorderId] = useState('');
  const [timezone, setTimezone] = useState(org.timezone);
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [override, setOverride] = useState('');
  const [selection, setSelection] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'processing' | 'done' | 'failed'>(
    'idle',
  );
  const [progress, setProgress] = useState(0);
  const [job, setJob] = useState<BatchJob | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const ctrl = useRef<AbortController | null>(null);

  const deployments = useResource(
    (signal) => api.listDeployments(org.id, { active: true }, signal),
    `active-deployments:${org.id}`,
  );
  const history = useResource(
    (signal) => api.listBatchJobs(org.id, 10, signal),
    `batches:${org.id}:${job?.id ?? ''}:${phase}`,
  );

  useEffect(() => {
    if (modelsState.status !== 'ready') return;
    const visible = modelsState.models.filter((m) => experimental || !m.experimental);
    const stillValid =
      selection === COMBINED_SELECTION
        ? experimental
        : visible.some((m) => m.key === selection && isSelectable(m));
    if (!stillValid) setSelection(defaultSelection(visible));
  }, [modelsState.status, modelsState.models, selection, experimental]);

  useEffect(() => () => ctrl.current?.abort(), []);

  const siteDeployments = (deployments.data ?? []).filter((d) => !siteId || d.site_id === siteId);
  useEffect(() => {
    if (deploymentId && !siteDeployments.some((d) => d.id === deploymentId)) setDeploymentId('');
  }, [deploymentId, siteDeployments]);
  useEffect(() => {
    const dep = siteDeployments.find((d) => d.id === deploymentId);
    if (dep) setRecorderId(dep.recorder_id);
  }, [deploymentId, siteDeployments]);

  const addFiles = (files: FileList | File[]) => {
    const list = Array.from(files);
    setPicked((current) => {
      const seen = new Set(current.map((p) => `${p.file.name}:${p.file.size}`));
      const next = [...current];
      for (const file of list) {
        const key = `${file.name}:${file.size}`;
        if (seen.has(key)) continue;
        seen.add(key);
        next.push({ id: `f${++pickCounter}`, file, kind: classifyUploadFile(file.name) });
      }
      return next;
    });
    setFormError(null);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
  };

  const totals = useMemo(() => {
    const payload = picked.filter((p) => p.kind !== 'unsupported');
    return {
      count: payload.length,
      bytes: payload.reduce((a, p) => a + p.file.size, 0),
      audio: picked.filter((p) => p.kind === 'audio').length,
      zips: picked.filter((p) => p.kind === 'zip').length,
      sidecars: picked.filter((p) => p.kind === 'sidecar').length,
      unsupported: picked.filter((p) => p.kind === 'unsupported').length,
      withTimestamp: picked.filter(
        (p) => p.kind === 'audio' && parseFilenameTimestamp(p.file.name).localTimestamp,
      ).length,
    };
  }, [picked]);

  const models = modelsForSelection(selection, modelsState.models);

  const start = async () => {
    const payload = picked.filter((p) => p.kind !== 'unsupported').map((p) => p.file);
    if (!payload.some((f) => classifyUploadFile(f.name) !== 'sidecar')) {
      setFormError('Add at least one audio file or zip archive.');
      return;
    }
    if (!siteId) {
      setFormError('Choose the site these recordings come from.');
      return;
    }
    if (!isValidTimeZone(timezone)) {
      setFormError('Use an IANA time zone such as America/Chicago.');
      return;
    }
    if (payload.length > MAX_BATCH_FILES) {
      setFormError(`A batch can hold at most ${MAX_BATCH_FILES} files. Split it up.`);
      return;
    }
    if (totals.bytes > MAX_BATCH_BYTES) {
      setFormError(`A batch can hold at most ${formatBytes(MAX_BATCH_BYTES)}. Split it up.`);
      return;
    }
    if (!models.length) {
      setFormError('Choose a model that is ready on this server.');
      return;
    }
    setFormError(null);
    setError(null);
    setJob(null);
    setProgress(0);
    setPhase('uploading');
    const controller = new AbortController();
    ctrl.current?.abort();
    ctrl.current = controller;
    let accepted: BatchJob;
    try {
      accepted = await api.createBatchUpload(
        org.id,
        {
          files: payload,
          siteId,
          deploymentId: deploymentId || null,
          recorderId: recorderId || null,
          timezone: timezone.trim(),
          models,
          threshold,
          // The override is wall-clock time in the chosen zone, like the recorder's clock.
          capturedAtOverride: override ? zonedLocalToIso(override, timezone.trim()) : null,
        },
        (fraction) => setProgress(fraction),
        controller.signal,
      );
    } catch (err) {
      if (isAbortError(err)) return;
      setError(describeError(err));
      setPhase('failed');
      return;
    }
    if (controller.signal.aborted) return;
    setJob(accepted);
    await follow(accepted, controller);
  };

  /**
   * Polls an accepted job to the end. The files are on the server by now, so a
   * failed poll must never lead back to `start` (that uploads every file again
   * and duplicates the recordings): blips are retried here, and the Retry
   * button resumes polling the same job.
   */
  const follow = async (accepted: BatchJob, controller: AbortController) => {
    setError(null);
    setPhase(isTerminal(accepted) ? 'done' : 'processing');
    let current = accepted;
    let failures = 0;
    try {
      while (!isTerminal(current)) {
        await pause(BATCH_POLL_INTERVAL_MS, controller.signal);
        try {
          current = await api.getBatchJob(accepted.id, controller.signal);
          failures = 0;
        } catch (err) {
          if (isAbortError(err) || isFinalPollError(err)) throw err;
          failures += 1;
          if (failures >= MAX_POLL_FAILURES) throw err;
          continue;
        }
        if (controller.signal.aborted) return;
        setJob(current);
      }
      setPhase('done');
      setPicked([]);
      sites.reload();
    } catch (err) {
      if (isAbortError(err)) return;
      setError(describeError(err));
      setPhase('failed');
    }
  };

  const resume = () => {
    if (!job) return;
    const controller = new AbortController();
    ctrl.current?.abort();
    ctrl.current = controller;
    void follow(job, controller);
  };

  const cancel = () => {
    ctrl.current?.abort();
    setPhase('idle');
  };

  if (!permissions.canManage) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow={org.name} title="Upload recordings" />
        <EmptyState title="Uploads need the manager role">
          <ReadOnlyNote>
            Viewers and reviewers can browse recordings but not add them. Ask an owner or manager to
            upload, or to change your role.
          </ReadOnlyNote>
        </EmptyState>
      </div>
    );
  }

  const busy = phase === 'uploading' || phase === 'processing';

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Upload recordings"
        description="Drop a whole recorder card: audio files, zip archives, AudioMoth CONFIG.TXT and Song Meter summary logs. Each file is analyzed and filed under the site you choose."
      />

      <div className="grid gap-5 xl:grid-cols-12">
        <Panel className="p-5 sm:p-6 xl:col-span-7 min-w-0" label="Files">
          <SectionHeading
            eyebrow="1. Files"
            note={picked.length ? `${formatInteger(picked.length)} chosen` : undefined}
          >
            Choose files
          </SectionHeading>
          <div
            role="presentation"
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
              dragging ? 'border-mark bg-mark/5' : 'border-line-strong'
            }`}
            data-testid="drop-zone"
          >
            <UploadIcon size={22} className="text-subtle" />
            <p className="text-sm text-ink">Drag files or folders here</p>
            <p className="text-xs text-muted">
              .wav .flac .mp3 .m4a, .zip, *_Summary.txt, CONFIG.TXT · up to {MAX_BATCH_FILES} files
              or {formatBytes(MAX_BATCH_BYTES)}
            </p>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
            >
              Choose files
            </Button>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".wav,.flac,.mp3,.m4a,.zip,.txt,audio/*,application/zip"
              className="sr-only"
              data-testid="batch-input"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </div>

          {picked.length ? (
            <>
              <div
                className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted"
                data-testid="batch-summary"
              >
                <span>{formatInteger(totals.audio)} audio</span>
                <span>{formatInteger(totals.zips)} archives</span>
                <span>{formatInteger(totals.sidecars)} recorder logs</span>
                {totals.unsupported ? (
                  <span className="text-danger">
                    {formatInteger(totals.unsupported)} unsupported (skipped)
                  </span>
                ) : null}
                <span>{formatBytes(totals.bytes)}</span>
                <span>
                  {formatInteger(totals.withTimestamp)} of {formatInteger(totals.audio)} names carry
                  a timestamp
                </span>
              </div>
              <div className="relative mt-3 max-h-[26rem] overflow-auto">
                <table className="w-full text-sm" data-testid="batch-preview">
                  <caption className="sr-only">
                    Chosen files and the timestamp read from each name
                  </caption>
                  <thead className="sticky top-0 bg-raised text-xs text-muted">
                    <tr>
                      <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                        File
                      </th>
                      <th scope="col" className="px-3 py-1.5 text-left font-medium">
                        Kind
                      </th>
                      <th scope="col" className="px-3 py-1.5 text-left font-medium">
                        Time in name
                      </th>
                      <th scope="col" className="py-1.5 pl-3 text-right font-medium">
                        <span className="sr-only">Remove</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {picked.map((p) => {
                      const parsed =
                        p.kind === 'audio' ? parseFilenameTimestamp(p.file.name) : null;
                      return (
                        <tr key={p.id} data-testid="batch-row">
                          <td className="max-w-[16rem] py-2 pr-3">
                            <span className="block truncate text-ink" title={p.file.name}>
                              {p.file.name}
                            </span>
                            <span className="block text-xs text-muted">
                              {formatBytes(p.file.size)}
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            <Badge tone={KIND_TONE[p.kind].tone}>{KIND_TONE[p.kind].label}</Badge>
                          </td>
                          <td className="px-3 py-2">
                            {parsed ? (
                              <>
                                <span
                                  className="num block text-ink"
                                  data-testid="timestamp-preview"
                                >
                                  {describeTimestamp(parsed)}
                                </span>
                                <span className="block text-xs text-muted">{parsed.note}</span>
                              </>
                            ) : p.kind === 'zip' ? (
                              <span className="text-xs text-muted">
                                Contents are read on the server
                              </span>
                            ) : p.kind === 'sidecar' ? (
                              <span className="text-xs text-muted">
                                Matched to recordings by time
                              </span>
                            ) : (
                              <span className="text-xs text-danger">
                                Not an audio, zip or log file
                              </span>
                            )}
                          </td>
                          <td className="py-2 pl-3 text-right">
                            <Button
                              size="sm"
                              variant="ghost"
                              aria-label={`Remove ${p.file.name}`}
                              disabled={busy}
                              onClick={() => setPicked((c) => c.filter((x) => x.id !== p.id))}
                            >
                              <TrashIcon size={14} />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-muted">
                The server decides the final capture time: file name first, then file metadata, then
                the file date from your browser, then your override.
              </p>
            </>
          ) : null}
        </Panel>

        <Panel className="p-5 sm:p-6 xl:col-span-5 min-w-0" label="Settings">
          <SectionHeading eyebrow="2. Where and how">Settings</SectionHeading>
          <div className="space-y-4">
            <Field
              label="Site"
              required
              hint={sites.data?.length ? undefined : 'Create a site first.'}
            >
              {(props) => (
                <Select
                  {...props}
                  value={siteId}
                  onChange={(e) => setSiteId(e.target.value)}
                  disabled={busy}
                >
                  <option value="">Choose a site</option>
                  {(sites.data ?? []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {!sites.data?.length && sites.data ? (
              <ButtonLink
                href={orgHref(org.id, 'sites', null, { new: '1' })}
                size="sm"
                variant="secondary"
              >
                Add a site
              </ButtonLink>
            ) : null}
            <Field
              label="Deployment"
              hint="Links the files to a recorder placement for health checks."
            >
              {(props) => (
                <Select
                  {...props}
                  value={deploymentId}
                  onChange={(e) => setDeploymentId(e.target.value)}
                  disabled={busy || !siteDeployments.length}
                >
                  <option value="">
                    {siteDeployments.length ? 'None' : 'No active deployment at this site'}
                  </option>
                  {siteDeployments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {(recorders.data ?? []).find((r) => r.id === d.recorder_id)?.label ??
                        d.recorder_id}{' '}
                      · since {formatDateTime(d.started_at)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Recorder" hint="Optional when no deployment is chosen.">
              {(props) => (
                <Select
                  {...props}
                  value={recorderId}
                  onChange={(e) => setRecorderId(e.target.value)}
                  disabled={busy || Boolean(deploymentId)}
                >
                  <option value="">None</option>
                  {(recorders.data ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field
              label="Time zone"
              required
              hint="For names that carry local time (Song Meter, ISO)."
            >
              {(props) => (
                <>
                  <TextInput
                    {...props}
                    list={`${props.id}-zones`}
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    disabled={busy}
                    autoComplete="off"
                  />
                  <datalist id={`${props.id}-zones`}>
                    {timeZoneOptions().map((z) => (
                      <option key={z} value={z} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
            <Field
              label="Decision threshold"
              hint="Recorded with each analysis; you can review at other thresholds later."
            >
              {(props) => (
                <Select
                  {...props}
                  className="num"
                  value={threshold.toFixed(2)}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  disabled={busy}
                >
                  {THRESHOLDS.map((t) => (
                    <option key={t.toFixed(2)} value={t.toFixed(2)}>
                      {thresholdPercent(t)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field
              label="Capture time override"
              hint="In the time zone above. Only used when a file has no timestamp anywhere."
            >
              {(props) => (
                <TextInput
                  {...props}
                  type="datetime-local"
                  value={override}
                  onChange={(e) => setOverride(e.target.value)}
                  disabled={busy}
                />
              )}
            </Field>
            {!demo ? (
              <ModelSelector
                modelsState={modelsState}
                selection={selection}
                onSelect={setSelection}
                experimentalEnabled={experimental}
              />
            ) : null}
          </div>

          {formError ? (
            <p
              className="mt-4 text-sm font-medium text-danger"
              role="alert"
              data-testid="batch-form-error"
            >
              {formError}
            </p>
          ) : null}
          {error ? (
            <ErrorCallout
              className="mt-4"
              error={error}
              // Once the server accepted the batch, retrying means checking on it again.
              onRetry={job ? resume : () => void start()}
            />
          ) : null}

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              onClick={() => void start()}
              disabled={busy || demo || !picked.length}
              data-testid="start-batch"
            >
              <UploadIcon size={15} />
              {phase === 'uploading'
                ? `Uploading ${Math.round(progress * 100)}%`
                : phase === 'processing'
                  ? 'Analyzing...'
                  : `Upload ${totals.count ? formatInteger(totals.count) : ''} files`}
            </Button>
            {busy ? (
              <Button variant="ghost" onClick={cancel}>
                Stop following
              </Button>
            ) : null}
          </div>
          {demo ? <p className="mt-2 text-xs text-muted">Uploads are off in the demo.</p> : null}
          {phase === 'uploading' ? (
            <div
              className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-muted"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress * 100)}
              aria-label="Upload progress"
            >
              <div
                className="h-full rounded-full bg-mark transition-[width]"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          ) : null}
        </Panel>
      </div>

      {job ? <BatchJobPanel job={job} orgId={org.id} live={phase === 'processing'} /> : null}

      <Panel className="p-5 sm:p-6" labelledBy="batch-history-heading">
        <SectionHeading id="batch-history-heading" eyebrow="History">
          Recent batches
        </SectionHeading>
        {history.data?.length ? (
          <ul className="divide-y divide-line text-sm">
            {history.data.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="text-ink">
                  {formatDateTime(b.created_at)} · {formatInteger(b.total)} files
                  {b.site_id
                    ? ` · ${(sites.data ?? []).find((s) => s.id === b.site_id)?.name ?? b.site_id}`
                    : ''}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted">
                  <span className="num">
                    {formatInteger(b.done)} done · {formatInteger(b.failed)} failed ·{' '}
                    {formatInteger(b.skipped)} skipped
                  </span>
                  <BatchStatusPill status={b.status} />
                </span>
              </li>
            ))}
          </ul>
        ) : history.loading ? (
          <LoadingState />
        ) : (
          <p className="text-sm text-muted">No batches yet.</p>
        )}
      </Panel>
    </div>
  );
}

function BatchStatusPill({ status }: { status: BatchJob['status'] }) {
  const map: Record<BatchJob['status'], { label: string; tone: BadgeTone }> = {
    queued: { label: 'Queued', tone: 'neutral' },
    processing: { label: 'Processing', tone: 'info' },
    completed: { label: 'Completed', tone: 'ok' },
    completed_with_errors: { label: 'Completed with errors', tone: 'warn' },
    failed: { label: 'Failed', tone: 'danger' },
  };
  return <Badge tone={map[status].tone}>{map[status].label}</Badge>;
}

export function BatchJobPanel({
  job,
  orgId,
  live,
}: {
  job: BatchJob;
  orgId: string;
  live: boolean;
}) {
  const finished = job.done + job.failed + job.skipped;
  const pct = job.total ? Math.round((finished / job.total) * 100) : 0;
  return (
    <Panel className="p-5 sm:p-6" labelledBy="batch-job-heading" aria-live="polite">
      <SectionHeading
        id="batch-job-heading"
        eyebrow={live ? 'Processing' : 'Result'}
        note={<BatchStatusPill status={job.status} />}
      >
        Batch {job.id}
      </SectionHeading>
      <div
        className="mb-3 h-1.5 overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Files processed"
      >
        <div
          className="h-full rounded-full bg-mark transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-sm text-muted" data-testid="batch-progress">
        {formatInteger(finished)} of {formatInteger(job.total)} files finished ·{' '}
        {formatInteger(job.done)} done · {formatInteger(job.failed)} failed ·{' '}
        {formatInteger(job.skipped)} skipped
        {job.sidecars_parsed?.length ? ` · logs read: ${job.sidecars_parsed.join(', ')}` : ''}
      </p>
      <div className="relative mt-3 overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm" data-testid="batch-items">
          <caption className="sr-only">Files in this batch</caption>
          <thead className="border-b border-line text-xs text-muted">
            <tr>
              <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                File
              </th>
              <th scope="col" className="px-3 py-1.5 text-left font-medium">
                Status
              </th>
              <th scope="col" className="px-3 py-1.5 text-left font-medium">
                Capture time
              </th>
              <th scope="col" className="px-3 py-1.5 text-left font-medium">
                Telemetry
              </th>
              <th scope="col" className="py-1.5 pl-3 text-left font-medium">
                Result
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {job.items.map((item, i) => (
              <tr key={`${item.filename}-${i}`} data-testid="batch-item">
                <td className="max-w-[16rem] truncate py-2 pr-3 text-ink" title={item.filename}>
                  {item.filename}
                </td>
                <td className="px-3 py-2">
                  <BatchItemPill status={item.status} />
                </td>
                <td className="px-3 py-2 text-muted">
                  {item.captured_at ? (
                    <>
                      <span className="num block text-ink">{formatDateTime(item.captured_at)}</span>
                      <span className="block text-xs">
                        {(item.captured_at_source ?? 'unknown').replace(/_/g, ' ')}
                      </span>
                    </>
                  ) : (
                    'Unknown'
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-muted">
                  {item.telemetry && item.telemetry.source && item.telemetry.source !== 'none' ? (
                    <>
                      {item.telemetry.battery_v != null
                        ? `${item.telemetry.battery_v.toFixed(2)} V `
                        : ''}
                      {item.telemetry.temperature_c != null
                        ? `${item.telemetry.temperature_c.toFixed(1)} C `
                        : ''}
                      <span className="block">{item.telemetry.source.replace(/_/g, ' ')}</span>
                    </>
                  ) : (
                    'None'
                  )}
                </td>
                <td className="py-2 pl-3">
                  {item.status === 'failed' || item.status === 'skipped' ? (
                    <span className="text-xs text-danger">
                      {item.error_message ?? item.error_code ?? 'No detail'}
                    </span>
                  ) : item.recording_id ? (
                    <a
                      className="link text-xs"
                      href={orgHref(orgId, 'recording', item.recording_id)}
                    >
                      Open recording
                    </a>
                  ) : (
                    <span className="text-xs text-muted">Waiting</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!live ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <ButtonLink
            href={orgHref(orgId, 'recordings', null, { site_id: job.site_id })}
            size="sm"
            variant="secondary"
          >
            See the recordings
          </ButtonLink>
          <ButtonLink
            href={orgHref(orgId, 'dashboard', null, { site_id: job.site_id })}
            size="sm"
            variant="ghost"
          >
            Dashboard
          </ButtonLink>
        </div>
      ) : null}
      {job.status === 'completed_with_errors' ? (
        <Callout tone="warn" className="mt-4">
          Some files failed. The reasons are in the Result column; fix the files and upload them
          again.
        </Callout>
      ) : null}
    </Panel>
  );
}

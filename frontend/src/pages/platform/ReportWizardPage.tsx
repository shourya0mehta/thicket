import { useEffect, useMemo, useRef, useState } from 'react';
import { isAbortError } from '../../api/client';
import { describeError, type FriendlyError } from '../../api/errors';
import type { Report, ReportField, ReportTemplate, ReportTemplateKey } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { ReportStatusPill } from '../../components/platform/pills';
import {
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  Select,
  TextInput,
} from '../../components/platform/primitives';
import { Button, ButtonLink } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { ArrowRightIcon, CheckIcon, ChevronLeftIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { REPORT_POLL_INTERVAL_MS } from '../../config';
import { useResource } from '../../hooks/useResource';
import { cx } from '../../lib/cx';
import { periodForPreset } from '../../lib/dates';
import { formatInteger } from '../../lib/format';
import {
  buildReportCreate,
  fieldError,
  groupFields,
  placeholderFor,
  scopeErrors,
  type RawValues,
  type WizardScope,
} from '../../lib/reportFields';
import { TEMPLATE_LABEL } from '../../lib/labels';
import { orgHref } from '../../lib/routes';
import { thresholdPercent } from '../../lib/threshold';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';
import { ReportDownloads } from './ReportsPage';

type Step = 'template' | 'scope' | 'fields' | 'submit';
const STEPS: Array<{ id: Step; label: string }> = [
  { id: 'template', label: 'Template' },
  { id: 'scope', label: 'Period and sites' },
  { id: 'fields', label: 'Details' },
  { id: 'submit', label: 'Build' },
];
const THRESHOLDS = Array.from({ length: 18 }, (_, i) => (i + 1) * 0.05);

function Stepper({ current }: { current: Step }) {
  const index = STEPS.findIndex((s) => s.id === current);
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs" aria-label="Steps">
      {STEPS.map((s, i) => {
        const state = i < index ? 'done' : i === index ? 'current' : 'todo';
        return (
          <li
            key={s.id}
            className="flex items-center gap-2"
            aria-current={state === 'current' ? 'step' : undefined}
          >
            <span
              className={cx(
                'inline-flex h-5 w-5 items-center justify-center rounded-full text-[0.6875rem] font-semibold',
                state === 'done'
                  ? 'bg-forest-600 text-white'
                  : state === 'current'
                    ? 'bg-mark/15 text-accent ring-1 ring-mark/40'
                    : 'bg-surface-muted text-muted',
              )}
            >
              {state === 'done' ? <CheckIcon size={12} strokeWidth={2.5} /> : i + 1}
            </span>
            <span className={state === 'current' ? 'font-semibold text-ink' : 'text-muted'}>
              {s.label}
            </span>
            {i < STEPS.length - 1 ? (
              <span className="mx-1 text-subtle" aria-hidden="true">
                /
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function FieldInput({
  field,
  value,
  onChange,
  error,
  orgId,
}: {
  field: ReportField;
  value: string | boolean | undefined;
  onChange: (next: string | boolean) => void;
  error: string | null;
  orgId: string;
}) {
  const { api } = usePlatform();
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<FriendlyError | null>(null);
  const label = field.label || field.name.replace(/_/g, ' ');
  const text = typeof value === 'string' ? value : '';
  const placeholder = placeholderFor(field);
  const hint =
    field.help ??
    (placeholder && field.type !== 'boolean'
      ? `For example: ${placeholder.split('\n')[0]}`
      : undefined);

  if (field.type === 'boolean') {
    return (
      <Checkbox
        label={
          <>
            {label}
            {field.required ? <span className="ml-1 text-danger">*</span> : null}
          </>
        }
        hint={field.help ?? undefined}
        checked={value === true || value === 'true'}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={`field-${field.name}`}
      />
    );
  }

  return (
    <Field label={label} required={field.required} hint={hint} error={error}>
      {(props) => {
        if (field.type === 'text' || field.type === 'list') {
          return (
            <textarea
              {...props}
              className="field-input min-h-[4.5rem]"
              value={text}
              placeholder={field.type === 'list' ? 'One per line' : undefined}
              onChange={(e) => onChange(e.target.value)}
              data-testid={`field-${field.name}`}
            />
          );
        }
        if (field.type === 'enum') {
          return (
            <Select
              {...props}
              value={text}
              onChange={(e) => onChange(e.target.value)}
              data-testid={`field-${field.name}`}
            >
              <option value="">Choose</option>
              {(field.options ?? []).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </Select>
          );
        }
        if (field.type === 'file') {
          return (
            <div>
              <input
                {...props}
                type="file"
                accept="image/png,image/jpeg,.geojson,.json"
                className="block w-full text-sm text-muted file:mr-3 file:rounded-lg file:border file:border-line-strong file:bg-raised file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink"
                disabled={uploading || api.readOnly}
                data-testid={`field-${field.name}`}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setUploading(true);
                  setUploadError(null);
                  try {
                    const uploaded = await api.uploadOrgFile(orgId, file);
                    onChange(uploaded.id);
                  } catch (err) {
                    setUploadError(describeError(err));
                  } finally {
                    setUploading(false);
                  }
                }}
              />
              {text ? <p className="mt-1 text-xs text-muted">Uploaded file id: {text}</p> : null}
              {uploading ? <p className="mt-1 text-xs text-muted">Uploading...</p> : null}
              {uploadError ? <p className="mt-1 text-xs text-danger">{uploadError.title}</p> : null}
            </div>
          );
        }
        const type =
          field.type === 'date'
            ? 'date'
            : field.type === 'datetime'
              ? 'datetime-local'
              : field.type === 'number' || field.type === 'integer'
                ? 'text'
                : 'text';
        return (
          <TextInput
            {...props}
            type={type}
            inputMode={field.type === 'number' || field.type === 'integer' ? 'decimal' : undefined}
            className={field.type === 'number' || field.type === 'integer' ? 'num' : undefined}
            value={text}
            onChange={(e) => onChange(e.target.value)}
            data-testid={`field-${field.name}`}
          />
        );
      }}
    </Field>
  );
}

export function ReportWizardPage() {
  const { api, me } = usePlatform();
  const { org, sites, permissions } = useOrg();
  const templates = useResource((signal) => api.getReportTemplates(signal), 'report-templates');
  const [step, setStep] = useState<Step>('template');
  const [templateKey, setTemplateKey] = useState<ReportTemplateKey | null>(null);
  const defaultPeriod = useMemo(() => periodForPreset('90'), []);
  const [scope, setScope] = useState<WizardScope>({
    template: 'evidence',
    title: '',
    periodStart: defaultPeriod.from,
    periodEnd: defaultPeriod.to,
    siteIds: [],
    baselineStart: '',
    baselineEnd: '',
    threshold: null,
    includeReviewLog: true,
    includeRawManifest: false,
  });
  const [raw, setRaw] = useState<RawValues>({});
  const [showErrors, setShowErrors] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const ctrl = useRef<AbortController | null>(null);

  useEffect(() => () => ctrl.current?.abort(), []);

  const template: ReportTemplate | null =
    templates.data?.templates.find((t) => t.key === templateKey) ?? null;
  const groups = useMemo(() => (template ? groupFields(template) : []), [template]);
  const allFields = useMemo(() => groups.flatMap((g) => g.fields), [groups]);
  const errorsByField = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const f of allFields) map[f.name] = fieldError(f, raw[f.name]);
    return map;
  }, [allFields, raw]);
  const missingRequired = allFields.filter((f) => f.required && errorsByField[f.name]);
  const scopeErr = scopeErrors(scope);

  const chooseTemplate = (key: ReportTemplateKey) => {
    setTemplateKey(key);
    setScope((s) => ({
      ...s,
      template: key,
      title: s.title || `${TEMPLATE_LABEL[key]}, ${org.name}`,
    }));
    setStep('scope');
  };

  const submit = async () => {
    if (!template) return;
    setSubmitting(true);
    setError(null);
    const controller = new AbortController();
    ctrl.current?.abort();
    ctrl.current = controller;
    try {
      let current = await api.createReport(org.id, buildReportCreate(scope, template, raw));
      setReport(current);
      setStep('submit');
      while (current.status === 'queued' || current.status === 'rendering') {
        await new Promise<void>((resolve, reject) => {
          const timer = window.setTimeout(resolve, REPORT_POLL_INTERVAL_MS);
          controller.signal.addEventListener(
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
        current = await api.getReport(current.id, controller.signal);
        if (controller.signal.aborted) return;
        setReport(current);
      }
    } catch (err) {
      if (isAbortError(err)) return;
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!permissions.canReview || api.readOnly) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow={org.name} title="New report" />
        <EmptyState title="Reports need the reviewer role">
          {api.readOnly
            ? 'Reports are off in the demo.'
            : 'Ask an owner or manager to change your role.'}
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <a href={orgHref(org.id, 'reports')} className="hover:underline">
            Reports
          </a>
        }
        title="New report"
        description="Four steps: pick a template, choose the period and sites, add the details Thicket cannot know, then build."
      />
      <Stepper current={step} />

      {step === 'template' ? (
        <section aria-labelledby="step-template">
          <h2 id="step-template" className="sr-only">
            Choose a template
          </h2>
          {templates.error ? (
            <ErrorState error={templates.error} onRetry={templates.reload} />
          ) : null}
          {templates.loading ? <LoadingState label="Loading templates..." /> : null}
          {templates.data ? (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="template-cards">
              {templates.data.templates.map((t) => (
                <li key={t.key}>
                  <button
                    type="button"
                    onClick={() => chooseTemplate(t.key)}
                    className="flex h-full w-full flex-col rounded-2xl border border-line-strong bg-raised p-4 text-left transition-colors hover:border-mark/60"
                    data-testid={`template-${t.key}`}
                  >
                    <span className="text-base font-semibold text-ink">{t.title}</span>
                    <span className="mt-0.5 text-xs text-muted">For: {t.audience}</span>
                    <span className="mt-2 text-sm text-muted">{t.description}</span>
                    <span className="mt-3 text-xs font-medium text-ink">
                      {formatInteger(t.pages.length)} pages
                    </span>
                    <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-xs text-muted">
                      {t.pages.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ol>
                    <span className="mt-auto inline-flex items-center gap-1 pt-3 text-xs font-medium text-accent">
                      Use this template <ArrowRightIcon size={12} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {step === 'scope' && template ? (
        <Panel className="p-5 sm:p-6" label="Period and sites">
          <p className="eyebrow mb-1">{template.title}</p>
          <h2 className="text-base font-semibold text-ink">What the report covers</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field
              label="Title"
              required
              error={showErrors ? scopeErr.title : null}
              className="sm:col-span-2"
            >
              {(props) => (
                <TextInput
                  {...props}
                  value={scope.title}
                  onChange={(e) => setScope((s) => ({ ...s, title: e.target.value }))}
                  data-testid="report-title"
                />
              )}
            </Field>
            <Field label="Period start" required error={showErrors ? scopeErr.periodStart : null}>
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  value={scope.periodStart}
                  onChange={(e) => setScope((s) => ({ ...s, periodStart: e.target.value }))}
                />
              )}
            </Field>
            <Field label="Period end" required>
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  value={scope.periodEnd}
                  onChange={(e) => setScope((s) => ({ ...s, periodEnd: e.target.value }))}
                />
              )}
            </Field>
            <Field
              label="Baseline period start"
              hint="Optional. A same-season earlier period for the comparison pages."
              error={showErrors ? scopeErr.baselineStart : null}
            >
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  value={scope.baselineStart}
                  onChange={(e) => setScope((s) => ({ ...s, baselineStart: e.target.value }))}
                />
              )}
            </Field>
            <Field label="Baseline period end" hint="Optional.">
              {(props) => (
                <TextInput
                  {...props}
                  type="date"
                  value={scope.baselineEnd}
                  onChange={(e) => setScope((s) => ({ ...s, baselineEnd: e.target.value }))}
                />
              )}
            </Field>
            <Field
              label="Decision threshold"
              hint="Blank keeps each analysis at its recorded threshold."
              error={showErrors ? scopeErr.threshold : null}
            >
              {(props) => (
                <Select
                  {...props}
                  className="num"
                  value={scope.threshold === null ? '' : scope.threshold.toFixed(2)}
                  onChange={(e) =>
                    setScope((s) => ({
                      ...s,
                      threshold: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                >
                  <option value="">As recorded</option>
                  {THRESHOLDS.map((t) => (
                    <option key={t.toFixed(2)} value={t.toFixed(2)}>
                      {thresholdPercent(t)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div>
              <p className="field-label">Sites</p>
              <div className="space-y-1.5" data-testid="site-checklist">
                {(sites.data ?? []).map((s) => (
                  <Checkbox
                    key={s.id}
                    label={s.name}
                    checked={scope.siteIds.includes(s.id)}
                    onChange={(e) =>
                      setScope((sc) => ({
                        ...sc,
                        siteIds: e.target.checked
                          ? [...sc.siteIds, s.id]
                          : sc.siteIds.filter((id) => id !== s.id),
                      }))
                    }
                  />
                ))}
              </div>
              <p className="field-hint">Leave all unticked to include every site.</p>
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Checkbox
                label="Include the review log"
                hint="Each reviewed event with the reviewer's label and note."
                checked={scope.includeReviewLog}
                onChange={(e) => setScope((s) => ({ ...s, includeReviewLog: e.target.checked }))}
              />
              <Checkbox
                label="Include the raw file manifest"
                hint="Every file with its hash, size and duration in the provenance appendix."
                checked={scope.includeRawManifest}
                onChange={(e) => setScope((s) => ({ ...s, includeRawManifest: e.target.checked }))}
              />
            </div>
          </div>
          <div className="mt-6 flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => setStep('template')}>
              <ChevronLeftIcon size={14} /> Template
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setShowErrors(true);
                if (Object.keys(scopeErr).length === 0) {
                  setShowErrors(false);
                  // Prefill what the wizard already knows; every value stays editable.
                  const known: Record<string, string> = {
                    report_title: scope.title.trim(),
                    organization_name: org.name,
                    preparer_name: me?.user.name ?? '',
                    attestation_name: me?.user.name ?? '',
                  };
                  setRaw((current) => {
                    const next = { ...current };
                    for (const f of allFields) {
                      const value = known[f.name];
                      if (value && (next[f.name] === undefined || next[f.name] === '')) {
                        next[f.name] = value;
                      }
                    }
                    return next;
                  });
                  setStep('fields');
                }
              }}
              data-testid="to-fields"
            >
              Details <ArrowRightIcon size={14} />
            </Button>
          </div>
        </Panel>
      ) : null}

      {step === 'fields' && template ? (
        <div className="space-y-5">
          {groups.map((g) => (
            <Panel key={g.group} className="p-5 sm:p-6" labelledBy={`group-${g.group}`}>
              <h2 id={`group-${g.group}`} className="text-base font-semibold text-ink">
                {g.label}
              </h2>
              <p className="mb-4 mt-0.5 text-xs text-muted">
                {g.fields.filter((f) => f.required).length
                  ? `${formatInteger(g.fields.filter((f) => f.required).length)} required`
                  : 'All optional'}
              </p>
              <div className="grid gap-4 sm:grid-cols-2" data-testid={`group-${g.group}`}>
                {g.fields.map((f) => (
                  <div
                    key={f.name}
                    className={f.type === 'text' || f.type === 'list' ? 'sm:col-span-2' : ''}
                  >
                    <FieldInput
                      field={f}
                      value={raw[f.name]}
                      onChange={(v) => setRaw((r) => ({ ...r, [f.name]: v }))}
                      error={showErrors ? (errorsByField[f.name] ?? null) : null}
                      orgId={org.id}
                    />
                  </div>
                ))}
              </div>
            </Panel>
          ))}
          {!groups.length ? (
            <Callout tone="info">This template has no extra fields.</Callout>
          ) : null}
          {showErrors && missingRequired.length ? (
            <Callout tone="warn" role="alert" title="Some required details are missing">
              {missingRequired.map((f) => f.label || f.name).join(', ')}. You can still build the
              report; blank required fields are listed on it as missing.
            </Callout>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => setStep('scope')}>
              <ChevronLeftIcon size={14} /> Period and sites
            </Button>
            <Button
              variant="primary"
              disabled={submitting}
              onClick={() => {
                // First click with blanks shows what is missing; the next one builds anyway.
                const blocking = allFields.some(
                  (f) =>
                    errorsByField[f.name] &&
                    errorsByField[f.name] !== 'Required for this template.',
                );
                if (!showErrors && (missingRequired.length || blocking)) {
                  setShowErrors(true);
                  return;
                }
                setShowErrors(true);
                if (blocking) return;
                void submit();
              }}
              data-testid="build-report"
            >
              {submitting
                ? 'Building...'
                : showErrors && missingRequired.length
                  ? 'Build with blanks'
                  : 'Build report'}
            </Button>
          </div>
          {error ? <ErrorCallout error={error} onRetry={() => void submit()} /> : null}
        </div>
      ) : null}

      {step === 'submit' ? (
        <Panel className="p-5 sm:p-6" label="Report status" aria-live="polite">
          {report ? (
            <div className="space-y-4" data-testid="report-result">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-base font-semibold text-ink">{report.title}</h2>
                <ReportStatusPill status={report.status} />
              </div>
              {report.status === 'queued' || report.status === 'rendering' ? (
                <LoadingState label="Rendering the PDF. This usually takes under a minute." />
              ) : null}
              {report.status === 'ready' ? (
                <>
                  <p className="text-sm text-muted">
                    {formatInteger(report.analysis_count)} analyses
                    {report.page_count ? ` · ${report.page_count} pages` : ''}
                    {report.checksum_sha256
                      ? ` · PDF sha256 ${report.checksum_sha256.slice(0, 12)}`
                      : ''}
                  </p>
                  <ReportDownloads report={report} />
                </>
              ) : null}
              {report.status === 'failed' ? (
                <Callout tone="danger" role="alert" title="The report could not be rendered">
                  {report.error_message ?? 'No detail was given.'}
                </Callout>
              ) : null}
              {report.missing_fields?.length ? (
                <Callout tone="warn" title="Left blank">
                  {report.missing_fields.join(', ')}
                </Callout>
              ) : null}
              {report.warnings?.length ? (
                <Callout tone="info" title="Notes from the renderer">
                  <ul className="list-disc pl-5">
                    {report.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </Callout>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <ButtonLink href={orgHref(org.id, 'reports')} variant="secondary" size="sm">
                  All reports
                </ButtonLink>
                {report.status === 'failed' ? (
                  <Button size="sm" variant="ghost" onClick={() => setStep('fields')}>
                    Back to details
                  </Button>
                ) : null}
              </div>
            </div>
          ) : (
            <LoadingState />
          )}
          {error ? <ErrorCallout error={error} /> : null}
        </Panel>
      ) : null}
    </div>
  );
}

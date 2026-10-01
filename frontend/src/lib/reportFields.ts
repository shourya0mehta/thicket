import type {
  ReportCreate,
  ReportField,
  ReportTemplate,
  ReportTemplateKey,
} from '../api/generated';

export const GROUP_LABEL: Record<string, string> = {
  identity: 'Who and what',
  location: 'Property and location',
  deployment: 'Recorders and deployment',
  review: 'Review and validation',
  nrcs: 'NRCS contract',
  aem: 'AEM evaluation',
  certification: 'Certification program',
  credit: 'Credit project',
  statements: 'Statements and attestation',
};

export const GROUP_ORDER = [
  'identity',
  'location',
  'deployment',
  'review',
  'nrcs',
  'aem',
  'certification',
  'credit',
  'statements',
];

export function groupLabel(group: string): string {
  return GROUP_LABEL[group] ?? group.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

export interface FieldGroup {
  group: string;
  label: string;
  fields: ReportField[];
}

/** Fields of a template grouped in the documented order, keeping field order within a group. */
export function groupFields(template: ReportTemplate): FieldGroup[] {
  const map = new Map<string, ReportField[]>();
  for (const field of template.fields) {
    if (field.templates.length && !field.templates.includes(template.key)) continue;
    map.set(field.group, [...(map.get(field.group) ?? []), field]);
  }
  const known = GROUP_ORDER.filter((g) => map.has(g));
  const extra = [...map.keys()].filter((g) => !GROUP_ORDER.includes(g)).sort();
  return [...known, ...extra].map((group) => ({
    group,
    label: groupLabel(group),
    fields: map.get(group)!,
  }));
}

/** Raw form state: strings for every input type except booleans. */
export type RawValues = Record<string, string | boolean | undefined>;

export function placeholderFor(field: ReportField): string {
  const ex = field.example;
  if (ex === undefined || ex === null) return '';
  const one = (v: unknown): string =>
    typeof v === 'string'
      ? v
      : typeof v === 'number' || typeof v === 'boolean'
        ? String(v)
        : JSON.stringify(v);
  if (Array.isArray(ex)) return ex.map(one).join('\n');
  return one(ex);
}

/** Turns one raw input into the value the API expects, or null when empty. */
export function coerceFieldValue(field: ReportField, raw: string | boolean | undefined): unknown {
  if (field.type === 'boolean') return raw === true || raw === 'true';
  const text = typeof raw === 'string' ? raw.trim() : '';
  if (!text) return null;
  switch (field.type) {
    case 'number':
    case 'integer': {
      const n = Number(text);
      if (!Number.isFinite(n)) return null;
      return field.type === 'integer' ? Math.round(n) : n;
    }
    case 'list':
      return text
        .split(/\r?\n|,/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => {
          if (s.startsWith('{') && s.endsWith('}')) {
            try {
              return JSON.parse(s) as unknown;
            } catch {
              return s;
            }
          }
          return s;
        });
    case 'datetime': {
      const d = new Date(text);
      return Number.isNaN(d.getTime()) ? text : d.toISOString();
    }
    default:
      return text;
  }
}

export function fieldError(field: ReportField, raw: string | boolean | undefined): string | null {
  const value = coerceFieldValue(field, raw);
  const text = typeof raw === 'string' ? raw.trim() : '';
  if (
    field.required &&
    (value === null || value === '' || (Array.isArray(value) && !value.length))
  ) {
    return 'Required for this template.';
  }
  if ((field.type === 'number' || field.type === 'integer') && text && value === null) {
    return 'Enter a number.';
  }
  if (field.type === 'integer' && text && !/^[-+]?\d+$/.test(text)) {
    return 'Enter a whole number.';
  }
  if (field.type === 'date' && text && !/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return 'Use the date picker (YYYY-MM-DD).';
  }
  if (field.type === 'enum' && text && field.options && !field.options.includes(text)) {
    return 'Choose one of the listed options.';
  }
  return null;
}

/** Only non-empty values are sent, so the server can tell "blank" from "false". */
export function collectFieldValues(fields: ReportField[], raw: RawValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    const value = coerceFieldValue(field, raw[field.name]);
    if (field.type === 'boolean') {
      if (raw[field.name] !== undefined) out[field.name] = value;
      continue;
    }
    if (value !== null && value !== '') out[field.name] = value;
  }
  return out;
}

export interface WizardScope {
  template: ReportTemplateKey;
  title: string;
  periodStart: string;
  periodEnd: string;
  siteIds: string[];
  baselineStart: string;
  baselineEnd: string;
  threshold: number | null;
  includeReviewLog: boolean;
  includeRawManifest: boolean;
}

export function scopeErrors(scope: WizardScope): Partial<Record<keyof WizardScope, string>> {
  const errors: Partial<Record<keyof WizardScope, string>> = {};
  if (!scope.title.trim()) errors.title = 'Give the report a title.';
  if (!scope.periodStart || !scope.periodEnd)
    errors.periodStart = 'Choose the period the report covers.';
  else if (scope.periodStart > scope.periodEnd)
    errors.periodStart = 'The period must start before it ends.';
  const hasBaseline = Boolean(scope.baselineStart || scope.baselineEnd);
  if (hasBaseline && (!scope.baselineStart || !scope.baselineEnd)) {
    errors.baselineStart = 'Give both ends of the baseline period, or clear both.';
  } else if (hasBaseline && scope.baselineStart > scope.baselineEnd) {
    errors.baselineStart = 'The baseline must start before it ends.';
  }
  if (scope.threshold !== null && (scope.threshold < 0.1 || scope.threshold > 0.95)) {
    errors.threshold = 'Thresholds run from 10% to 95%.';
  }
  return errors;
}

export function buildReportCreate(
  scope: WizardScope,
  template: ReportTemplate,
  raw: RawValues,
): ReportCreate {
  return {
    template: scope.template,
    title: scope.title.trim(),
    period_start: scope.periodStart,
    period_end: scope.periodEnd,
    site_ids: scope.siteIds,
    baseline_start: scope.baselineStart || null,
    baseline_end: scope.baselineEnd || null,
    decision_threshold: scope.threshold,
    include_review_log: scope.includeReviewLog,
    include_raw_manifest: scope.includeRawManifest,
    fields: collectFieldValues(template.fields, raw),
  };
}

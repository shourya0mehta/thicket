import type { Analysis } from '../api/types';

/**
 * Client-side exports for demo mode. They mirror
 * backend/thicket/services/exports.py exactly: same columns and order, one row
 * per event in API order, "\n" line endings, formula-safe text cells and
 * Python float formatting.
 */
export const CSV_COLUMNS = [
  'analysis_id',
  'recording_filename',
  'site_name',
  'latitude',
  'longitude',
  'captured_at',
  'timezone',
  'taxon',
  'common_name',
  'scientific_name',
  'event_id',
  'start_seconds',
  'end_seconds',
  'max_confidence',
  'mean_confidence',
  'n_windows',
  'model',
  'model_version',
  'model_run_id',
  'decision_threshold',
  'plausibility',
  'review_status',
] as const;

type Cell = string | number | null | undefined;

/** Columns the backend writes as Python floats (so 3 is written as "3.0"). */
const FLOAT_COLUMNS: ReadonlySet<string> = new Set([
  'latitude',
  'longitude',
  'start_seconds',
  'end_seconds',
  'max_confidence',
  'mean_confidence',
  'decision_threshold',
]);

const FORMULA_START = /^[=+\-@\t\r]/;
const NEEDS_QUOTES = /[",\r\n]/;

export function csvCell(value: Cell, float = false): string {
  if (value === null || value === undefined) return '';
  let text: string;
  if (typeof value === 'number') {
    text = float && Number.isInteger(value) ? value.toFixed(1) : String(value);
  } else {
    // Defuse spreadsheet formulas in text cells.
    text = FORMULA_START.test(value) ? `'${value}` : value;
  }
  return NEEDS_QUOTES.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** One row per detection event at the analysis's applied decision threshold. */
export function analysisToCsv(analysis: Analysis): string {
  const runs = new Map(analysis.model_runs.map((r) => [r.id, r]));
  const rec = analysis.recording;
  const rows = analysis.events.map((event) => {
    const run = runs.get(event.model_run_id);
    const cells: Cell[] = [
      analysis.id,
      rec?.filename,
      rec?.site_name,
      rec?.latitude,
      rec?.longitude,
      rec?.captured_at,
      rec?.timezone,
      event.taxon,
      event.common_name,
      event.scientific_name,
      event.id,
      event.start_seconds,
      event.end_seconds,
      event.max_confidence,
      event.mean_confidence,
      event.n_windows,
      run?.model,
      run?.version,
      event.model_run_id,
      analysis.settings.decision_threshold,
      event.plausibility ?? 'unknown',
      event.review_status ?? 'unreviewed',
    ];
    return cells.map((cell, i) => csvCell(cell, FLOAT_COLUMNS.has(CSV_COLUMNS[i] ?? ''))).join(',');
  });
  return [CSV_COLUMNS.join(','), ...rows].join('\n') + '\n';
}

/** Same note the backend attaches to export.json. */
export const EXPORT_NOTE =
  'Metrics are based on acoustic detection events and do not estimate individual abundance. ' +
  'Species, events and metrics come from consolidated detection events at or above the ' +
  'decision threshold. Events excluded from metrics (rejected in review, unlikely for the ' +
  'location and date, or non-wildlife sounds) are listed with their status.';

/** Client-side equivalent of the backend AnalysisExport. */
export function analysisToExportJson(analysis: Analysis, schemaVersion: string): string {
  return JSON.stringify(
    {
      ...analysis,
      export_metadata: {
        exported_at: new Date().toISOString(),
        software_version: analysis.software_version,
        schema_version: schemaVersion,
        decision_threshold: analysis.settings.decision_threshold,
        note: EXPORT_NOTE,
      },
    },
    null,
    2,
  );
}

/** Backend download name, e.g. thicket_an_123_t0.60.csv. */
export function exportFilename(analysis: Analysis, ext: 'csv' | 'json'): string {
  return `thicket_${analysis.id}_t${analysis.settings.decision_threshold.toFixed(2)}.${ext}`;
}

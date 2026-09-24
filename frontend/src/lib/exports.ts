import { resolveApiUrl, withThreshold } from '../api/client';
import type { Analysis } from '../api/types';

/** Server export URLs for the analysis, pinned to its applied decision threshold. */
export function exportUrls(analysis: Analysis): { csv: string | null; json: string | null } {
  const threshold = analysis.settings.decision_threshold;
  const csv = resolveApiUrl(analysis.assets.csv_url);
  const json = resolveApiUrl(analysis.assets.json_url);
  return {
    csv: csv ? withThreshold(csv, threshold) : null,
    json: json ? withThreshold(json, threshold) : null,
  };
}

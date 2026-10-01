import type { ModelInfo } from '../api/types';

export const COMBINED_SELECTION = 'combined';

export interface ModelDisplay {
  title: string;
  subtitle: string;
  description: string;
}

/** UI copy avoids em and en dashes; model names from the server may contain them. */
export function sanitizeCopy(text: string): string {
  return text.replace(/\s*[—–]\s*/g, ' · ').trim();
}

function versionLabel(version: string): string {
  const v = version.trim();
  if (/^\d/.test(v)) return `v${v}`;
  if (/^v\d/i.test(v)) return v;
  return `Version: ${v}`;
}

export function modelDisplay(model: ModelInfo): ModelDisplay {
  if (model.key === 'birdnet') {
    return {
      title: 'Birds and more',
      subtitle: `BirdNET ${versionLabel(model.version)}`,
      description:
        'Stable model for about 6,500 bird species. It also recognizes some North American frogs and insects; every detection is labeled with its taxon.',
    };
  }
  const parts = model.name.split(/\s*[—–:]\s*/);
  const title = parts[0]?.trim() || model.key;
  const subtitle = parts.slice(1).join(' · ').trim() || versionLabel(model.version);
  return { title, subtitle, description: sanitizeCopy(model.description) };
}

/** Short name for stage labels, e.g. "Running BirdNET". */
export function modelShortName(key: string, models: ModelInfo[] = []): string {
  if (key === 'birdnet') return 'BirdNET';
  const model = models.find((m) => m.key === key);
  return model ? modelDisplay(model).title : key;
}

export function isSelectable(model: ModelInfo): boolean {
  return model.status === 'ready';
}

export function modelStatusText(model: ModelInfo): string | null {
  switch (model.status) {
    case 'ready':
      return null;
    case 'loading':
      return 'Loading on the server. Try again in a moment.';
    case 'unavailable':
      return model.unavailable_reason
        ? sanitizeCopy(model.unavailable_reason)
        : 'Not available on this server.';
    case 'disabled':
      return model.unavailable_reason
        ? sanitizeCopy(model.unavailable_reason)
        : 'Disabled on this server.';
    default:
      return null;
  }
}

/** Experimental models are hidden when the build sets VITE_ENABLE_EXPERIMENTAL_MODELS=false. */
export function visibleModels(models: ModelInfo[], experimentalEnabled: boolean): ModelInfo[] {
  const filtered = models.filter((m) => experimentalEnabled || !m.experimental);
  // Stable models first, then experimental; keep server order within each group.
  return [...filtered.filter((m) => !m.experimental), ...filtered.filter((m) => m.experimental)];
}

export function defaultSelection(models: ModelInfo[], experimentalEnabled = false): string | null {
  // With the frog and insect head ready, run both models: the server counts
  // each shared species once (see docs/DECISIONS.md, combined mode).
  if (canOfferCombined(models, experimentalEnabled)) return COMBINED_SELECTION;
  const birdnet = models.find((m) => m.key === 'birdnet' && isSelectable(m));
  if (birdnet) return birdnet.key;
  const stable = models.find((m) => !m.experimental && isSelectable(m));
  if (stable) return stable.key;
  return models.find(isSelectable)?.key ?? null;
}

/** Keys sent to the API for a selection ("combined" means every ready visible model). */
export function modelsForSelection(selection: string | null, models: ModelInfo[]): string[] {
  if (!selection) return [];
  if (selection === COMBINED_SELECTION) return models.filter(isSelectable).map((m) => m.key);
  return [selection];
}

export function canOfferCombined(models: ModelInfo[], experimentalEnabled: boolean): boolean {
  return experimentalEnabled && models.filter(isSelectable).length > 1;
}

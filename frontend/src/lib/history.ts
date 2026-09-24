import type { Analysis } from '../api/types';
import { HISTORY_KEY, HISTORY_LIMIT } from '../config';
import { topSpeciesNames } from './analysis';
import { readStorage, writeStorage } from './storage';

/** A local summary only. Audio is never stored; results live on the Thicket server. */
export interface HistoryEntry {
  id: string;
  filename: string | null;
  site: string | null;
  created_at: string;
  richness: number | null;
  top_species: string[];
}

function isEntry(value: unknown): value is HistoryEntry {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === 'string' &&
    typeof v.created_at === 'string' &&
    (v.filename === null || typeof v.filename === 'string') &&
    (v.site === null || typeof v.site === 'string') &&
    (v.richness === null || typeof v.richness === 'number') &&
    Array.isArray(v.top_species) &&
    v.top_species.every((s) => typeof s === 'string')
  );
}

export function readHistory(): HistoryEntry[] {
  const raw = readStorage(HISTORY_KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isEntry).slice(0, HISTORY_LIMIT) : [];
  } catch {
    return [];
  }
}

function writeHistory(entries: HistoryEntry[]): HistoryEntry[] {
  const trimmed = entries.slice(0, HISTORY_LIMIT);
  writeStorage(HISTORY_KEY, JSON.stringify(trimmed));
  return trimmed;
}

export function entryFromAnalysis(analysis: Analysis): HistoryEntry {
  return {
    id: analysis.id,
    filename: analysis.recording?.filename ?? null,
    site: analysis.recording?.site_name ?? null,
    created_at: analysis.created_at,
    richness: analysis.metrics?.species_richness ?? null,
    top_species: topSpeciesNames(analysis, 3),
  };
}

export function addToHistory(entry: HistoryEntry): HistoryEntry[] {
  const rest = readHistory().filter((e) => e.id !== entry.id);
  return writeHistory([entry, ...rest]);
}

export function removeFromHistory(id: string): HistoryEntry[] {
  return writeHistory(readHistory().filter((e) => e.id !== id));
}

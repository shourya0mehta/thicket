/**
 * View helpers over one Analysis. These only group and filter what the server
 * returned for the applied decision threshold; they never recompute metrics.
 */
import type {
  Analysis,
  DetectionEvent,
  ModelRun,
  RecordingInfo,
  SpeciesSummary,
  Taxon,
} from '../api/types';
import { isBiodiversityTaxon } from './taxa';

export function isUnlikely(item: { plausibility?: string | null }): boolean {
  return item.plausibility === 'unlikely';
}

/**
 * Species that count toward metrics. The server's species table is built from
 * the counted event set only, so it is used as is.
 */
export function countedSpecies(analysis: Analysis): SpeciesSummary[] {
  return analysis.species;
}

/** Left out of the metrics because of a review (rejected, or corrected to an unknown label). */
export function isExcludedByReview(event: DetectionEvent): boolean {
  return (
    !event.counted_in_metrics &&
    (event.review_status === 'rejected' || event.review_status === 'corrected')
  );
}

/** A reviewer corrected the event to another label the models know; it counts under that one. */
export function isRelabeled(event: DetectionEvent): boolean {
  return (
    event.review_status === 'corrected' && event.scientific_name !== event.detected_scientific_name
  );
}

/**
 * Wildlife events for the events table: the counted ones plus those a
 * reviewer took out, so the review can be seen and undone. Membership comes
 * from the server's counted_in_metrics flag; nothing is re-derived here.
 */
export function listedEvents(analysis: Analysis): DetectionEvent[] {
  return analysis.events
    .filter((e) => isBiodiversityTaxon(e.taxon) && (e.counted_in_metrics || isExcludedByReview(e)))
    .slice()
    .sort(
      (a, b) => a.start_seconds - b.start_seconds || a.common_name.localeCompare(b.common_name),
    );
}

/** "Corrected to Purple Finch": the species it now counts as, else the reviewer's text. */
export function correctedCopy(event: DetectionEvent): string {
  const to = isRelabeled(event) ? event.common_name : event.reviewed_label;
  return to ? `Corrected to ${to}` : 'Corrected';
}

export function isRejected(event: DetectionEvent): boolean {
  return event.review_status === 'rejected';
}

export interface EventGroup {
  scientificName: string;
  commonName: string;
  taxon: Taxon;
  events: DetectionEvent[];
  windows: number;
  maxConfidence: number;
}

function groupEvents(events: DetectionEvent[], key: (e: DetectionEvent) => string): EventGroup[] {
  const groups = new Map<string, EventGroup>();
  for (const event of events) {
    const k = key(event);
    let group = groups.get(k);
    if (!group) {
      group = {
        scientificName: event.scientific_name,
        commonName: event.common_name,
        taxon: event.taxon,
        events: [],
        windows: 0,
        maxConfidence: 0,
      };
      groups.set(k, group);
    }
    group.events.push(event);
    group.windows += event.n_windows;
    group.maxConfidence = Math.max(group.maxConfidence, event.max_confidence);
  }
  return [...groups.values()].sort(
    (a, b) =>
      b.events.length - a.events.length ||
      b.windows - a.windows ||
      a.commonName.localeCompare(b.commonName),
  );
}

/**
 * Wildlife detected above threshold but not counted because it is outside the
 * expected range or season (and no reviewer accepted or corrected it).
 */
export function unlikelyGroups(analysis: Analysis): EventGroup[] {
  return groupEvents(
    analysis.events.filter(
      (e) =>
        !e.counted_in_metrics &&
        isBiodiversityTaxon(e.taxon) &&
        isUnlikely(e) &&
        !isExcludedByReview(e),
    ),
    (e) => e.scientific_name,
  );
}

/** Human voices, engines, wind and similar labels. Never counted as species. */
export function otherSoundGroups(analysis: Analysis): EventGroup[] {
  return groupEvents(
    analysis.events.filter((e) => !e.counted_in_metrics && !isBiodiversityTaxon(e.taxon)),
    (e) => `${e.taxon}|${e.common_name}`,
  );
}

/** Wildlife events above the threshold that do not count (rejected, corrected away or unlikely). */
export function excludedWildlifeCount(analysis: Analysis): number {
  return analysis.events.filter((e) => !e.counted_in_metrics && isBiodiversityTaxon(e.taxon))
    .length;
}

export function hasValidCoordinates(
  recording: RecordingInfo | null | undefined,
): recording is RecordingInfo & { latitude: number; longitude: number } {
  if (!recording) return false;
  const { latitude, longitude } = recording;
  if (typeof latitude !== 'number' || typeof longitude !== 'number') return false;
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return false;
  // Same rule as the backend: any in-range pair is a location, 0,0 included.
  // Missing coordinates are null, never a placeholder value.
  return Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180;
}

export function modelRunMap(analysis: Analysis): Map<string, ModelRun> {
  return new Map(analysis.model_runs.map((run) => [run.id, run]));
}

/** "BirdNET GLOBAL 6K V2.4" stays as is; "Perch" + "2.0" becomes "Perch 2.0". */
export function runLabel(model: string, version: string): string {
  const name = model.replace(/\s*[\u2014\u2013]\s*/g, ' · ').trim();
  const bare = version.trim().replace(/^v/i, '');
  if (!bare || name.toLowerCase().includes(bare.toLowerCase())) return name;
  return `${name} ${version.trim()}`;
}

export function modelLabelForRun(run: ModelRun | undefined): string {
  if (!run) return 'Unknown model';
  return runLabel(run.model, run.version);
}

/** Events whose extent contains the playback time. */
export function eventsAtTime(events: DetectionEvent[], time: number): Set<string> {
  const ids = new Set<string>();
  for (const event of events) {
    if (time >= event.start_seconds && time < event.end_seconds) ids.add(event.id);
  }
  return ids;
}

export interface TimelineLane {
  key: string;
  commonName: string;
  scientificName: string;
  taxon: Taxon;
  /** Sub-rows so that overlapping events of the same species never share a row. */
  rows: DetectionEvent[][];
  eventCount: number;
}

/**
 * One lane per species, ordered like the species table (most events first).
 * Within a lane, events are greedily packed into rows without overlap.
 */
export function buildTimelineLanes(events: DetectionEvent[]): TimelineLane[] {
  const bySpecies = new Map<string, DetectionEvent[]>();
  for (const event of events) {
    const list = bySpecies.get(event.scientific_name) ?? [];
    list.push(event);
    bySpecies.set(event.scientific_name, list);
  }

  const lanes: TimelineLane[] = [];
  for (const [scientificName, list] of bySpecies) {
    const sorted = list.slice().sort((a, b) => a.start_seconds - b.start_seconds);
    const rows: DetectionEvent[][] = [];
    const rowEnds: number[] = [];
    for (const event of sorted) {
      const index = rowEnds.findIndex((end) => end <= event.start_seconds + 1e-6);
      if (index === -1) {
        rows.push([event]);
        rowEnds.push(event.end_seconds);
      } else {
        rows[index]!.push(event);
        rowEnds[index] = event.end_seconds;
      }
    }
    const first = sorted[0]!;
    lanes.push({
      key: scientificName,
      commonName: first.common_name,
      scientificName,
      taxon: first.taxon,
      rows,
      eventCount: sorted.length,
    });
  }

  return lanes.sort(
    (a, b) => b.eventCount - a.eventCount || a.commonName.localeCompare(b.commonName),
  );
}

export function topSpeciesNames(analysis: Analysis, limit = 3): string[] {
  return countedSpecies(analysis)
    .slice()
    .sort(
      (a, b) =>
        b.detection_event_count - a.detection_event_count ||
        b.max_confidence - a.max_confidence ||
        a.common_name.localeCompare(b.common_name),
    )
    .slice(0, limit)
    .map((s) => s.common_name);
}

export function hasNoDetections(analysis: Analysis): boolean {
  return !analysis.events.some((e) => e.counted_in_metrics);
}

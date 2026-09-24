/**
 * Realistic, internally consistent fixtures that conform to the generated API
 * types. A tiny test-only consolidation turns one set of raw window detections
 * into an Analysis at any threshold, mirroring the backend's rules (inclusive
 * threshold, per-species merge within the merge gap, metrics over counted
 * events only). Used by unit tests, Playwright route mocks and screenshots.
 */
import type {
  AcousticIndices,
  Analysis,
  DetectionEvent,
  ModelsResponse,
  Preview,
  QualityReport,
  RawDetection,
  RecordingInfo,
  ReviewStatus,
  SpeciesSummary,
  Taxon,
} from '../../api/generated';

export const ANALYSIS_ID = 'an_7f3c2a91d4';
export const PREVIEW_ID = 'pv_51b0e8c2';
export const RUN_ID = 'run_birdnet_7f3c2a';
export const DURATION = 60;
const WINDOW = 3;
const MERGE_GAP = 1;
const RAW_FLOOR = 0.1;
const BIODIVERSITY: ReadonlySet<Taxon> = new Set<Taxon>(['bird', 'amphibian', 'insect', 'mammal']);

interface SpeciesSpec {
  sci: string;
  common: string;
  taxon: Taxon;
  plausibility?: 'plausible' | 'unlikely' | 'unknown';
  /** [window index, confidence] */
  windows: Array<[number, number]>;
}

const SPECIES: SpeciesSpec[] = [
  {
    sci: 'Turdus migratorius',
    common: 'American Robin',
    taxon: 'bird',
    windows: [
      [0, 0.91],
      [1, 0.88],
      [2, 0.72],
      [5, 0.66],
      [6, 0.58],
      [10, 0.83],
      [11, 0.79],
      [15, 0.52],
      [18, 0.47],
    ],
  },
  {
    sci: 'Cardinalis cardinalis',
    common: 'Northern Cardinal',
    taxon: 'bird',
    windows: [
      [1, 0.94],
      [4, 0.81],
      [8, 0.62],
      [9, 0.55],
      [13, 0.77],
      [16, 0.44],
    ],
  },
  {
    sci: 'Melospiza melodia',
    common: 'Song Sparrow',
    taxon: 'bird',
    windows: [
      [2, 0.71],
      [3, 0.68],
      [12, 0.86],
      [17, 0.63],
      [19, 0.49],
    ],
  },
  {
    sci: 'Agelaius phoeniceus',
    common: 'Red-winged Blackbird',
    taxon: 'bird',
    windows: [
      [6, 0.74],
      [7, 0.69],
      [14, 0.57],
    ],
  },
  {
    sci: 'Pseudacris crucifer',
    common: 'Spring Peeper',
    taxon: 'amphibian',
    windows: [
      [0, 0.64],
      [3, 0.61],
      [9, 0.48],
      [15, 0.66],
      [16, 0.62],
    ],
  },
  {
    sci: 'Dumetella carolinensis',
    common: 'Gray Catbird',
    taxon: 'bird',
    windows: [
      [11, 0.61],
      [18, 0.52],
    ],
  },
  {
    sci: 'Poecile atricapillus',
    common: 'Black-capped Chickadee',
    taxon: 'bird',
    windows: [
      [5, 0.47],
      [13, 0.46],
    ],
  },
  {
    sci: 'Oecanthus fultoni',
    common: 'Snowy Tree Cricket',
    taxon: 'insect',
    windows: [
      [17, 0.43],
      [18, 0.41],
    ],
  },
  {
    sci: 'Passerina ciris',
    common: 'Painted Bunting',
    taxon: 'bird',
    plausibility: 'unlikely',
    windows: [[8, 0.67]],
  },
  {
    sci: 'Human vocal',
    common: 'Human vocal',
    taxon: 'human',
    windows: [
      [4, 0.72],
      [5, 0.64],
    ],
  },
  {
    sci: 'Engine',
    common: 'Engine',
    taxon: 'anthropogenic',
    windows: [[19, 0.55]],
  },
];

function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

export function rawDetections(confidenceScale = 1): RawDetection[] {
  const out: RawDetection[] = [];
  for (const spec of SPECIES) {
    for (const [index, unscaled] of spec.windows) {
      const confidence = Math.round(unscaled * confidenceScale * 10000) / 10000;
      if (confidence < RAW_FLOOR) continue;
      out.push({
        id: `det_${slug(spec.sci)}_${index}`,
        model_run_id: RUN_ID,
        label_raw: `${spec.sci}_${spec.common}`,
        scientific_name: spec.sci,
        common_name: spec.common,
        taxon: spec.taxon,
        start_seconds: index * WINDOW,
        end_seconds: index * WINDOW + WINDOW,
        confidence,
        plausibility: spec.plausibility ?? 'plausible',
      });
    }
  }
  return out.sort(
    (a, b) =>
      a.start_seconds - b.start_seconds || a.scientific_name.localeCompare(b.scientific_name),
  );
}

/** A reviewer's correction to another known label, keyed by event id. */
export interface Correction {
  scientific_name: string;
  common_name: string;
  taxon?: Taxon;
  reviewed_label: string;
}

function consolidate(
  raw: RawDetection[],
  threshold: number,
  reviews: Record<string, ReviewStatus>,
  corrections: Record<string, Correction> = {},
): DetectionEvent[] {
  const kept = raw.filter((d) => d.confidence + 1e-9 >= threshold);
  const bySpecies = new Map<string, RawDetection[]>();
  for (const d of kept) {
    const list = bySpecies.get(d.scientific_name) ?? [];
    list.push(d);
    bySpecies.set(d.scientific_name, list);
  }
  const events: DetectionEvent[] = [];
  for (const list of bySpecies.values()) {
    list.sort((a, b) => a.start_seconds - b.start_seconds);
    let group: RawDetection[] = [];
    const flush = () => {
      if (!group.length) return;
      const first = group[0]!;
      const start = first.start_seconds;
      const end = Math.max(...group.map((g) => g.end_seconds));
      const id = `evt_${slug(first.scientific_name)}_${start.toFixed(0)}`;
      const confs = group.map((g) => g.confidence);
      const fix = corrections[id];
      const review = fix ? 'corrected' : (reviews[id] ?? 'unreviewed');
      const plausibility = first.plausibility ?? 'unknown';
      const taxon = fix?.taxon ?? first.taxon;
      events.push({
        id,
        scientific_name: fix?.scientific_name ?? first.scientific_name,
        common_name: fix?.common_name ?? first.common_name,
        taxon,
        detected_scientific_name: first.scientific_name,
        detected_common_name: first.common_name,
        detected_taxon: first.taxon,
        model_run_id: RUN_ID,
        start_seconds: start,
        end_seconds: end,
        max_confidence: Math.max(...confs),
        mean_confidence:
          Math.round((confs.reduce((a, b) => a + b, 0) / confs.length) * 10000) / 10000,
        n_windows: group.length,
        contributing_detection_ids: group.map((g) => g.id),
        plausibility,
        review_status: review,
        reviewed_label: fix?.reviewed_label ?? null,
        review_note: null,
        // The backend rule: wildlife (as counted), not rejected, and not
        // unlikely unless a reviewer accepted or corrected it.
        counted_in_metrics:
          BIODIVERSITY.has(taxon) &&
          review !== 'rejected' &&
          (plausibility !== 'unlikely' || review === 'accepted' || review === 'corrected'),
      });
      group = [];
    };
    for (const d of list) {
      const last = group[group.length - 1];
      if (last && d.start_seconds > last.end_seconds + MERGE_GAP) flush();
      group.push(d);
    }
    flush();
  }
  return events.sort(
    (a, b) =>
      a.start_seconds - b.start_seconds || a.scientific_name.localeCompare(b.scientific_name),
  );
}

function round4(x: number): number {
  return Math.round(x * 10000) / 10000;
}

function summaries(events: DetectionEvent[], raw: RawDetection[]): SpeciesSummary[] {
  const bySpecies = new Map<string, DetectionEvent[]>();
  for (const e of events) {
    const list = bySpecies.get(e.scientific_name) ?? [];
    list.push(e);
    bySpecies.set(e.scientific_name, list);
  }
  const rawById = new Map(raw.map((r) => [r.id, r]));
  const out: SpeciesSummary[] = [];
  for (const [sci, evs] of bySpecies) {
    const contributing = evs
      .flatMap((e) => e.contributing_detection_ids)
      .map((id) => rawById.get(id)!);
    const confs = contributing.map((c) => c.confidence);
    out.push({
      scientific_name: sci,
      common_name: evs[0]!.common_name,
      taxon: evs[0]!.taxon,
      model_run_ids: [RUN_ID],
      detection_event_count: evs.length,
      raw_detection_count: contributing.length,
      max_confidence: round4(Math.max(...evs.map((e) => e.max_confidence))),
      mean_confidence: round4(confs.reduce((a, b) => a + b, 0) / confs.length),
      total_event_duration_seconds: evs.reduce((a, e) => a + (e.end_seconds - e.start_seconds), 0),
      first_detection_seconds: Math.min(...evs.map((e) => e.start_seconds)),
      last_detection_seconds: Math.max(...evs.map((e) => e.end_seconds)),
      // An accepted event overrides the range flag, as on the server.
      plausibility: evs.some((e) => e.plausibility === 'unlikely' && e.review_status !== 'accepted')
        ? 'unlikely'
        : 'plausible',
    });
  }
  return out.sort(
    (a, b) =>
      b.detection_event_count - a.detection_event_count ||
      b.max_confidence - a.max_confidence ||
      a.common_name.localeCompare(b.common_name),
  );
}

export const RECORDING: RecordingInfo = {
  id: 'rec_2b9d61',
  filename: 'hollow-creek-dawn.wav',
  content_type: 'audio/wav',
  byte_size: 5_760_044,
  checksum_sha256: '9c1f0e7a4b2d8c6e1f3a5b7d9e0c2a4f6b8d0e2c4a6f8b0d2e4c6a8f0b2d4e6f',
  format: 'WAV (PCM_16)',
  duration_seconds: DURATION,
  sample_rate_hz: 48000,
  channels: 1,
  bit_depth: 16,
  captured_at: '2026-05-14T05:42:00-04:00',
  timezone: 'America/New_York',
  latitude: 42.4531,
  longitude: -76.4735,
  site_name: 'Hollow Creek Easement, north meadow',
  recorder_type: null,
  notes: null,
};

export const QUALITY: QualityReport = {
  status: 'usable_with_warnings',
  score: 0.82,
  peak_dbfs: -3.4,
  rms_dbfs: -31.2,
  clipping_fraction: 0.0001,
  silence_fraction: 0.04,
  low_frequency_energy_fraction: 0.31,
  speech_detected: true,
  checks: [
    {
      name: 'decode',
      status: 'pass',
      message: 'Decoded 60.0 s of audio at 48 kHz.',
      value: 60,
      unit: 's',
    },
    {
      name: 'clipping',
      status: 'pass',
      message: 'Less than 0.1% of samples are clipped.',
      value: 0.0001,
      unit: null,
    },
    {
      name: 'level',
      status: 'pass',
      message: 'Recording level is in a healthy range.',
      value: -31.2,
      unit: 'dBFS',
    },
    {
      name: 'low_frequency_energy',
      status: 'warn',
      message: 'About 31% of energy is below 200 Hz, which often means wind or handling noise.',
      value: 0.31,
      unit: null,
    },
  ],
  warnings: ['Possible wind noise in the first 20 seconds.'],
};

export const ACOUSTIC_INDICES: AcousticIndices = {
  acoustic_complexity_index: 1864.2,
  acoustic_diversity_index: 2.14,
  acoustic_evenness_index: 0.38,
  bioacoustic_index: 41.7,
  ndsi: 0.62,
  spectral_entropy: 0.71,
  temporal_entropy: 0.93,
};

export interface BuildOptions {
  threshold?: number;
  reviews?: Record<string, ReviewStatus>;
  /** Corrections to known labels, keyed by event id. */
  corrections?: Record<string, Correction>;
  recording?: Partial<RecordingInfo>;
  quality?: Partial<QualityReport> | null;
  status?: Analysis['status'];
  stage?: string | null;
  id?: string;
  audioUrl?: string | null;
  /** Scales every raw confidence, e.g. 0.5 for a quiet recording with no events at 60%. */
  confidenceScale?: number;
}

/** A completed analysis at the given decision threshold. */
export function buildAnalysis(options: BuildOptions = {}): Analysis {
  const threshold = Math.round((options.threshold ?? 0.6) * 100) / 100;
  const id = options.id ?? ANALYSIS_ID;
  const raw = rawDetections(options.confidenceScale ?? 1);
  const events = consolidate(raw, threshold, options.reviews ?? {}, options.corrections ?? {});
  const counted = events.filter((e) => e.counted_in_metrics);
  // Like the backend, the species table holds counted species only.
  const countedSummaries = summaries(counted, raw);
  const counts = countedSummaries.map((s) => s.detection_event_count);
  const n = counts.reduce((a, b) => a + b, 0);
  const shannon = n ? -counts.reduce((acc, c) => acc + (c / n) * Math.log(c / n), 0) : 0;
  const s = counts.length;
  const pielou = s > 1 ? shannon / Math.log(s) : 0;
  const simpson = n ? 1 - counts.reduce((acc, c) => acc + (c / n) ** 2, 0) : 0;
  const dominant = countedSummaries[0];
  const byTaxon: Record<string, number> = {};
  for (const e of counted) byTaxon[e.taxon] = (byTaxon[e.taxon] ?? 0) + 1;
  const status = options.status ?? 'completed';
  const completed = status === 'completed';

  return {
    schema_version: '1.2.0',
    id,
    status,
    stage: options.stage ?? (completed ? 'completed' : status === 'failed' ? 'failed' : 'queued'),
    recording: { ...RECORDING, ...options.recording },
    quality: options.quality === null ? null : { ...QUALITY, ...options.quality },
    settings: {
      decision_threshold: threshold,
      raw_threshold: RAW_FLOOR,
      merge_gap_seconds: MERGE_GAP,
      hop_seconds: WINDOW,
      requested_models: ['birdnet'],
      location_filter: true,
      location_filter_threshold: 0.03,
    },
    model_runs: [
      {
        id: RUN_ID,
        adapter: 'birdnet',
        model: 'BirdNET GLOBAL 6K',
        version: 'V2.4',
        model_sha256: '55f3e4055b1a13bfa9a2452731d0d34f6a02d6b775a334362665892794165e4c',
        taxa: ['bird', 'amphibian', 'insect', 'mammal', 'human', 'anthropogenic', 'environmental'],
        experimental: false,
        required_sample_rate_hz: 48000,
        window_seconds: WINDOW,
        hop_seconds: WINDOW,
        raw_threshold: RAW_FLOOR,
        configuration: { overlap: 0, sensitivity: 1, week: 20 },
        runtime_ms: 2140,
        n_windows: 20,
      },
    ],
    metrics: completed
      ? {
          species_richness: s,
          shannon_index: round4(shannon),
          pielou_evenness: round4(pielou),
          simpson_diversity: round4(simpson),
          total_detection_events: n,
          raw_detection_count: counted.reduce((a, e) => a + e.n_windows, 0),
          events_per_minute: Math.round((n / (DURATION / 60)) * 1000) / 1000,
          dominant_species: dominant
            ? { scientific_name: dominant.scientific_name, common_name: dominant.common_name }
            : null,
          events_by_taxon: byTaxon,
          basis: 'detection_events',
        }
      : null,
    acoustic_indices: completed ? ACOUSTIC_INDICES : null,
    species: completed ? countedSummaries : [],
    events: completed ? events : [],
    raw_detections: completed ? raw : [],
    assets: {
      audio_url: options.audioUrl ?? null,
      spectrogram_url: `/api/v1/analyses/${id}/spectrogram.png`,
      spectrogram_min_hz: 0,
      spectrogram_max_hz: 12000,
      csv_url: `/api/v1/analyses/${id}/export.csv`,
      json_url: `/api/v1/analyses/${id}/export.json`,
    },
    warnings: [],
    error_code: null,
    error_message: null,
    software_version: '0.1.0',
    created_at: '2026-09-24T13:12:08Z',
    completed_at: completed ? '2026-09-24T13:12:13Z' : null,
    stage_timings_ms: completed
      ? {
          normalizing: 180,
          quality: 95,
          spectrogram: 410,
          'model:birdnet': 2140,
          consolidating: 12,
          metrics: 4,
        }
      : {},
  };
}

/** An in-flight analysis as returned by POST (202) and early polls. */
export function pendingAnalysis(
  stage: string,
  status: 'queued' | 'processing' = 'processing',
): Analysis {
  return buildAnalysis({ status, stage });
}

export function failedAnalysis(errorCode: Analysis['error_code'], message: string): Analysis {
  return {
    ...buildAnalysis({ status: 'failed', stage: 'model:birdnet' }),
    error_code: errorCode,
    error_message: message,
  };
}

export const PREVIEW: Preview = {
  id: PREVIEW_ID,
  recording: RECORDING,
  quality: QUALITY,
  spectrogram_url: `/api/v1/previews/${PREVIEW_ID}/spectrogram.png`,
  spectrogram_min_hz: 0,
  spectrogram_max_hz: 12000,
  expires_at: '2099-01-01T00:00:00Z',
};

export const MODELS: ModelsResponse = {
  models: [
    {
      key: 'birdnet',
      name: 'Birds and more — BirdNET v2.4',
      version: '2.4',
      taxa: ['bird', 'amphibian', 'insect', 'mammal'],
      status: 'ready',
      experimental: false,
      required_sample_rate_hz: 48000,
      window_seconds: 3,
      license: 'CC BY-NC-SA 4.0',
      model_card_url: null,
      description: 'BirdNET GLOBAL 6K V2.4 — about 6,500 classes.',
      unavailable_reason: null,
    },
    {
      key: 'frogs_insects',
      name: 'Frogs and insects',
      version: '0.1',
      taxa: ['amphibian', 'insect'],
      status: 'disabled',
      experimental: true,
      required_sample_rate_hz: 32000,
      window_seconds: 5,
      license: 'MIT',
      model_card_url: null,
      description: 'Experimental frog and insect classifier.',
      unavailable_reason: 'Disabled until it passes the validation benchmark.',
    },
    {
      key: 'perch',
      name: 'Perch 2.0',
      version: '2.0',
      taxa: ['bird', 'amphibian', 'insect', 'mammal'],
      status: 'ready',
      experimental: true,
      required_sample_rate_hz: 32000,
      window_seconds: 5,
      license: 'Apache-2.0',
      model_card_url: null,
      description: 'Experimental general bioacoustics model.',
      unavailable_reason: null,
    },
  ],
};

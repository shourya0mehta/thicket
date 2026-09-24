/* eslint-disable */
/**
 * GENERATED FILE. DO NOT EDIT.
 *
 * Source: shared/api.schema.json (exported from backend/thicket/api/schemas.py).
 * Regenerate with `npm run gen:types`; CI checks freshness with
 * `npm run check:types-fresh`.
 */

/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ErrorCode".
 */
export type ErrorCode =
  | 'unsupported_file_type'
  | 'file_too_large'
  | 'audio_too_long'
  | 'audio_decode_failed'
  | 'audio_too_short'
  | 'model_unavailable'
  | 'unknown_model'
  | 'invalid_parameter'
  | 'analysis_not_found'
  | 'event_not_found'
  | 'analysis_timeout'
  | 'internal_error'
  | 'unsupported_audio'
  | 'not_found'
  | 'rate_limited'
  | 'request_timeout';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Taxon".
 */
export type Taxon =
  | 'bird'
  | 'amphibian'
  | 'insect'
  | 'mammal'
  | 'human'
  | 'domestic_animal'
  | 'anthropogenic'
  | 'environmental'
  | 'noise';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReviewStatus".
 */
export type ReviewStatus = 'unreviewed' | 'accepted' | 'rejected' | 'corrected';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "QualityStatus".
 */
export type QualityStatus = 'usable' | 'usable_with_warnings' | 'not_usable';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AnalysisStatus".
 */
export type AnalysisStatus = 'queued' | 'processing' | 'completed' | 'failed';

export interface ThicketAPI {}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AcousticIndices".
 */
export interface AcousticIndices {
  acoustic_complexity_index: number;
  acoustic_diversity_index: number;
  acoustic_evenness_index: number;
  bioacoustic_index: number;
  ndsi: number;
  spectral_entropy: number;
  temporal_entropy: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Analysis".
 */
export interface Analysis {
  acoustic_indices?: AcousticIndices | null;
  assets: Assets;
  completed_at?: string | null;
  created_at: string;
  error_code?: ErrorCode | null;
  error_message?: string | null;
  events: DetectionEvent[];
  id: string;
  metrics: Metrics | null;
  model_runs: ModelRun[];
  quality: QualityReport | null;
  raw_detections: RawDetection[];
  recording: RecordingInfo | null;
  schema_version?: string;
  settings: AnalysisSettings;
  software_version: string;
  species: SpeciesSummary[];
  stage?: string | null;
  stage_timings_ms?: {
    [k: string]: number;
  };
  status: AnalysisStatus;
  warnings: string[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Assets".
 */
export interface Assets {
  audio_url: string | null;
  csv_url: string;
  json_url: string;
  spectrogram_max_hz?: number;
  spectrogram_min_hz?: number;
  spectrogram_url: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "DetectionEvent".
 */
export interface DetectionEvent {
  common_name: string;
  contributing_detection_ids: string[];
  counted_in_metrics: boolean;
  detected_common_name: string;
  detected_scientific_name: string;
  detected_taxon: Taxon;
  end_seconds: number;
  id: string;
  max_confidence: number;
  mean_confidence: number;
  model_run_id: string;
  n_windows: number;
  plausibility?: 'plausible' | 'unlikely' | 'unknown';
  review_note?: string | null;
  review_status?: ReviewStatus;
  reviewed_label?: string | null;
  scientific_name: string;
  start_seconds: number;
  taxon: Taxon;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Metrics".
 */
export interface Metrics {
  basis?: string;
  dominant_species: SpeciesRef | null;
  events_by_taxon: {
    [k: string]: number;
  };
  events_per_minute: number;
  pielou_evenness: number;
  raw_detection_count: number;
  shannon_index: number;
  simpson_diversity: number;
  species_richness: number;
  total_detection_events: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SpeciesRef".
 */
export interface SpeciesRef {
  common_name: string;
  scientific_name: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ModelRun".
 */
export interface ModelRun {
  adapter: string;
  configuration: {
    [k: string]: unknown;
  };
  experimental: boolean;
  hop_seconds: number;
  id: string;
  model: string;
  model_sha256?: string | null;
  n_windows: number;
  raw_threshold: number;
  required_sample_rate_hz: number;
  runtime_ms: number;
  taxa: string[];
  version: string;
  window_seconds: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "QualityReport".
 */
export interface QualityReport {
  checks: QualityCheck[];
  clipping_fraction: number;
  low_frequency_energy_fraction: number;
  peak_dbfs: number;
  rms_dbfs: number;
  score: number;
  silence_fraction: number;
  speech_detected: boolean;
  status: QualityStatus;
  warnings: string[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "QualityCheck".
 */
export interface QualityCheck {
  message: string;
  name: string;
  status: 'pass' | 'warn' | 'fail';
  unit?: string | null;
  value?: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RawDetection".
 */
export interface RawDetection {
  common_name: string;
  confidence: number;
  end_seconds: number;
  id: string;
  label_raw: string;
  model_run_id: string;
  plausibility?: 'plausible' | 'unlikely' | 'unknown';
  scientific_name: string;
  start_seconds: number;
  taxon: Taxon;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecordingInfo".
 */
export interface RecordingInfo {
  bit_depth?: number | null;
  byte_size: number;
  captured_at?: string | null;
  channels: number;
  checksum_sha256: string;
  content_type?: string | null;
  duration_seconds: number;
  filename: string;
  format?: string | null;
  id: string;
  latitude?: number | null;
  longitude?: number | null;
  notes?: string | null;
  recorder_type?: string | null;
  sample_rate_hz: number;
  site_name?: string | null;
  timezone?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AnalysisSettings".
 */
export interface AnalysisSettings {
  decision_threshold: number;
  hop_seconds: number;
  location_filter: boolean;
  location_filter_threshold: number;
  merge_gap_seconds: number;
  raw_threshold: number;
  requested_models: string[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SpeciesSummary".
 */
export interface SpeciesSummary {
  common_name: string;
  detection_event_count: number;
  first_detection_seconds: number;
  last_detection_seconds: number;
  max_confidence: number;
  mean_confidence: number;
  model_run_ids: string[];
  plausibility?: 'plausible' | 'unlikely' | 'unknown';
  raw_detection_count: number;
  scientific_name: string;
  taxon: Taxon;
  total_event_duration_seconds: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AnalysisExport".
 */
export interface AnalysisExport {
  acoustic_indices?: AcousticIndices | null;
  assets: Assets;
  completed_at?: string | null;
  created_at: string;
  error_code?: ErrorCode | null;
  error_message?: string | null;
  events: DetectionEvent[];
  export_metadata: ExportMetadata;
  id: string;
  metrics: Metrics | null;
  model_runs: ModelRun[];
  quality: QualityReport | null;
  raw_detections: RawDetection[];
  recording: RecordingInfo | null;
  schema_version?: string;
  settings: AnalysisSettings;
  software_version: string;
  species: SpeciesSummary[];
  stage?: string | null;
  stage_timings_ms?: {
    [k: string]: number;
  };
  status: AnalysisStatus;
  warnings: string[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ExportMetadata".
 */
export interface ExportMetadata {
  decision_threshold: number;
  exported_at: string;
  note: string;
  schema_version: string;
  software_version: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AnalysisList".
 */
export interface AnalysisList {
  items: AnalysisSummary[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AnalysisSummary".
 */
export interface AnalysisSummary {
  created_at: string;
  decision_threshold: number;
  duration_seconds: number | null;
  filename: string | null;
  id: string;
  site_name: string | null;
  species_richness: number | null;
  status: AnalysisStatus;
  top_species: string[];
  total_detection_events: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  detail?: {
    [k: string]: unknown;
  } | null;
  error_code: ErrorCode;
  message: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "EventReviewUpdate".
 */
export interface EventReviewUpdate {
  review_note?: string | null;
  review_status: ReviewStatus;
  reviewed_label?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "HealthResponse".
 */
export interface HealthResponse {
  environment: string;
  ffmpeg: boolean;
  models: {
    [k: string]: string;
  };
  status: 'ok' | 'degraded';
  version: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ModelInfo".
 */
export interface ModelInfo {
  description: string;
  experimental: boolean;
  key: string;
  license: string;
  model_card_url?: string | null;
  name: string;
  required_sample_rate_hz: number;
  status: 'ready' | 'loading' | 'unavailable' | 'disabled';
  taxa: string[];
  unavailable_reason?: string | null;
  version: string;
  window_seconds: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ModelsResponse".
 */
export interface ModelsResponse {
  models: ModelInfo[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Preview".
 */
export interface Preview {
  expires_at: string;
  id: string;
  quality: QualityReport;
  recording: RecordingInfo;
  spectrogram_max_hz?: number;
  spectrogram_min_hz?: number;
  spectrogram_url: string;
}

/** Schema version these types were generated from. */
export const API_SCHEMA_VERSION = '1.2.0';

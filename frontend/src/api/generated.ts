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
 * via the `definition` "AlertKind".
 */
export type AlertKind =
  | 'richness_drop'
  | 'activity_drop'
  | 'new_species_for_site'
  | 'priority_species_detected'
  | 'expected_species_missing'
  | 'species_surge'
  | 'low_quality_streak'
  | 'speech_detected'
  | 'muffled_audio'
  | 'level_drift'
  | 'recording_gap'
  | 'clipping_increase'
  | 'channel_imbalance'
  | 'dc_offset'
  | 'battery_low'
  | 'temperature_extreme'
  | 'clock_suspect'
  | 'schedule_deviation';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AlertSeverity".
 */
export type AlertSeverity = 'info' | 'watch' | 'warning';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AlertStatus".
 */
export type AlertStatus = 'open' | 'acknowledged' | 'resolved' | 'snoozed';
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
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AuthMode".
 */
export type AuthMode = 'disabled' | 'dev' | 'google';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "CapturedAtSource".
 */
export type CapturedAtSource =
  'filename' | 'file_metadata' | 'user' | 'browser_last_modified' | 'unknown';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "BatchItemStatus".
 */
export type BatchItemStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'skipped';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "HabitatType".
 */
export type HabitatType =
  | 'pasture'
  | 'hayfield'
  | 'cropland'
  | 'shrubland'
  | 'forest'
  | 'wetland'
  | 'riparian_buffer'
  | 'pond'
  | 'farmstead'
  | 'other';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Role".
 */
export type Role = 'owner' | 'manager' | 'reviewer' | 'viewer';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "OrganizationKind".
 */
export type OrganizationKind =
  'farm' | 'ranch' | 'land_trust' | 'restoration_project' | 'agency' | 'research' | 'other';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecorderMake".
 */
export type RecorderMake = 'audiomoth' | 'song_meter' | 'phone' | 'handheld' | 'other';
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReportTemplateKey".
 */
export type ReportTemplateKey = 'evidence' | 'nrcs' | 'aem' | 'certification' | 'credit';

export interface ThicketAPI {}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Accumulation".
 */
export interface Accumulation {
  note?: string;
  points: AccumulationPoint[];
  site_id: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AccumulationPoint".
 */
export interface AccumulationPoint {
  captured_at: string | null;
  cumulative_species: number;
  recording_index: number;
}
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
 * via the `definition` "Alert".
 */
export interface Alert {
  acknowledged_by?: string | null;
  category: 'ecology' | 'quality' | 'recorder';
  created_at: string;
  deployment_id?: string | null;
  detail: string;
  evidence: {
    [k: string]: unknown;
  };
  first_seen_at: string;
  id: string;
  kind: AlertKind;
  last_seen_at: string;
  note?: string | null;
  occurrences?: number;
  organization_id: string;
  recorder_id?: string | null;
  recording_ids?: string[];
  severity: AlertSeverity;
  site_id?: string | null;
  snoozed_until?: string | null;
  species?: SpeciesRef | null;
  status: AlertStatus;
  suggested_action?: string | null;
  title: string;
  updated_at: string;
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
 * via the `definition` "AlertPage".
 */
export interface AlertPage {
  counts_by_category: {
    [k: string]: number;
  };
  counts_by_status: {
    [k: string]: number;
  };
  items: Alert[];
  total: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AlertRules".
 */
export interface AlertRules {
  activity_drop_mad?: number;
  battery_low_v?: {
    [k: string]: number;
  };
  consecutive_recordings?: number;
  enabled?: boolean;
  expected_species_min_presence?: number;
  expected_species_missing_recordings?: number;
  gap_min_hours?: number;
  gap_multiplier?: number;
  low_quality_streak?: number;
  min_baseline_recordings?: number;
  priority_species?: string[];
  richness_drop_mad?: number;
  species_surge_mad?: number;
  temperature_max_c?: number;
  temperature_min_c?: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "AlertUpdate".
 */
export interface AlertUpdate {
  note?: string | null;
  snoozed_until?: string | null;
  status: AlertStatus;
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
 * via the `definition` "AuthConfig".
 */
export interface AuthConfig {
  allowed_domains?: string[];
  google_client_id?: string | null;
  mode: AuthMode;
  sign_in_url?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "BatchItem".
 */
export interface BatchItem {
  analysis_id?: string | null;
  captured_at?: string | null;
  captured_at_source?: CapturedAtSource;
  error_code?: string | null;
  error_message?: string | null;
  filename: string;
  recording_id?: string | null;
  status: BatchItemStatus;
  telemetry?: Telemetry | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Telemetry".
 */
export interface Telemetry {
  battery_v?: number | null;
  device_id?: string | null;
  gain?: string | null;
  source?: 'audiomoth_comment' | 'song_meter_summary' | 'guano' | 'none';
  temperature_c?: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "BatchJob".
 */
export interface BatchJob {
  completed_at?: string | null;
  created_at: string;
  deployment_id: string | null;
  done: number;
  failed: number;
  id: string;
  items: BatchItem[];
  organization_id: string;
  settings: {
    [k: string]: unknown;
  };
  sidecars_parsed?: string[];
  site_id: string | null;
  skipped: number;
  status: 'queued' | 'processing' | 'completed' | 'completed_with_errors' | 'failed';
  total: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Dashboard".
 */
export interface Dashboard {
  activity_heatmap: HeatCell[];
  baseline_note: string;
  by_taxon: TaxonCount[];
  detection_events: number;
  generated_at: string;
  indices_by_day: IndexPoint[];
  minutes_recorded: number;
  open_alerts: number;
  organization_id: string;
  period_end: string;
  period_start: string;
  quality: {
    [k: string]: number;
  };
  recordings: number;
  richness_by_day: DayPoint[];
  site_ids: string[];
  species: SpeciesRollup[];
  species_counted: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "HeatCell".
 */
export interface HeatCell {
  events_per_minute: number;
  hour: number;
  recordings: number;
  weekday: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "TaxonCount".
 */
export interface TaxonCount {
  detection_events: number;
  species: number;
  taxon: Taxon;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "IndexPoint".
 */
export interface IndexPoint {
  acoustic_complexity_index?: number | null;
  acoustic_diversity_index?: number | null;
  bioacoustic_index?: number | null;
  date: string;
  ndsi?: number | null;
  site_id?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "DayPoint".
 */
export interface DayPoint {
  date: string;
  detection_events: number;
  events_per_minute: number;
  minutes: number;
  recordings: number;
  shannon_index?: number | null;
  site_id?: string | null;
  species_richness: number;
  usable_fraction?: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SpeciesRollup".
 */
export interface SpeciesRollup {
  common_name: string;
  detection_events: number;
  first_detected_at: string | null;
  is_priority?: boolean;
  last_detected_at: string | null;
  max_confidence: number;
  plausibility?: 'plausible' | 'unlikely' | 'unknown';
  presence_fraction: number;
  recordings_total: number;
  recordings_with_detection: number;
  scientific_name: string;
  site_ids: string[];
  taxon: Taxon;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Deployment".
 */
export interface Deployment {
  created_at: string;
  ended_at?: string | null;
  expected_clip_seconds?: number | null;
  expected_interval_minutes?: number | null;
  gain_setting?: string | null;
  id: string;
  mount_height_m?: number | null;
  notes?: string | null;
  organization_id: string;
  orientation?: string | null;
  recorder_id: string;
  schedule_description?: string | null;
  site_id: string;
  started_at: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "DeploymentCreate".
 */
export interface DeploymentCreate {
  ended_at?: string | null;
  expected_clip_seconds?: number | null;
  expected_interval_minutes?: number | null;
  gain_setting?: string | null;
  mount_height_m?: number | null;
  notes?: string | null;
  orientation?: string | null;
  recorder_id: string;
  schedule_description?: string | null;
  site_id: string;
  started_at: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "DeploymentUpdate".
 */
export interface DeploymentUpdate {
  ended_at?: string | null;
  expected_clip_seconds?: number | null;
  expected_interval_minutes?: number | null;
  gain_setting?: string | null;
  mount_height_m?: number | null;
  notes?: string | null;
  orientation?: string | null;
  schedule_description?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "DevLogin".
 */
export interface DevLogin {
  email: string;
  name?: string | null;
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
 * via the `definition` "Gap".
 */
export interface Gap {
  end: string;
  expected_recordings?: number | null;
  hours: number;
  start: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "HealthCheck".
 */
export interface HealthCheck {
  baseline?: number | null;
  message: string;
  name: string;
  status: 'good' | 'watch' | 'attention' | 'unknown';
  value?: number | null;
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
 * via the `definition` "Invite".
 */
export interface Invite {
  accept_url?: string | null;
  accepted_at?: string | null;
  email: string;
  expires_at: string;
  id: string;
  invited_by: string;
  organization_id: string;
  role: Role;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "InviteCreate".
 */
export interface InviteCreate {
  email: string;
  role?: Role;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Me".
 */
export interface Me {
  auth_mode: AuthMode;
  organizations: Organization[];
  roles: {
    [k: string]: Role;
  };
  unread_notifications?: number;
  user: User;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Organization".
 */
export interface Organization {
  country?: string | null;
  created_at: string;
  id: string;
  kind: OrganizationKind;
  member_count?: number;
  name: string;
  region?: string | null;
  site_count?: number;
  slug: string;
  timezone: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "User".
 */
export interface User {
  created_at: string;
  email: string;
  id: string;
  last_login_at?: string | null;
  name: string;
  picture_url?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Membership".
 */
export interface Membership {
  joined_at: string;
  role: Role;
  user: User;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "MembershipUpdate".
 */
export interface MembershipUpdate {
  role: Role;
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
 * via the `definition` "Notification".
 */
export interface Notification {
  alert: Alert;
  channel: 'in_app' | 'email';
  created_at: string;
  id: string;
  read_at?: string | null;
  sent_at?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "NotificationPage".
 */
export interface NotificationPage {
  items: Notification[];
  unread: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "NotificationPrefs".
 */
export interface NotificationPrefs {
  categories?: ('ecology' | 'quality' | 'recorder')[];
  email_digest?: 'immediate' | 'daily' | 'weekly' | 'off';
  email_enabled?: boolean;
  min_severity?: AlertSeverity;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "OrganizationCreate".
 */
export interface OrganizationCreate {
  country?: string | null;
  kind?: OrganizationKind;
  name: string;
  region?: string | null;
  timezone?: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "OrganizationUpdate".
 */
export interface OrganizationUpdate {
  country?: string | null;
  kind?: OrganizationKind | null;
  name?: string | null;
  region?: string | null;
  timezone?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Phenology".
 */
export interface Phenology {
  cells: PhenologyCell[];
  first_detection_by_year: {
    [k: string]: string;
  };
  last_detection_by_year: {
    [k: string]: string;
  };
  organization_id: string;
  site_ids: string[];
  species: SpeciesRef;
  taxon: Taxon;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "PhenologyCell".
 */
export interface PhenologyCell {
  events_per_minute: number;
  iso_week: number;
  presence_fraction: number;
  recordings: number;
  recordings_with_detection: number;
  year: number;
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
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Recorder".
 */
export interface Recorder {
  active_deployment_id?: string | null;
  created_at: string;
  firmware?: string | null;
  health?: 'good' | 'watch' | 'attention' | 'unknown';
  id: string;
  label: string;
  last_recording_at?: string | null;
  make: RecorderMake;
  model?: string | null;
  notes?: string | null;
  organization_id: string;
  serial?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecorderCreate".
 */
export interface RecorderCreate {
  firmware?: string | null;
  label: string;
  make?: RecorderMake;
  model?: string | null;
  notes?: string | null;
  serial?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecorderHealth".
 */
export interface RecorderHealth {
  baseline_note: string;
  battery: SeriesPoint[];
  checks: HealthCheck[];
  clipping_fraction: SeriesPoint[];
  deployment: Deployment | null;
  expected_last_7d: number | null;
  gaps: Gap[];
  high_band_fraction: SeriesPoint[];
  last_recording_at: string | null;
  level_dbfs: SeriesPoint[];
  median_interval_minutes: number | null;
  open_alerts: Alert[];
  recorder: Recorder;
  recordings_last_7d: number;
  spectral_centroid_hz: SeriesPoint[];
  status: 'good' | 'watch' | 'attention' | 'unknown';
  temperature: SeriesPoint[];
  uptime_fraction_7d: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SeriesPoint".
 */
export interface SeriesPoint {
  t: string;
  v: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecorderUpdate".
 */
export interface RecorderUpdate {
  firmware?: string | null;
  label?: string | null;
  make?: RecorderMake | null;
  model?: string | null;
  notes?: string | null;
  serial?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecordingPage".
 */
export interface RecordingPage {
  items: RecordingSummary[];
  page: number;
  page_size: number;
  total: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "RecordingSummary".
 */
export interface RecordingSummary {
  analysis_id: string | null;
  analysis_status: AnalysisStatus | null;
  captured_at: string | null;
  captured_at_source: CapturedAtSource;
  created_at: string;
  decision_threshold: number | null;
  deployment_id: string | null;
  duration_seconds: number;
  filename: string;
  id: string;
  latitude: number | null;
  longitude: number | null;
  organization_id: string;
  quality_status: QualityStatus | null;
  recorder_id: string | null;
  site_id: string | null;
  site_name: string | null;
  species_richness: number | null;
  telemetry: Telemetry;
  timezone: string | null;
  total_detection_events: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Report".
 */
export interface Report {
  analysis_count: number;
  checksum_sha256?: string | null;
  completed_at?: string | null;
  created_at: string;
  created_by: string;
  error_message?: string | null;
  id: string;
  json_url?: string | null;
  missing_fields?: string[];
  organization_id: string;
  page_count?: number | null;
  pdf_url?: string | null;
  period_end: string;
  period_start: string;
  site_ids: string[];
  status: 'queued' | 'rendering' | 'ready' | 'failed';
  template: ReportTemplateKey;
  title: string;
  warnings?: string[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReportCreate".
 */
export interface ReportCreate {
  baseline_end?: string | null;
  baseline_start?: string | null;
  decision_threshold?: number | null;
  fields?: {
    [k: string]: unknown;
  };
  include_raw_manifest?: boolean;
  include_review_log?: boolean;
  period_end: string;
  period_start: string;
  site_ids?: string[];
  template: ReportTemplateKey;
  title: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReportField".
 */
export interface ReportField {
  example?: unknown;
  group: string;
  help?: string | null;
  label: string;
  name: string;
  options?: string[] | null;
  required?: boolean;
  templates: ReportTemplateKey[];
  type:
    | 'string'
    | 'text'
    | 'date'
    | 'datetime'
    | 'number'
    | 'integer'
    | 'boolean'
    | 'enum'
    | 'list'
    | 'file';
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReportList".
 */
export interface ReportList {
  items: Report[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReportTemplate".
 */
export interface ReportTemplate {
  audience: string;
  description: string;
  fields: ReportField[];
  key: ReportTemplateKey;
  pages: string[];
  title: string;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "ReportTemplates".
 */
export interface ReportTemplates {
  templates: ReportTemplate[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "Site".
 */
export interface Site {
  area_hectares?: number | null;
  created_at: string;
  fsa_field_number?: string | null;
  habitat_type?: HabitatType | null;
  id: string;
  latitude?: number | null;
  longitude?: number | null;
  name: string;
  notes?: string | null;
  organization_id: string;
  paddock_id?: string | null;
  stats: SiteStats;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SiteStats".
 */
export interface SiteStats {
  first_recording_at?: string | null;
  health?: 'good' | 'watch' | 'attention' | 'unknown';
  last_recording_at?: string | null;
  minutes_recorded?: number;
  open_alerts?: number;
  recordings?: number;
  species_counted?: number;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SiteComparison".
 */
export interface SiteComparison {
  period_end: string;
  period_start: string;
  rows: SiteComparisonRow[];
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SiteComparisonRow".
 */
export interface SiteComparisonRow {
  events_per_minute: number;
  minutes: number;
  recordings: number;
  shannon_index: number | null;
  site: Site;
  species_richness: number;
  top_species: SpeciesRef[];
  usable_fraction: number | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SiteCreate".
 */
export interface SiteCreate {
  area_hectares?: number | null;
  fsa_field_number?: string | null;
  habitat_type?: HabitatType | null;
  latitude?: number | null;
  longitude?: number | null;
  name: string;
  notes?: string | null;
  paddock_id?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "SiteUpdate".
 */
export interface SiteUpdate {
  area_hectares?: number | null;
  fsa_field_number?: string | null;
  habitat_type?: HabitatType | null;
  latitude?: number | null;
  longitude?: number | null;
  name?: string | null;
  notes?: string | null;
  paddock_id?: string | null;
}
/**
 * This interface was referenced by `ThicketAPI`'s JSON-Schema
 * via the `definition` "UploadedFile".
 */
export interface UploadedFile {
  byte_size: number;
  content_type: string;
  created_at: string;
  filename: string;
  id: string;
  organization_id: string;
  url: string;
}

/** Schema version these types were generated from. */
export const API_SCHEMA_VERSION = '1.2.0';

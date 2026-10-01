/**
 * Re-exports of the generated API contract plus small derived helpers.
 * Response shapes come only from ./generated (see scripts/gen-types.mjs).
 */
export type {
  AcousticIndices,
  Analysis,
  AnalysisList,
  AnalysisSettings,
  AnalysisStatus,
  AnalysisSummary,
  Assets,
  DetectionEvent,
  ErrorCode,
  ErrorResponse,
  EventReviewUpdate,
  HealthResponse,
  Metrics,
  ModelInfo,
  ModelRun,
  ModelsResponse,
  Preview,
  QualityCheck,
  QualityReport,
  QualityStatus,
  RawDetection,
  RecordingInfo,
  ReviewStatus,
  SpeciesRef,
  SpeciesSummary,
  Taxon,
} from './generated';
export { API_SCHEMA_VERSION } from './generated';

import type { DetectionEvent, ModelInfo } from './generated';

export type Plausibility = NonNullable<DetectionEvent['plausibility']>;
export type ModelStatus = ModelInfo['status'];

/** Parameters for POST /api/v1/analyses (multipart). */
export interface CreateAnalysisParams {
  file?: File | null;
  previewId?: string | null;
  models: string[];
  threshold: number;
  latitude?: number | null;
  longitude?: number | null;
  capturedAt?: string | null;
  timezone?: string | null;
  siteName?: string | null;
  /** Platform context: file the analysis under an organization and site. */
  organizationId?: string | null;
  siteId?: string | null;
  deploymentId?: string | null;
  recorderId?: string | null;
}

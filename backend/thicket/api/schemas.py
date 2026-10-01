"""Canonical API contract.

Every response shape the frontend consumes is defined here, once. The JSON
Schema generated from these models (``shared/api.schema.json``) is the
source for the frontend's TypeScript types, so the two cannot drift.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.3.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Taxon(StrEnum):
    bird = "bird"
    amphibian = "amphibian"
    insect = "insect"
    mammal = "mammal"
    human = "human"
    domestic_animal = "domestic_animal"
    anthropogenic = "anthropogenic"
    environmental = "environmental"
    noise = "noise"


# Taxa that count toward biodiversity metrics. Human, noise and
# anthropogenic labels are surfaced as warnings, never as species.
BIODIVERSITY_TAXA: frozenset[str] = frozenset({"bird", "amphibian", "insect", "mammal"})


class AnalysisStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class QualityStatus(StrEnum):
    usable = "usable"
    usable_with_warnings = "usable_with_warnings"
    not_usable = "not_usable"


class ReviewStatus(StrEnum):
    unreviewed = "unreviewed"
    accepted = "accepted"
    rejected = "rejected"
    corrected = "corrected"


class ErrorCode(StrEnum):
    unsupported_file_type = "unsupported_file_type"
    file_too_large = "file_too_large"
    audio_too_long = "audio_too_long"
    audio_decode_failed = "audio_decode_failed"
    audio_too_short = "audio_too_short"
    model_unavailable = "model_unavailable"
    unknown_model = "unknown_model"
    invalid_parameter = "invalid_parameter"
    analysis_not_found = "analysis_not_found"
    event_not_found = "event_not_found"
    analysis_timeout = "analysis_timeout"
    internal_error = "internal_error"
    # Added in 1.1.0 (additive).
    unsupported_audio = "unsupported_audio"
    not_found = "not_found"
    rate_limited = "rate_limited"
    request_timeout = "request_timeout"
    # Added in 1.3.0 for the platform (additive).
    unauthenticated = "unauthenticated"
    forbidden = "forbidden"
    conflict = "conflict"


class ErrorResponse(_Model):
    error_code: ErrorCode
    message: str
    detail: dict | None = None


# ---------------------------------------------------------------- recording


class RecordingInfo(_Model):
    id: str
    filename: str
    content_type: str | None = None
    byte_size: int
    checksum_sha256: str
    format: str | None = Field(None, description="Container/codec reported by the decoder.")
    duration_seconds: float
    sample_rate_hz: int = Field(description="Sample rate of the uploaded file.")
    channels: int
    bit_depth: int | None = None
    captured_at: datetime | None = None
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    site_name: str | None = None
    recorder_type: str | None = None
    notes: str | None = None


# ------------------------------------------------------------------ quality


class QualityCheck(_Model):
    name: str
    value: float | None = None
    unit: str | None = None
    status: Literal["pass", "warn", "fail"]
    message: str


class QualityReport(_Model):
    status: QualityStatus
    score: float = Field(ge=0, le=1, description="0..1 heuristic usability score.")
    peak_dbfs: float
    rms_dbfs: float
    clipping_fraction: float
    silence_fraction: float
    low_frequency_energy_fraction: float = Field(
        description="Share of energy below 200 Hz; high values suggest wind or handling noise."
    )
    speech_detected: bool = Field(
        description="BirdNET 'Human vocal' above threshold in any window."
    )
    checks: list[QualityCheck]
    warnings: list[str]


# --------------------------------------------------------------- model runs


class ModelInfo(_Model):
    key: str = Field(description="Stable identifier used in requests, e.g. 'birdnet'.")
    name: str
    version: str
    taxa: list[str]
    status: Literal["ready", "loading", "unavailable", "disabled"]
    experimental: bool
    required_sample_rate_hz: int
    window_seconds: float
    license: str
    model_card_url: str | None = None
    description: str
    unavailable_reason: str | None = None


class ModelRun(_Model):
    id: str
    adapter: str
    model: str
    version: str
    model_sha256: str | None = None
    taxa: list[str]
    experimental: bool
    required_sample_rate_hz: int
    window_seconds: float
    hop_seconds: float
    raw_threshold: float = Field(
        description="Ingestion floor: raw windows below it are not stored."
    )
    configuration: dict
    runtime_ms: int
    n_windows: int


# ---------------------------------------------------------------- detections


class RawDetection(_Model):
    id: str
    model_run_id: str
    label_raw: str
    scientific_name: str
    common_name: str
    taxon: Taxon
    start_seconds: float
    end_seconds: float
    confidence: float = Field(ge=0, le=1)
    plausibility: Literal["plausible", "unlikely", "unknown"] = "unknown"


class DetectionEvent(_Model):
    """One consolidated detection event at the requested decision threshold.

    ``scientific_name``, ``common_name`` and ``taxon`` are the species the event
    counts under: the model's label, or the reviewer's correction when an event
    was corrected to a label the models know. ``detected_*`` always hold the
    model's own label, so a correction never hides what the model said.
    """

    id: str
    scientific_name: str = Field(description="Species the event counts under (see detected_*).")
    common_name: str
    taxon: Taxon
    detected_scientific_name: str = Field(description="The model's label for this event.")
    detected_common_name: str
    detected_taxon: Taxon
    model_run_id: str
    start_seconds: float
    end_seconds: float
    max_confidence: float = Field(description="Model score for the detected label.")
    mean_confidence: float
    n_windows: int
    contributing_detection_ids: list[str]
    plausibility: Literal["plausible", "unlikely", "unknown"] = Field(
        "unknown",
        description="Range and season check of the detected label; reviews do not change it.",
    )
    review_status: ReviewStatus = ReviewStatus.unreviewed
    reviewed_label: str | None = None
    review_note: str | None = None
    counted_in_metrics: bool = Field(
        description=(
            "True when the event is in the counted set behind species, metrics and charts: "
            "a wildlife taxon, not rejected, and not flagged unlikely unless a reviewer "
            "accepted or corrected it."
        )
    )


class SpeciesSummary(_Model):
    scientific_name: str
    common_name: str
    taxon: Taxon
    model_run_ids: list[str]
    detection_event_count: int
    raw_detection_count: int
    max_confidence: float
    mean_confidence: float
    total_event_duration_seconds: float
    first_detection_seconds: float
    last_detection_seconds: float
    plausibility: Literal["plausible", "unlikely", "unknown"] = "unknown"


class SpeciesRef(_Model):
    scientific_name: str
    common_name: str


class Metrics(_Model):
    species_richness: int
    shannon_index: float
    pielou_evenness: float
    simpson_diversity: float = Field(description="Gini-Simpson, 1 - sum(p_i^2).")
    total_detection_events: int
    raw_detection_count: int
    events_per_minute: float
    dominant_species: SpeciesRef | None
    events_by_taxon: dict[str, int]
    basis: str = Field(
        default="detection_events",
        description="Metrics use consolidated detection events above the decision threshold.",
    )


class AcousticIndices(_Model):
    """Signal-level soundscape indices, independent of any species model."""

    acoustic_complexity_index: float
    acoustic_diversity_index: float
    acoustic_evenness_index: float
    bioacoustic_index: float
    ndsi: float = Field(description="Normalized Difference Soundscape Index, -1..1.")
    spectral_entropy: float
    temporal_entropy: float


class AnalysisSettings(_Model):
    decision_threshold: float
    raw_threshold: float
    merge_gap_seconds: float
    hop_seconds: float
    requested_models: list[str]
    location_filter: bool
    location_filter_threshold: float


class Assets(_Model):
    audio_url: str | None = Field(description="Null unless audio retention is enabled.")
    spectrogram_url: str | None
    spectrogram_min_hz: int = 0
    spectrogram_max_hz: int = 16000
    csv_url: str
    json_url: str


class Preview(_Model):
    """Result of POST /api/v1/previews: decode, facts, QC and spectrogram, no model."""

    id: str
    recording: RecordingInfo
    quality: QualityReport
    spectrogram_url: str
    spectrogram_min_hz: int = 0
    spectrogram_max_hz: int = 16000
    expires_at: datetime


class Analysis(_Model):
    schema_version: str = SCHEMA_VERSION
    id: str
    status: AnalysisStatus
    stage: str | None = None
    recording: RecordingInfo | None
    quality: QualityReport | None
    settings: AnalysisSettings
    model_runs: list[ModelRun]
    metrics: Metrics | None
    acoustic_indices: AcousticIndices | None = None
    species: list[SpeciesSummary]
    events: list[DetectionEvent]
    raw_detections: list[RawDetection]
    assets: Assets
    warnings: list[str]
    error_code: ErrorCode | None = None
    error_message: str | None = None
    software_version: str
    created_at: datetime
    completed_at: datetime | None = None
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)


class ExportMetadata(_Model):
    exported_at: datetime
    software_version: str
    schema_version: str
    decision_threshold: float
    note: str


class AnalysisExport(Analysis):
    """JSON export: the Analysis at one decision threshold plus export provenance."""

    export_metadata: ExportMetadata


class AnalysisSummary(_Model):
    id: str
    status: AnalysisStatus
    filename: str | None
    site_name: str | None
    created_at: datetime
    duration_seconds: float | None
    species_richness: int | None
    total_detection_events: int | None
    decision_threshold: float
    top_species: list[str]


class AnalysisList(_Model):
    items: list[AnalysisSummary]


class EventReviewUpdate(_Model):
    review_status: ReviewStatus
    reviewed_label: str | None = None
    review_note: str | None = None


class HealthResponse(_Model):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    models: dict[str, str]
    ffmpeg: bool


class ModelsResponse(_Model):
    models: list[ModelInfo]

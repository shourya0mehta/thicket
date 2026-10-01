"""Platform contract: accounts, farms, sites, recorders, batch ingestion,
dashboards, seasonal series, alerts, recorder health, notifications, reports.

Everything the multi-tenant web app consumes is defined here, once, and
exported to ``shared/api.schema.json`` next to the single-analysis contract in
``schemas.py``. Rules carried over from that module: ``extra="forbid"``,
explicit scientific/common names, never the words individuals, population or
abundance for counts.

Tenancy
-------
Every resource except users, invites and notifications belongs to exactly one
organization (a farm, ranch, land trust, agency or lab). Routes are scoped by
path (``/api/v1/orgs/{org_id}/...``); membership roles gate writes:

* ``owner``: everything, including members and deletion of the organization
* ``manager``: sites, recorders, uploads, alerts, reports, settings
* ``reviewer``: review events, acknowledge alerts, create reports
* ``viewer``: read only

When ``AUTH_MODE=disabled`` (local single-user install, tests, CLI) the server
creates one implicit organization ("Local workspace") and one implicit owner,
so every route works without a login and the single-recording workspace keeps
behaving as before.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from thicket.api.schemas import (
    AnalysisStatus,
    QualityStatus,
    SpeciesRef,
    Taxon,
)

PLATFORM_SCHEMA_VERSION = "0.1.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ------------------------------------------------------------------ auth


class AuthMode(StrEnum):
    disabled = "disabled"  # implicit local workspace, no login
    dev = "dev"  # email-only sign-in form, development only
    google = "google"  # Google OpenID Connect


class AuthConfig(_Model):
    mode: AuthMode
    google_client_id: str | None = None
    sign_in_url: str | None = Field(None, description="Where the sign-in button sends the browser.")
    allowed_domains: list[str] = Field(default_factory=list)


class Role(StrEnum):
    owner = "owner"
    manager = "manager"
    reviewer = "reviewer"
    viewer = "viewer"


class User(_Model):
    id: str
    email: str
    name: str
    picture_url: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class OrganizationKind(StrEnum):
    farm = "farm"
    ranch = "ranch"
    land_trust = "land_trust"
    restoration_project = "restoration_project"
    agency = "agency"
    research = "research"
    other = "other"


class Organization(_Model):
    id: str
    name: str
    slug: str
    kind: OrganizationKind
    timezone: str = Field(description="IANA zone used for day boundaries in rollups.")
    country: str | None = None
    region: str | None = Field(None, description="State or province, e.g. NY.")
    created_at: datetime
    member_count: int = 0
    site_count: int = 0


class OrganizationCreate(_Model):
    name: str = Field(min_length=1, max_length=120)
    kind: OrganizationKind = OrganizationKind.farm
    timezone: str = "America/New_York"
    country: str | None = None
    region: str | None = None


class OrganizationUpdate(_Model):
    name: str | None = None
    kind: OrganizationKind | None = None
    timezone: str | None = None
    country: str | None = None
    region: str | None = None


class Membership(_Model):
    user: User
    role: Role
    joined_at: datetime


class MembershipUpdate(_Model):
    role: Role


class Invite(_Model):
    id: str
    organization_id: str
    email: str
    role: Role
    invited_by: str
    expires_at: datetime
    accepted_at: datetime | None = None
    accept_url: str | None = Field(None, description="Only returned to the inviter at creation.")


class InviteCreate(_Model):
    email: str
    role: Role = Role.viewer


class Me(_Model):
    user: User
    organizations: list[Organization]
    roles: dict[str, Role] = Field(description="organization_id -> role")
    auth_mode: AuthMode
    unread_notifications: int = 0


class DevLogin(_Model):
    email: str
    name: str | None = None


# ------------------------------------------------------------------ sites


class HabitatType(StrEnum):
    pasture = "pasture"
    hayfield = "hayfield"
    cropland = "cropland"
    shrubland = "shrubland"
    forest = "forest"
    wetland = "wetland"
    riparian_buffer = "riparian_buffer"
    pond = "pond"
    farmstead = "farmstead"
    other = "other"


class SiteStats(_Model):
    recordings: int = 0
    minutes_recorded: float = 0
    first_recording_at: datetime | None = None
    last_recording_at: datetime | None = None
    species_counted: int = 0
    open_alerts: int = 0
    health: Literal["good", "watch", "attention", "unknown"] = "unknown"


class Site(_Model):
    id: str
    organization_id: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    habitat_type: HabitatType | None = None
    area_hectares: float | None = None
    fsa_field_number: str | None = None
    paddock_id: str | None = None
    notes: str | None = None
    created_at: datetime
    stats: SiteStats


class SiteCreate(_Model):
    name: str = Field(min_length=1, max_length=120)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    habitat_type: HabitatType | None = None
    area_hectares: float | None = Field(None, ge=0)
    fsa_field_number: str | None = None
    paddock_id: str | None = None
    notes: str | None = None


class SiteUpdate(SiteCreate):
    name: str | None = Field(None, min_length=1, max_length=120)  # type: ignore[assignment]


# ------------------------------------------------------- recorders, deployments


class RecorderMake(StrEnum):
    audiomoth = "audiomoth"
    song_meter = "song_meter"
    phone = "phone"
    handheld = "handheld"
    other = "other"


class Recorder(_Model):
    id: str
    organization_id: str
    label: str
    make: RecorderMake
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    notes: str | None = None
    created_at: datetime
    active_deployment_id: str | None = None
    health: Literal["good", "watch", "attention", "unknown"] = "unknown"
    last_recording_at: datetime | None = None


class RecorderCreate(_Model):
    label: str = Field(min_length=1, max_length=120)
    make: RecorderMake = RecorderMake.other
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    notes: str | None = None


class RecorderUpdate(_Model):
    label: str | None = None
    make: RecorderMake | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    notes: str | None = None


class Deployment(_Model):
    """A recorder placed at a site for a period. Health baselines are per deployment."""

    id: str
    organization_id: str
    recorder_id: str
    site_id: str
    started_at: datetime
    ended_at: datetime | None = None
    mount_height_m: float | None = None
    orientation: str | None = None
    gain_setting: str | None = None
    schedule_description: str | None = Field(
        None, description="Human text, e.g. 1 min every 5 min, dawn and dusk."
    )
    expected_interval_minutes: float | None = Field(
        None, description="Expected time between recordings; inferred when null."
    )
    expected_clip_seconds: float | None = None
    notes: str | None = None
    created_at: datetime


class DeploymentCreate(_Model):
    recorder_id: str
    site_id: str
    started_at: datetime
    ended_at: datetime | None = None
    mount_height_m: float | None = None
    orientation: str | None = None
    gain_setting: str | None = None
    schedule_description: str | None = None
    expected_interval_minutes: float | None = Field(None, gt=0)
    expected_clip_seconds: float | None = Field(None, gt=0)
    notes: str | None = None


class DeploymentUpdate(_Model):
    ended_at: datetime | None = None
    mount_height_m: float | None = None
    orientation: str | None = None
    gain_setting: str | None = None
    schedule_description: str | None = None
    expected_interval_minutes: float | None = Field(None, gt=0)
    expected_clip_seconds: float | None = Field(None, gt=0)
    notes: str | None = None


# ------------------------------------------------------ recordings, batches


class Telemetry(_Model):
    """Device readings parsed from the file (AudioMoth WAV comment, Song Meter summary)."""

    battery_v: float | None = None
    temperature_c: float | None = None
    gain: str | None = None
    device_id: str | None = None
    source: Literal["audiomoth_comment", "song_meter_summary", "guano", "none"] = "none"


class SignalProfile(_Model):
    """Per-recording signal statistics used for recorder health baselines."""

    rms_dbfs: float
    peak_dbfs: float
    clipping_fraction: float
    dc_offset: float
    band_fraction_0_1k: float
    band_fraction_1_4k: float
    band_fraction_4_8k: float
    band_fraction_8k_plus: float
    spectral_centroid_hz: float
    channel_rms_dbfs: list[float] = Field(description="Per channel, from the original file.")


class CapturedAtSource(StrEnum):
    filename = "filename"
    file_metadata = "file_metadata"
    user = "user"
    browser_last_modified = "browser_last_modified"
    unknown = "unknown"


class RecordingSummary(_Model):
    id: str
    organization_id: str
    site_id: str | None
    site_name: str | None
    deployment_id: str | None
    recorder_id: str | None
    filename: str
    duration_seconds: float
    captured_at: datetime | None
    captured_at_source: CapturedAtSource
    timezone: str | None
    latitude: float | None
    longitude: float | None
    telemetry: Telemetry
    analysis_id: str | None
    analysis_status: AnalysisStatus | None
    quality_status: QualityStatus | None
    species_richness: int | None
    total_detection_events: int | None
    decision_threshold: float | None
    created_at: datetime


class RecordingPage(_Model):
    items: list[RecordingSummary]
    total: int
    page: int
    page_size: int


class BatchItemStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class BatchItem(_Model):
    filename: str
    status: BatchItemStatus
    recording_id: str | None = None
    analysis_id: str | None = None
    captured_at: datetime | None = None
    captured_at_source: CapturedAtSource = CapturedAtSource.unknown
    telemetry: Telemetry | None = None
    error_code: str | None = None
    error_message: str | None = None


class BatchJob(_Model):
    id: str
    organization_id: str
    site_id: str | None
    deployment_id: str | None
    status: Literal["queued", "processing", "completed", "completed_with_errors", "failed"]
    total: int
    done: int
    failed: int
    skipped: int
    items: list[BatchItem]
    settings: dict = Field(description="Effective models, threshold, timezone, parse options.")
    created_at: datetime
    completed_at: datetime | None = None
    sidecars_parsed: list[str] = Field(
        default_factory=list, description="Summary or config files that were read."
    )


# ---------------------------------------------------------- dashboard


class DayPoint(_Model):
    date: date
    site_id: str | None = None
    recordings: int
    minutes: float
    species_richness: int
    detection_events: int
    events_per_minute: float
    shannon_index: float | None = None
    usable_fraction: float | None = None


class TaxonCount(_Model):
    taxon: Taxon
    detection_events: int
    species: int


class SpeciesRollup(_Model):
    scientific_name: str
    common_name: str
    taxon: Taxon
    detection_events: int
    recordings_with_detection: int
    recordings_total: int
    presence_fraction: float = Field(description="recordings_with_detection / recordings_total")
    max_confidence: float
    first_detected_at: datetime | None
    last_detected_at: datetime | None
    site_ids: list[str]
    is_priority: bool = False
    plausibility: Literal["plausible", "unlikely", "unknown"] = "unknown"


class HeatCell(_Model):
    weekday: int = Field(ge=0, le=6, description="0 = Monday")
    hour: int = Field(ge=0, le=23)
    recordings: int
    events_per_minute: float


class IndexPoint(_Model):
    date: date
    site_id: str | None = None
    acoustic_complexity_index: float | None = None
    acoustic_diversity_index: float | None = None
    bioacoustic_index: float | None = None
    ndsi: float | None = None


class Dashboard(_Model):
    organization_id: str
    period_start: date
    period_end: date
    site_ids: list[str]
    recordings: int
    minutes_recorded: float
    species_counted: int
    detection_events: int
    richness_by_day: list[DayPoint]
    species: list[SpeciesRollup]
    by_taxon: list[TaxonCount]
    activity_heatmap: list[HeatCell]
    indices_by_day: list[IndexPoint]
    quality: dict[str, int] = Field(description="usable / usable_with_warnings / not_usable counts")
    open_alerts: int
    baseline_note: str = Field(description="Plain text on how much history the baselines have.")
    generated_at: datetime


class PhenologyCell(_Model):
    year: int
    iso_week: int = Field(ge=1, le=53)
    recordings: int
    recordings_with_detection: int
    presence_fraction: float
    events_per_minute: float


class Phenology(_Model):
    organization_id: str
    site_ids: list[str]
    species: SpeciesRef
    taxon: Taxon
    cells: list[PhenologyCell]
    first_detection_by_year: dict[int, date]
    last_detection_by_year: dict[int, date]


class AccumulationPoint(_Model):
    recording_index: int
    captured_at: datetime | None
    cumulative_species: int


class Accumulation(_Model):
    site_id: str
    points: list[AccumulationPoint]
    note: str = "Cumulative distinct species counted across recordings in time order. Flattening suggests the common vocal species have been found; it is not a completeness estimate."


class SiteComparisonRow(_Model):
    site: Site
    recordings: int
    minutes: float
    species_richness: int
    events_per_minute: float
    shannon_index: float | None
    top_species: list[SpeciesRef]
    usable_fraction: float | None


class SiteComparison(_Model):
    period_start: date
    period_end: date
    rows: list[SiteComparisonRow]


# ------------------------------------------------------------- alerts


class AlertKind(StrEnum):
    # ecology
    richness_drop = "richness_drop"
    activity_drop = "activity_drop"
    new_species_for_site = "new_species_for_site"
    priority_species_detected = "priority_species_detected"
    expected_species_missing = "expected_species_missing"
    species_surge = "species_surge"
    # data quality
    low_quality_streak = "low_quality_streak"
    speech_detected = "speech_detected"
    # recorder health
    muffled_audio = "muffled_audio"
    level_drift = "level_drift"
    recording_gap = "recording_gap"
    clipping_increase = "clipping_increase"
    channel_imbalance = "channel_imbalance"
    dc_offset = "dc_offset"
    battery_low = "battery_low"
    temperature_extreme = "temperature_extreme"
    clock_suspect = "clock_suspect"
    schedule_deviation = "schedule_deviation"
    # Upload time, not recording time: a regularly uploading deployment went quiet.
    upload_overdue = "upload_overdue"


class AlertSeverity(StrEnum):
    info = "info"
    watch = "watch"
    warning = "warning"


class AlertStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
    snoozed = "snoozed"


class Alert(_Model):
    id: str
    organization_id: str
    kind: AlertKind
    category: Literal["ecology", "quality", "recorder"]
    severity: AlertSeverity
    status: AlertStatus
    title: str
    detail: str = Field(description="Plain-language explanation with the numbers behind it.")
    suggested_action: str | None = None
    evidence: dict = Field(
        description="Machine-readable numbers: observed, baseline median, MAD, n, window."
    )
    site_id: str | None = None
    recorder_id: str | None = None
    deployment_id: str | None = None
    species: SpeciesRef | None = None
    recording_ids: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int = 1
    acknowledged_by: str | None = None
    note: str | None = None
    snoozed_until: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AlertPage(_Model):
    items: list[Alert]
    total: int
    counts_by_status: dict[str, int]
    counts_by_category: dict[str, int]


class AlertUpdate(_Model):
    status: AlertStatus
    note: str | None = None
    snoozed_until: datetime | None = None


class AlertRules(_Model):
    """Per-organization tuning. Defaults are conservative; alerts need a baseline first."""

    enabled: bool = True
    min_baseline_recordings: int = Field(
        8, ge=3, description="Recordings needed before ecology alerts fire."
    )
    richness_drop_mad: float = Field(
        3.0, gt=0, description="Robust z (MAD units) below baseline median."
    )
    activity_drop_mad: float = Field(3.0, gt=0)
    species_surge_mad: float = Field(4.0, gt=0)
    consecutive_recordings: int = Field(
        3, ge=1, description="How many recordings in a row must agree."
    )
    expected_species_min_presence: float = Field(
        0.5,
        ge=0,
        le=1,
        description="Historical presence fraction for a species to be expected this week.",
    )
    expected_species_missing_recordings: int = Field(6, ge=2)
    priority_species: list[str] = Field(default_factory=list, description="Scientific names.")
    gap_multiplier: float = Field(
        3.0, gt=1, description="Gap longer than this many median intervals is a recording gap."
    )
    gap_min_hours: float = Field(2.0, gt=0)
    battery_low_v: dict[str, float] = Field(
        default_factory=lambda: {"audiomoth": 3.6, "song_meter": 4.6, "other": 3.6},
        description="Per recorder make. Below this a battery alert opens.",
    )
    temperature_min_c: float = -20.0
    temperature_max_c: float = 50.0
    low_quality_streak: int = Field(3, ge=2)


class NotificationPrefs(_Model):
    email_enabled: bool = False
    email_digest: Literal["immediate", "daily", "weekly", "off"] = "daily"
    min_severity: AlertSeverity = AlertSeverity.watch
    categories: list[Literal["ecology", "quality", "recorder"]] = Field(
        default_factory=lambda: ["ecology", "quality", "recorder"]
    )


class Notification(_Model):
    id: str
    alert: Alert
    channel: Literal["in_app", "email"]
    created_at: datetime
    read_at: datetime | None = None
    sent_at: datetime | None = None


class NotificationPage(_Model):
    items: list[Notification]
    unread: int


# ------------------------------------------------------ recorder health


class SeriesPoint(_Model):
    t: datetime
    v: float


class Gap(_Model):
    start: datetime
    end: datetime
    hours: float
    expected_recordings: int | None = None


class HealthCheck(_Model):
    name: str
    status: Literal["good", "watch", "attention", "unknown"]
    message: str
    value: float | None = None
    baseline: float | None = None


class RecorderHealth(_Model):
    recorder: Recorder
    deployment: Deployment | None
    status: Literal["good", "watch", "attention", "unknown"]
    checks: list[HealthCheck]
    last_recording_at: datetime | None
    recordings_last_7d: int
    expected_last_7d: int | None
    uptime_fraction_7d: float | None
    median_interval_minutes: float | None
    battery: list[SeriesPoint]
    temperature: list[SeriesPoint]
    level_dbfs: list[SeriesPoint]
    high_band_fraction: list[SeriesPoint] = Field(
        description="band_fraction_4_8k + band_fraction_8k_plus per recording."
    )
    spectral_centroid_hz: list[SeriesPoint]
    clipping_fraction: list[SeriesPoint]
    gaps: list[Gap]
    open_alerts: list[Alert]
    baseline_note: str


# ------------------------------------------------------------ reports


class ReportTemplateKey(StrEnum):
    evidence = "evidence"
    nrcs = "nrcs"
    aem = "aem"
    certification = "certification"
    credit = "credit"


class ReportField(_Model):
    name: str
    type: Literal[
        "string", "text", "date", "datetime", "number", "integer", "boolean", "enum", "list", "file"
    ]
    group: str
    templates: list[ReportTemplateKey]
    label: str
    help: str | None = None
    required: bool = False
    options: list[str] | None = None
    example: object | None = None


class ReportTemplate(_Model):
    key: ReportTemplateKey
    title: str
    audience: str
    description: str
    pages: list[str]
    fields: list[ReportField]


class ReportTemplates(_Model):
    templates: list[ReportTemplate]


class ReportCreate(_Model):
    template: ReportTemplateKey
    title: str = Field(min_length=1, max_length=200)
    site_ids: list[str] = Field(default_factory=list, description="Empty means all sites.")
    period_start: date
    period_end: date
    baseline_start: date | None = None
    baseline_end: date | None = None
    decision_threshold: float | None = Field(
        None, description="Defaults to each analysis's own threshold."
    )
    include_review_log: bool = True
    include_raw_manifest: bool = True
    fields: dict[str, object] = Field(
        default_factory=dict, description="Values for ReportTemplate.fields."
    )


class Report(_Model):
    id: str
    organization_id: str
    template: ReportTemplateKey
    title: str
    status: Literal["queued", "rendering", "ready", "failed"]
    created_by: str
    created_at: datetime
    completed_at: datetime | None = None
    period_start: date
    period_end: date
    site_ids: list[str]
    analysis_count: int
    page_count: int | None = None
    pdf_url: str | None = None
    json_url: str | None = None
    checksum_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(
        default_factory=list, description="Template fields left blank."
    )
    error_message: str | None = None


class ReportList(_Model):
    items: list[Report]


class UploadedFile(_Model):
    id: str
    organization_id: str
    filename: str
    content_type: str
    byte_size: int
    url: str
    created_at: datetime

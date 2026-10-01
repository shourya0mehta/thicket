"""SQLAlchemy 2.0 schema and engine.

SQLite by default, Postgres-compatible types throughout (String with
lengths, Float, Integer, Boolean, JSON, timezone-aware DateTime).

What is stored: sites, recordings (file facts and user metadata, never
audio bytes), analyses (settings, QC, indices, warnings, stage timings),
model runs, raw window detections above the ingestion floor, and event
reviews. Events, species tables and metrics are *derived on read* from raw
detections at the requested threshold (see :mod:`thicket.services.results`),
so there is one code path for every threshold.

Platform tables (schema 3; schema 4 adds ``alerts.open_key``): users,
organizations, memberships, invites,
revoked sessions, recorders, deployments, batch jobs and items, per-recording
stats, site and species day rollups, alerts and alert rules, notifications
and preferences, reports and uploaded files. Every tenant resource carries
``organization_id``.

``event_refs`` records which analysis an event id belongs to, the first time
the event is served, so ``PATCH /events/{event_id}`` can find it (event ids
are hashes and cannot be inverted).

Schema versioning: ``schema_meta`` holds one row per applied schema version.
Tables are created with ``create_all`` at startup, columns added since an
older version are added by :func:`_migrate`, and a database written by a
newer version refuses to start.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from thicket.ids import LOCAL_ORG_ID, LOCAL_USER_ID

DB_SCHEMA_VERSION = 4

LOCAL_ORG_NAME = "Local workspace"
LOCAL_ORG_SLUG = "local"
LOCAL_USER_EMAIL = "local@thicket.invalid"
LOCAL_USER_NAME = "Local user"


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """An aware UTC datetime; naive values are read as UTC, as the storage layer does."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class SchemaMeta(Base):
    __tablename__ = "schema_meta"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ------------------------------------------------------------- tenancy


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class OrganizationRow(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="farm")
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MembershipRow(Base):
    __tablename__ = "memberships"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InviteRow(Base):
    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(20))
    # SHA-256 of the url-safe token; the token itself is only shown once.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RevokedSessionRow(Base):
    """Server-side revocation list for the stateless signed session cookie."""

    __tablename__ = "revoked_sessions"
    session_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    revoked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # When the cookie itself would have expired; rows past this can be pruned.
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


# ------------------------------------------------------- sites and recorders


class SiteRow(Base):
    __tablename__ = "sites"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Schema 3
    organization_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    habitat_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    area_hectares: Mapped[float | None] = mapped_column(Float, nullable=True)
    fsa_field_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    paddock_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True for sites created implicitly from a recording's ``site_name``; those
    # are removed again once no recording uses them. Explicit sites persist.
    auto_created: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class RecorderRow(Base):
    __tablename__ = "recorders"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120))
    make: Mapped[str] = mapped_column(String(40), default="other")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(120), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeploymentRow(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    recorder_id: Mapped[str] = mapped_column(
        ForeignKey("recorders.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    mount_height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    orientation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gain_setting: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schedule_description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    expected_interval_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_clip_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# -------------------------------------------------------------- recordings


class RecordingRow(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    site_id: Mapped[str | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float)
    sample_rate_hz: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    site_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recorder_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Schema 3
    organization_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    deployment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    recorder_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    captured_at_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    captured_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    telemetry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    signal_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    batch_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)


class AnalysisRow(Base):
    __tablename__ = "analyses"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), index=True)
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requested_models: Mapped[list] = mapped_column(JSON)
    decision_threshold: Mapped[float] = mapped_column(Float)
    raw_threshold: Mapped[float] = mapped_column(Float)
    merge_gap_seconds: Mapped[float] = mapped_column(Float)
    hop_seconds: Mapped[float] = mapped_column(Float)
    location_filter: Mapped[bool] = mapped_column(Boolean)
    location_filter_threshold: Mapped[float] = mapped_column(Float)
    quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acoustic_indices: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    software_version: Mapped[str] = mapped_column(String(40))
    stage_timings: Mapped[dict] = mapped_column(JSON, default=dict)
    has_spectrogram: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ModelRunRow(Base):
    __tablename__ = "model_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    adapter: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40))
    model_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    taxa: Mapped[list] = mapped_column(JSON)
    experimental: Mapped[bool] = mapped_column(Boolean)
    required_sample_rate_hz: Mapped[int] = mapped_column(Integer)
    window_seconds: Mapped[float] = mapped_column(Float)
    hop_seconds: Mapped[float] = mapped_column(Float)
    raw_threshold: Mapped[float] = mapped_column(Float)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    runtime_ms: Mapped[int] = mapped_column(Integer)
    n_windows: Mapped[int] = mapped_column(Integer)


class RawDetectionRow(Base):
    __tablename__ = "raw_detections"
    __table_args__ = (
        UniqueConstraint("analysis_id", "detection_id", name="uq_raw_detection"),
        Index("ix_raw_detections_analysis", "analysis_id"),
    )
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    detection_id: Mapped[str] = mapped_column(String(40))
    model_run_id: Mapped[str] = mapped_column(String(40))
    label_raw: Mapped[str] = mapped_column(String(300))
    scientific_name: Mapped[str] = mapped_column(String(200))
    common_name: Mapped[str] = mapped_column(String(200))
    taxon: Mapped[str] = mapped_column(String(40))
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    plausibility: Mapped[str] = mapped_column(String(20))


class EventReviewRow(Base):
    __tablename__ = "event_reviews"
    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    review_status: Mapped[str] = mapped_column(String(20))
    reviewed_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_scientific_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolved_common_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolved_taxon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Raw detection ids the reviewed event was made of (schema 2). The review
    # follows these windows across thresholds; NULL for reviews written by
    # schema 1, which still apply by event id only.
    detection_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Schema 3: who reviewed (user id), for the report review log.
    reviewed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)


class EventRefRow(Base):
    __tablename__ = "event_refs"
    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    # Raw detection ids of the event when it was first served (schema 2).
    detection_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


# -------------------------------------------------------------- batches


class BatchJobRow(Base):
    __tablename__ = "batch_jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    deployment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recorder_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    sidecars_parsed: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BatchItemRow(Base):
    __tablename__ = "batch_items"
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("batch_jobs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    recording_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    analysis_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    captured_at_source: Mapped[str] = mapped_column(String(40), default="unknown")
    telemetry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------- rollups


class RecordingStatsRow(Base):
    """One derived summary per completed analysis, at its own threshold.

    Maintained by the rollup service (after completion, after a review, and
    in the nightly rebuild) so dashboards, baselines and alerts never have to
    re-derive thousands of analyses. ``species`` maps scientific name to
    ``[common_name, taxon, events, max_confidence, plausibility]``.
    """

    __tablename__ = "recording_stats"
    recording_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(40), index=True)
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    site_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    recorder_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    deployment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    local_hour: Mapped[int] = mapped_column(Integer)
    hour_bucket: Mapped[str] = mapped_column(String(10))
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    minutes: Mapped[float] = mapped_column(Float)
    richness: Mapped[int] = mapped_column(Integer)
    events: Mapped[int] = mapped_column(Integer)
    events_per_minute: Mapped[float] = mapped_column(Float)
    shannon: Mapped[float] = mapped_column(Float)
    quality_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    speech_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_threshold: Mapped[float] = mapped_column(Float)
    species: Mapped[dict] = mapped_column(JSON, default=dict)
    indices: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SiteDayStatsRow(Base):
    __tablename__ = "site_day_stats"
    site_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    recordings: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    richness: Mapped[int] = mapped_column(Integer, default=0)
    events: Mapped[int] = mapped_column(Integer, default=0)
    events_per_minute: Mapped[float] = mapped_column(Float, default=0.0)
    shannon: Mapped[float | None] = mapped_column(Float, nullable=True)
    usable_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    indices: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"usable": n, "usable_with_warnings": n, "not_usable": n}
    quality_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"<hour 0..23>": [recordings, events, minutes]} for the activity heatmap.
    activity: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SpeciesDayStatsRow(Base):
    __tablename__ = "species_day_stats"
    site_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    scientific_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    common_name: Mapped[str] = mapped_column(String(200))
    taxon: Mapped[str] = mapped_column(String(40))
    events: Mapped[int] = mapped_column(Integer, default=0)
    recordings_with_detection: Mapped[int] = mapped_column(Integer, default=0)
    max_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    first_detected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_detected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    plausibility: Mapped[str] = mapped_column(String(20), default="unknown")


# ---------------------------------------------------------------- alerts


OPEN_ALERT_STATUSES = ("open", "acknowledged", "snoozed")


def alert_open_key(organization_id: str, dedupe_key: str, status: str) -> str | None:
    """``alerts.open_key``: unique while an alert is open, acknowledged or snoozed."""
    return f"{organization_id}|{dedupe_key}" if status in OPEN_ALERT_STATUSES else None


class AlertRow(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_org_status", "organization_id", "status"),
        # At most one unresolved alert per (organization, dedupe key), enforced by the
        # database so two workers raising the same alert cannot both insert one.
        # NULL once resolved; unique indexes allow many NULLs (SQLite and Postgres).
        Index("ux_alerts_open_key", "open_key", unique=True),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    site_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    recorder_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    deployment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    species_scientific_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    species_common_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recording_ids: Mapped[list] = mapped_column(JSON, default=list)
    # kind|site|recorder|species, the deduplication key for open alerts.
    dedupe_key: Mapped[str] = mapped_column(String(400), index=True)
    open_key: Mapped[str | None] = mapped_column(String(460), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AlertRulesRow(Base):
    __tablename__ = "alert_rules"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class NotificationRow(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[str] = mapped_column(String(40), index=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    # email only: immediate | daily | weekly (when the message should go out)
    digest: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class NotificationPrefsRow(Base):
    __tablename__ = "notification_prefs"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------- reports


class ReportRow(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    template: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    baseline_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    site_ids: Mapped[list] = mapped_column(JSON, default=list)
    decision_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    include_review_log: Mapped[bool] = mapped_column(Boolean, default=True)
    include_raw_manifest: Mapped[bool] = mapped_column(Boolean, default=True)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bundle_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bundle_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)


class UploadedFileRow(Base):
    __tablename__ = "uploaded_files"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(Integer)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SchemaVersionError(RuntimeError):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        kwargs: dict = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url or url.rstrip("/") in ("sqlite:", "sqlite+pysqlite:"):
                kwargs["poolclass"] = StaticPool
            else:
                path = url.split("///", 1)[-1]
                if path:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> int | None:
        """Create tables, migrate an older schema; return the version migrated from, if any."""
        Base.metadata.create_all(self.engine)
        migrated_from: int | None = None
        with self.session() as s:
            row = (
                s.execute(select(SchemaMeta).order_by(SchemaMeta.version.desc())).scalars().first()
            )
            if row is None:
                s.add(SchemaMeta(version=DB_SCHEMA_VERSION))
            elif row.version > DB_SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"Database schema version {row.version} is newer than this build "
                    f"({DB_SCHEMA_VERSION}). Upgrade Thicket."
                )
            elif row.version < DB_SCHEMA_VERSION:
                migrated_from = row.version
                _migrate(s, row.version)
                s.add(SchemaMeta(version=DB_SCHEMA_VERSION))
        with self.session() as s:
            ensure_local_workspace(s)
        return migrated_from

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._sessions()
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()


# Columns added after schema 1: (version that added them, table, column, DDL type).
_ADDED_COLUMNS = [
    (2, "event_reviews", "detection_ids", "JSON"),
    (2, "event_refs", "detection_ids", "JSON"),
    (3, "event_reviews", "reviewed_by", "VARCHAR(40)"),
    (3, "sites", "organization_id", "VARCHAR(40)"),
    (3, "sites", "habitat_type", "VARCHAR(40)"),
    (3, "sites", "area_hectares", "FLOAT"),
    (3, "sites", "fsa_field_number", "VARCHAR(80)"),
    (3, "sites", "paddock_id", "VARCHAR(80)"),
    (3, "sites", "notes", "TEXT"),
    (3, "sites", "auto_created", "BOOLEAN"),
    (3, "recordings", "organization_id", "VARCHAR(40)"),
    (3, "recordings", "deployment_id", "VARCHAR(40)"),
    (3, "recordings", "recorder_id", "VARCHAR(40)"),
    (3, "recordings", "captured_at_source", "VARCHAR(40)"),
    (3, "recordings", "source_filename", "VARCHAR(255)"),
    (3, "recordings", "captured_at_utc", "TIMESTAMP"),
    (3, "recordings", "telemetry", "JSON"),
    (3, "recordings", "signal_profile", "JSON"),
    (3, "recordings", "batch_job_id", "VARCHAR(40)"),
    (4, "alerts", "open_key", "VARCHAR(460)"),
]


def _migrate(s: Session, from_version: int) -> None:
    """Bring an older database up to :data:`DB_SCHEMA_VERSION`.

    ``create_all`` adds missing tables but never columns, so added nullable
    columns are created here with ``ALTER TABLE ... ADD COLUMN`` (valid on
    SQLite and Postgres). Existing rows keep NULL, which every reader handles.
    Schema 3 then creates the implicit local workspace and attaches every
    site and recording without an organization to it.
    """
    conn = s.connection()
    for version, table, column, ddl in _ADDED_COLUMNS:
        if version <= from_version:
            continue
        existing = {c["name"] for c in inspect(conn).get_columns(table)}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    if from_version < 3:
        ensure_local_workspace(s)
        conn.execute(
            text("UPDATE sites SET organization_id = :org WHERE organization_id IS NULL"),
            {"org": LOCAL_ORG_ID},
        )
        # Every site before schema 3 came from a recording's site_name.
        conn.execute(
            update(SiteRow).where(SiteRow.auto_created.is_(None)).values(auto_created=True)
        )
        conn.execute(
            text("UPDATE recordings SET organization_id = :org WHERE organization_id IS NULL"),
            {"org": LOCAL_ORG_ID},
        )
        conn.execute(
            text(
                "UPDATE recordings SET captured_at_source = 'user' "
                "WHERE captured_at_source IS NULL AND captured_at IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE recordings SET captured_at_source = 'unknown' "
                "WHERE captured_at_source IS NULL"
            )
        )
        _local_workspace_timezone_from_recordings(conn)
    if from_version < 4:
        _fill_open_alert_keys(s)
    # create_all() only builds indexes together with new tables; the columns added
    # above to existing tables (recordings.organization_id, captured_at_utc...)
    # would otherwise stay unindexed on upgraded databases.
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(conn, checkfirst=True)


def _fill_open_alert_keys(s: Session) -> None:
    """Schema 4: key every unresolved alert. Should duplicates exist from before the
    constraint, the newest keeps the key and the older ones are resolved into it."""
    rows = s.execute(
        select(AlertRow)
        .where(AlertRow.status.in_(OPEN_ALERT_STATUSES))
        .order_by(AlertRow.created_at.desc(), AlertRow.id)
    ).scalars()
    seen: set[str] = set()
    for row in rows:
        key = alert_open_key(row.organization_id, row.dedupe_key, row.status)
        if key in seen:
            row.status = "resolved"
            row.open_key = None
            row.note = row.note or "Resolved during the upgrade: a newer alert covers this."
            continue
        seen.add(key)  # type: ignore[arg-type]
        row.open_key = key
    s.flush()


def _local_workspace_timezone_from_recordings(conn) -> None:  # type: ignore[no-untyped-def]
    """The single-user build stored a time zone per recording, not per workspace.

    Rollups put recordings on local dates in the organization's zone, so leaving
    the upgraded workspace on UTC would move every evening recording west of
    Greenwich to the next day. Use the zone most recordings declare.
    """
    row = conn.execute(
        text(
            "SELECT timezone, COUNT(*) AS n FROM recordings "
            "WHERE timezone IS NOT NULL AND timezone <> '' "
            "GROUP BY timezone ORDER BY n DESC, timezone LIMIT 1"
        )
    ).first()
    if row is None:
        return
    try:
        ZoneInfo(str(row[0]))
    except (ZoneInfoNotFoundError, ValueError):
        return
    conn.execute(
        text("UPDATE organizations SET timezone = :tz WHERE id = :org AND timezone = 'UTC'"),
        {"tz": str(row[0]), "org": LOCAL_ORG_ID},
    )


def ensure_local_workspace(s: Session) -> None:
    """Create the implicit local user, organization and owner membership (idempotent).

    They exist in every mode so a database can move between AUTH_MODE values:
    with sign-in enabled the local user simply has no way to log in.
    """
    if s.get(UserRow, LOCAL_USER_ID) is None:
        s.add(
            UserRow(
                id=LOCAL_USER_ID,
                email=LOCAL_USER_EMAIL,
                name=LOCAL_USER_NAME,
            )
        )
    if s.get(OrganizationRow, LOCAL_ORG_ID) is None:
        s.add(
            OrganizationRow(
                id=LOCAL_ORG_ID,
                name=LOCAL_ORG_NAME,
                slug=LOCAL_ORG_SLUG,
                kind="other",
                timezone="UTC",
            )
        )
    s.flush()
    if s.get(MembershipRow, (LOCAL_ORG_ID, LOCAL_USER_ID)) is None:
        s.add(MembershipRow(organization_id=LOCAL_ORG_ID, user_id=LOCAL_USER_ID, role="owner"))
    s.flush()


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    try:
        cur.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001 - in-memory databases do not support WAL
        pass
    cur.close()

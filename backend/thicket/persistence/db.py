"""SQLAlchemy 2.0 schema and engine.

SQLite by default, Postgres-compatible types throughout (String with
lengths, Float, Integer, Boolean, JSON, timezone-aware DateTime).

What is stored: sites, recordings (file facts and user metadata, never
audio bytes), analyses (settings, QC, indices, warnings, stage timings),
model runs, raw window detections above the ingestion floor, and event
reviews. Events, species tables and metrics are *derived on read* from raw
detections at the requested threshold (see :mod:`thicket.services.results`),
so there is one code path for every threshold.

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
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
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
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DB_SCHEMA_VERSION = 2


def utcnow() -> datetime:
    return datetime.now(UTC)


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


class SiteRow(Base):
    __tablename__ = "sites"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


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


class EventRefRow(Base):
    __tablename__ = "event_refs"
    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    # Raw detection ids of the event when it was first served (schema 2).
    detection_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


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

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
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
                _migrate(s, row.version)
                s.add(SchemaMeta(version=DB_SCHEMA_VERSION))

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
]


def _migrate(s: Session, from_version: int) -> None:
    """Bring an older database up to :data:`DB_SCHEMA_VERSION`.

    ``create_all`` adds missing tables but never columns, so added nullable
    columns are created here with ``ALTER TABLE ... ADD COLUMN`` (valid on
    SQLite and Postgres). Existing rows keep NULL, which every reader handles.
    """
    conn = s.connection()
    for version, table, column, ddl in _ADDED_COLUMNS:
        if version <= from_version:
            continue
        existing = {c["name"] for c in inspect(conn).get_columns(table)}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    try:
        cur.execute("PRAGMA journal_mode=WAL")
    except Exception:  # noqa: BLE001 - in-memory databases do not support WAL
        pass
    cur.close()

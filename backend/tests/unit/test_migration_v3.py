"""A database written by the single-user build (schema 2) upgrades in place to
schema 3: new columns are added, new tables created, the implicit local
workspace exists and old sites and recordings are attached to it."""

from sqlalchemy import create_engine, inspect, text

from thicket.ids import LOCAL_ORG_ID, LOCAL_USER_ID
from thicket.persistence.db import (
    DB_SCHEMA_VERSION,
    Database,
    MembershipRow,
    OrganizationRow,
    RecordingRow,
    SiteRow,
)
from thicket.persistence.platform_repositories import PlatformRepository

# The schema 2 tables that changed or that rows depend on, as schema 2 created them.
SCHEMA_2 = [
    "CREATE TABLE schema_meta (version INTEGER PRIMARY KEY, applied_at DATETIME)",
    "INSERT INTO schema_meta (version, applied_at) VALUES (1, '2026-09-01 00:00:00')",
    "INSERT INTO schema_meta (version, applied_at) VALUES (2, '2026-09-10 00:00:00')",
    "CREATE TABLE sites (id VARCHAR(40) PRIMARY KEY, name VARCHAR(200), latitude FLOAT,"
    " longitude FLOAT, created_at DATETIME)",
    "CREATE TABLE recordings (id VARCHAR(40) PRIMARY KEY, site_id VARCHAR(40) REFERENCES sites(id),"
    " filename VARCHAR(255), content_type VARCHAR(100), byte_size INTEGER, checksum_sha256 VARCHAR(64),"
    " format VARCHAR(100), duration_seconds FLOAT, sample_rate_hz INTEGER, channels INTEGER,"
    " bit_depth INTEGER, captured_at VARCHAR(64), timezone VARCHAR(64), latitude FLOAT,"
    " longitude FLOAT, site_name VARCHAR(200), recorder_type VARCHAR(200), notes TEXT,"
    " storage_uri VARCHAR(500), created_at DATETIME)",
    "CREATE TABLE event_reviews (event_id VARCHAR(40) PRIMARY KEY, analysis_id VARCHAR(40),"
    " review_status VARCHAR(20), reviewed_label VARCHAR(200), review_note TEXT,"
    " resolved_scientific_name VARCHAR(200), resolved_common_name VARCHAR(200),"
    " resolved_taxon VARCHAR(40), detection_ids JSON, updated_at DATETIME)",
    "CREATE TABLE event_refs (event_id VARCHAR(40) PRIMARY KEY, analysis_id VARCHAR(40),"
    " detection_ids JSON)",
    "INSERT INTO sites (id, name, latitude, longitude, created_at) VALUES"
    " ('site_aaaaaaaaaaaaaaaaaaaaaaaa', 'Sapsucker Woods', 42.48, -76.45, '2026-09-02 00:00:00')",
    "INSERT INTO recordings (id, site_id, filename, byte_size, checksum_sha256, duration_seconds,"
    " sample_rate_hz, channels, captured_at, created_at) VALUES"
    " ('rec_aaaaaaaaaaaaaaaaaaaaaaaa', 'site_aaaaaaaaaaaaaaaaaaaaaaaa', 'a.wav', 10, 'x', 30.0,"
    " 48000, 1, '2026-05-14T06:30:00-04:00', '2026-09-02 00:00:00')",
    "INSERT INTO recordings (id, filename, byte_size, checksum_sha256, duration_seconds,"
    " sample_rate_hz, channels, created_at) VALUES"
    " ('rec_bbbbbbbbbbbbbbbbbbbbbbbb', 'b.wav', 10, 'x', 30.0, 48000, 1, '2026-09-03 00:00:00')",
]


def _old_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'v2.sqlite3'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        for stmt in SCHEMA_2:
            conn.execute(text(stmt))
    engine.dispose()
    return url


def test_v2_database_upgrades_in_place(tmp_path):
    db = Database(_old_db(tmp_path))
    db.create_all()
    insp = inspect(db.engine)
    site_cols = {c["name"] for c in insp.get_columns("sites")}
    rec_cols = {c["name"] for c in insp.get_columns("recordings")}
    assert {
        "organization_id",
        "habitat_type",
        "area_hectares",
        "fsa_field_number",
        "paddock_id",
        "notes",
        "auto_created",
    } <= site_cols
    assert {
        "organization_id",
        "deployment_id",
        "recorder_id",
        "captured_at_source",
        "source_filename",
        "telemetry",
        "signal_profile",
        "captured_at_utc",
    } <= rec_cols
    assert "reviewed_by" in {c["name"] for c in insp.get_columns("event_reviews")}
    for table in (
        "users",
        "organizations",
        "memberships",
        "invites",
        "revoked_sessions",
        "recorders",
        "deployments",
        "batch_jobs",
        "batch_items",
        "recording_stats",
        "site_day_stats",
        "species_day_stats",
        "alerts",
        "alert_rules",
        "notifications",
        "notification_prefs",
        "reports",
        "uploaded_files",
    ):
        assert table in insp.get_table_names(), table
    with db.session() as s:
        versions = [
            v for (v,) in s.execute(text("SELECT version FROM schema_meta ORDER BY version"))
        ]
        assert versions == [1, 2, DB_SCHEMA_VERSION] and DB_SCHEMA_VERSION == 3
        org = s.get(OrganizationRow, LOCAL_ORG_ID)
        assert org is not None and org.slug == "local"
        assert s.get(MembershipRow, (LOCAL_ORG_ID, LOCAL_USER_ID)).role == "owner"
        site = s.get(SiteRow, "site_aaaaaaaaaaaaaaaaaaaaaaaa")
        assert site.organization_id == LOCAL_ORG_ID and site.auto_created is True
        a = s.get(RecordingRow, "rec_aaaaaaaaaaaaaaaaaaaaaaaa")
        b = s.get(RecordingRow, "rec_bbbbbbbbbbbbbbbbbbbbbbbb")
        assert a.organization_id == b.organization_id == LOCAL_ORG_ID
        assert a.captured_at_source == "user" and b.captured_at_source == "unknown"
        assert a.signal_profile is None and a.deployment_id is None
    db.create_all()  # idempotent on the next start
    with db.session() as s:
        assert [v for (v,) in s.execute(text("SELECT count(*) FROM organizations"))] == [1]
    db.dispose()


def test_upgraded_recordings_are_visible_in_the_local_org(tmp_path):
    db = Database(_old_db(tmp_path))
    db.create_all()
    platform = PlatformRepository(db)
    views, total = platform.list_recordings(LOCAL_ORG_ID)
    assert total == 2 and {v.recording.id for v in views} == {
        "rec_aaaaaaaaaaaaaaaaaaaaaaaa",
        "rec_bbbbbbbbbbbbbbbbbbbbbbbb",
    }
    assert [s.name for s in platform.list_sites(LOCAL_ORG_ID)] == ["Sapsucker Woods"]
    db.dispose()


def test_fresh_database_has_the_local_workspace(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'fresh.sqlite3'}")
    db.create_all()
    platform = PlatformRepository(db)
    assert platform.roles_for_user(LOCAL_USER_ID) == {LOCAL_ORG_ID: "owner"}
    db.dispose()

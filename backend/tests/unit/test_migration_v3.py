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
    # Indexes declared on the added columns exist too (create_all skips existing tables).
    assert {
        "ix_recordings_organization_id",
        "ix_recordings_captured_at_utc",
        "ix_recordings_deployment_id",
        "ix_recordings_recorder_id",
        "ix_recordings_batch_job_id",
    } <= {i["name"] for i in insp.get_indexes("recordings")}
    assert "ix_sites_organization_id" in {i["name"] for i in insp.get_indexes("sites")}
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
        assert versions == [1, 2, DB_SCHEMA_VERSION] and DB_SCHEMA_VERSION == 4
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


def test_upgraded_workspace_takes_the_recordings_time_zone(tmp_path):
    """Day boundaries follow the org zone; UTC put 20:30 New York recordings on the next day."""
    url = _old_db(tmp_path)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE recordings SET timezone = 'America/New_York'"))
        conn.execute(
            text(
                "INSERT INTO recordings (id, filename, byte_size, checksum_sha256,"
                " duration_seconds, sample_rate_hz, channels, timezone, created_at) VALUES"
                " ('rec_cccccccccccccccccccccccc', 'c.wav', 10, 'x', 30.0, 48000, 1,"
                " 'Not/AZone', '2026-09-03 00:00:00')"
            )
        )
    engine.dispose()
    db = Database(url)
    db.create_all()
    with db.session() as s:
        assert s.get(OrganizationRow, LOCAL_ORG_ID).timezone == "America/New_York"
    db.dispose()
    # Without any declared zone the workspace stays on UTC.
    other = tmp_path / "other"
    other.mkdir()
    db = Database(_old_db(other))
    db.create_all()
    with db.session() as s:
        assert s.get(OrganizationRow, LOCAL_ORG_ID).timezone == "UTC"
    db.dispose()


def test_fresh_database_has_the_local_workspace(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'fresh.sqlite3'}")
    db.create_all()
    platform = PlatformRepository(db)
    assert platform.roles_for_user(LOCAL_USER_ID) == {LOCAL_ORG_ID: "owner"}
    db.dispose()


def test_schema_3_alerts_get_open_keys_and_duplicates_are_folded(tmp_path):
    """Schema 4 enforces one unresolved alert per key; older duplicates are resolved."""
    from datetime import UTC, datetime

    from thicket.persistence.db import AlertRow

    url = f"sqlite:///{tmp_path / 'v3.sqlite3'}"
    db = Database(url)
    db.create_all()
    with db.session() as s:
        s.execute(text("DROP INDEX ux_alerts_open_key"))
        s.execute(text("ALTER TABLE alerts DROP COLUMN open_key"))
        s.execute(text("DELETE FROM schema_meta"))
        s.execute(
            text("INSERT INTO schema_meta (version, applied_at) VALUES (3, '2026-09-30 00:00:00')")
        )
    db.dispose()
    engine = create_engine(url)
    with engine.begin() as conn:
        for i, (status, created) in enumerate(
            [("open", 1), ("acknowledged", 2), ("resolved", 3), ("open", 4)]
        ):
            conn.execute(
                text(
                    "INSERT INTO alerts (id, organization_id, kind, category, severity, status,"
                    " title, detail, evidence, recording_ids, dedupe_key, first_seen_at,"
                    " last_seen_at, occurrences, created_at, updated_at) VALUES"
                    " (:id, :org, 'battery_low', 'recorder', 'warning', :status, 't', 'd', '{}',"
                    " '[]', :key, :t, :t, 1, :t, :t)"
                ),
                {
                    "id": f"alr_{i:024d}",
                    "org": LOCAL_ORG_ID,
                    "status": status,
                    "key": "battery_low||rcd_1|" if i < 3 else "speech_detected|||",
                    "t": datetime(2026, 5, created, tzinfo=UTC).isoformat(),
                },
            )
    engine.dispose()
    db = Database(url)
    assert db.create_all() == 3
    with db.session() as s:
        rows = {r.id: r for r in s.query(AlertRow)}
    older, newest, resolved, other = (rows[f"alr_{i:024d}"] for i in range(4))
    assert (
        newest.status == "acknowledged" and newest.open_key == f"{LOCAL_ORG_ID}|battery_low||rcd_1|"
    )
    assert older.status == "resolved" and older.open_key is None and older.note
    assert resolved.open_key is None
    assert other.open_key == f"{LOCAL_ORG_ID}|speech_detected|||"
    assert "ux_alerts_open_key" in {i["name"] for i in inspect(db.engine).get_indexes("alerts")}
    db.dispose()

"""Schema 1 databases gain the schema 2 columns at startup, keeping their rows."""

from sqlalchemy import create_engine, inspect, text

from thicket.persistence.db import DB_SCHEMA_VERSION, Database, EventReviewRow

# The two tables whose columns changed, as schema 1 created them.
SCHEMA_1 = [
    "CREATE TABLE schema_meta (version INTEGER PRIMARY KEY, applied_at DATETIME)",
    "INSERT INTO schema_meta (version, applied_at) VALUES (1, '2026-09-01 00:00:00')",
    "CREATE TABLE event_reviews (event_id VARCHAR(40) PRIMARY KEY, analysis_id VARCHAR(40),"
    " review_status VARCHAR(20), reviewed_label VARCHAR(200), review_note TEXT,"
    " resolved_scientific_name VARCHAR(200), resolved_common_name VARCHAR(200),"
    " resolved_taxon VARCHAR(40), updated_at DATETIME)",
    "CREATE TABLE event_refs (event_id VARCHAR(40) PRIMARY KEY, analysis_id VARCHAR(40))",
    "INSERT INTO event_reviews (event_id, analysis_id, review_status)"
    " VALUES ('evt_0000000000000001', 'ana_x', 'rejected')",
]


def test_schema_1_database_is_migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        for stmt in SCHEMA_1:
            conn.execute(text(stmt))
    engine.dispose()

    db = Database(url)
    db.create_all()
    cols = {
        t: {c["name"] for c in inspect(db.engine).get_columns(t)}
        for t in ("event_reviews", "event_refs")
    }
    assert "detection_ids" in cols["event_reviews"] and "detection_ids" in cols["event_refs"]
    with db.session() as s:
        versions = [
            v for (v,) in s.execute(text("SELECT version FROM schema_meta ORDER BY version"))
        ]
        old = s.get(EventReviewRow, "evt_0000000000000001")
        assert old.review_status == "rejected" and old.detection_ids is None
    assert versions == [1, DB_SCHEMA_VERSION] and DB_SCHEMA_VERSION == 2
    db.create_all()  # idempotent on the next start
    db.dispose()


def test_fresh_database_starts_at_the_current_version(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'new.sqlite3'}")
    db.create_all()
    with db.session() as s:
        versions = [v for (v,) in s.execute(text("SELECT version FROM schema_meta"))]
    assert versions == [DB_SCHEMA_VERSION]
    db.dispose()

"""Recording windows and gaps for SD-card and duty-cycled recorders.

Gaps are only measured between consecutive recordings of a deployment and only
inside its active hours, never from "now"; a separate upload-time check covers
deployments that stop sending data on their usual routine.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.platform_helpers import insert_analysis

from thicket.domain.schedule import (
    ALL_HOURS,
    Schedule,
    active_minutes,
    learned_hours,
    parse_schedule_hours,
    upload_events,
)
from thicket.ids import LOCAL_USER_ID

NY = ZoneInfo("America/New_York")


@pytest.fixture
def farm(container):
    c = container
    org = c.platform.create_org(
        LOCAL_USER_ID,
        name="Window Farm",
        kind="farm",
        timezone="America/New_York",
        country=None,
        region=None,
    )
    site = c.platform.create_site(org.id, {"name": "Hedge"})
    rec = c.platform.create_recorder(org.id, {"label": "AM-W", "make": "audiomoth"})
    dep = c.platform.create_deployment(
        org.id,
        {
            "recorder_id": rec.id,
            "site_id": site.id,
            "started_at": datetime(2026, 4, 1, tzinfo=UTC),
        },
    )
    return c, org, site, rec, dep


def record(farm, when, **kw):
    c, org, site, rec, dep = farm
    return insert_analysis(
        c,
        org_id=org.id,
        site_id=site.id,
        recorder_id=rec.id,
        deployment_id=dep.id,
        captured_at=when,
        **kw,
    )


def health(c, rec, dep, now=None):
    return c.health.build(
        c.platform.get_recorder(rec.id),
        c.services.recorder_model(c.platform.get_recorder(rec.id)),
        c.services.deployment_model(c.platform.get_deployment(dep.id)),
        c.platform.get_deployment(dep.id),
        days=30,
        now=now,
    )


def kinds(c, org_id):
    return sorted(a.kind for a in c.platform.list_alerts(org_id)[0])


# ---------------------------------------------------------------- scenarios


def test_backfilled_may_data_uploaded_in_october_raises_no_gap(farm):
    """Ten days of hourly May recordings arrive on one card in October: no gap, no alert."""
    c, org, site, rec, dep = farm
    start = datetime(2026, 5, 1, 4, 0, tzinfo=UTC)
    for h in range(10 * 24):
        record(farm, start + timedelta(hours=h), duration=30.0)
    october = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    c.alerts.clock = lambda: october
    assert c.alerts.nightly(org.id) == []
    assert kinds(c, org.id) == []
    h = health(c, rec, dep, now=october)
    # The health window follows the data, so the card's recorder looks healthy.
    assert h.gaps == [] and h.uptime_fraction_7d == 1.0
    assert h.recordings_last_7d == 7 * 24 + 1 and h.median_interval_minutes == 60.0
    assert "up to the latest recording (2026-05-11)" in h.baseline_note


def test_dawn_only_schedule_over_ten_days_has_no_gap(farm):
    """04:00 to 08:00 local every 10 minutes: nights and days are outside the window."""
    c, org, site, rec, dep = farm
    c.platform.update_deployment(dep.id, {"expected_interval_minutes": 10.0})
    aid = None
    for day in range(10):
        local = datetime(2026, 5, 1 + day, 4, 0, tzinfo=NY)
        for i in range(24):
            aid, _ = record(farm, (local + timedelta(minutes=10 * i)).astimezone(UTC))
    assert {a.kind for a in c.alerts.evaluate_analysis(aid)}.isdisjoint(
        {"recording_gap", "schedule_deviation"}
    )
    c.alerts.clock = lambda: datetime(2026, 5, 12, 6, 0, tzinfo=UTC)
    assert [a for a in c.alerts.nightly(org.id) if a.kind == "recording_gap"] == []
    h = health(c, rec, dep, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert h.gaps == []
    assert h.uptime_fraction_7d == pytest.approx(1.0, abs=0.02)
    gaps = next(x for x in h.checks if x.name == "gaps")
    assert gaps.status == "good"
    assert "local hours 04:00-08:00" in h.baseline_note


def test_a_two_day_hole_in_a_24h_schedule_is_one_gap(farm):
    c, org, site, rec, dep = farm
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    hours = [h for h in range(10 * 24) if not 96 <= h < 144]  # days 5 and 6 missing
    aid = None
    for h in hours:
        aid, _ = record(farm, start + timedelta(hours=h))
    rows = [a for a in c.alerts.evaluate_analysis(aid) if a.kind == "recording_gap"]
    assert len(rows) == 1
    gap = rows[0]
    assert gap.evidence["observed_gap_hours"] == 49.0
    assert gap.evidence["gaps_in_deployment"] == 1
    assert gap.evidence["active_hours"] == list(range(24))
    assert "Observed 49 hours of the recording window (around the clock)" in gap.detail
    c.alerts.clock = lambda: datetime(2026, 10, 1, tzinfo=UTC)
    c.alerts.nightly(org.id)
    assert kinds(c, org.id).count("recording_gap") == 1
    h = health(c, rec, dep, now=datetime(2026, 10, 1, tzinfo=UTC))
    assert len(h.gaps) == 1 and h.gaps[0].hours == 49.0 and h.gaps[0].expected_recordings == 48


def test_a_hole_inside_a_dawn_window_counts_only_its_active_hours(farm):
    """A card that died for three days of a dawn-only schedule misses 3 x 4 hours."""
    c, org, site, rec, dep = farm
    for day in [d for d in range(10) if d not in (4, 5, 6)]:
        local = datetime(2026, 5, 1 + day, 4, 0, tzinfo=NY)
        for i in range(24):
            record(farm, (local + timedelta(minutes=10 * i)).astimezone(UTC))
    c.alerts.clock = lambda: datetime(2026, 5, 12, tzinfo=UTC)
    (gap,) = [a for a in c.alerts.nightly(org.id) if a.kind == "recording_gap"]
    assert gap.evidence["observed_gap_hours"] == pytest.approx(12.17, abs=0.01)
    assert gap.evidence["active_hours"] == [4, 5, 6, 7]


def test_declared_schedule_ranges_win_over_learning(farm):
    c, org, site, rec, dep = farm
    c.platform.update_deployment(dep.id, {"schedule_description": "Dawn 04:00-08:00 local"})
    start = datetime(2026, 5, 1, 4, 0, tzinfo=NY)
    for i in range(6):
        record(farm, (start + timedelta(minutes=10 * i)).astimezone(UTC))
    h = health(c, rec, dep, now=datetime(2026, 5, 2, tzinfo=UTC))
    assert "from the deployment's schedule" in h.baseline_note


# ------------------------------------------------------------- upload time


def _uploads(farm, upload_times):
    """One recording per upload, with that upload time as created_at."""
    c = farm[0]
    for i, uploaded in enumerate(upload_times):
        _, rid = record(farm, datetime(2026, 4, 1, 6, tzinfo=UTC) + timedelta(days=7 * i))
        c.platform.attach_recording(rid, {"created_at": uploaded})


@pytest.mark.parametrize(
    "days_quiet, severity",
    [(10, None), (16, "info"), (30, "watch")],
)
def test_no_new_uploads_from_a_regular_routine(farm, days_quiet, severity):
    """Weekly uploads that stop: info after twice the usual spacing, watch after four."""
    c, org, *_ = farm
    first = datetime(2026, 5, 1, 12, tzinfo=UTC)
    _uploads(farm, [first + timedelta(days=7 * i) for i in range(5)])
    last = first + timedelta(days=28)
    c.alerts.clock = lambda: last + timedelta(days=days_quiet)
    rows = [a for a in c.alerts.nightly(org.id) if a.kind == "upload_overdue"]
    if severity is None:
        assert rows == []
        return
    assert len(rows) == 1 and rows[0].severity == severity and rows[0].category == "recorder"
    assert rows[0].evidence["baseline_median_upload_spacing_hours"] == 168.0
    assert rows[0].evidence["n"] == 4
    assert "not recordings" in rows[0].detail and "recording_gap" not in kinds(c, org.id)


def test_no_upload_check_without_a_routine(farm):
    c, org, *_ = farm
    first = datetime(2026, 5, 1, 12, tzinfo=UTC)
    _uploads(farm, [first, first + timedelta(days=7), first + timedelta(days=14)])
    c.alerts.clock = lambda: first + timedelta(days=200)
    assert [a for a in c.alerts.nightly(org.id) if a.kind == "upload_overdue"] == []


# ------------------------------------------------------------- building blocks


def test_parse_schedule_hours():
    assert parse_schedule_hours("04:00-08:00") == frozenset({4, 5, 6, 7})
    assert parse_schedule_hours("04:30-06:15, 18:30 to 20:00") == frozenset({4, 5, 6, 18, 19})
    assert parse_schedule_hours("21:00-03:00") == frozenset({21, 22, 23, 0, 1, 2})
    assert parse_schedule_hours("00:00-24:00") == ALL_HOURS
    for text in (None, "", "every 10 minutes", "deployed 2024-05-14", "3-5 times a day"):
        assert parse_schedule_hours(text) is None


def test_active_minutes_follow_local_hours_across_a_clock_change():
    dawn = frozenset({4, 5, 6, 7})
    # 1 to 2 May (EDT): one dawn window of 240 minutes between 08:00 and 08:00.
    a = datetime(2026, 5, 1, 8, 0, tzinfo=NY)
    assert active_minutes(a, a + timedelta(days=1), NY, dawn) == 240.0
    # Across the November clock change the window is still four local hours a day.
    b = datetime(2026, 10, 31, 8, 0, tzinfo=NY)
    assert active_minutes(b, datetime(2026, 11, 2, 8, 0, tzinfo=NY), NY, dawn) == 480.0
    assert active_minutes(a, a, NY, dawn) == 0.0
    assert active_minutes(a, a + timedelta(hours=3), NY, ALL_HOURS) == 180.0


def test_learned_hours_include_the_hours_a_recording_runs_through():
    start = datetime(2026, 5, 1, 5, 50, tzinfo=NY)
    assert learned_hours([(start, 30 * 60)], NY) == frozenset({5, 6})
    assert learned_hours([(start, 0)], NY) == frozenset({5})
    sched = Schedule(tz=NY, hours=frozenset({5, 6}), source="learned")
    assert sched.describe() == "local hours 05:00-07:00"


def test_upload_events_group_a_batch():
    t = datetime(2026, 5, 1, 12, tzinfo=UTC)
    created = [t, t + timedelta(minutes=5), t + timedelta(minutes=20), t + timedelta(days=7)]
    assert upload_events(created) == [t, t + timedelta(days=7)]
    assert upload_events([]) == []
    assert date(2026, 5, 1) == upload_events(created)[0].date()

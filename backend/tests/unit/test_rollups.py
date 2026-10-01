"""Rollups, dashboard, phenology and site comparison on synthetic analyses.

Numbers are worked out by hand in the comments. Species shorthand:
A = American Robin, B = Blue Jay, C = House Finch (birds), D = Spring Peeper
(amphibian). Organization time zone America/New_York.
"""

from datetime import UTC, date, datetime

import pytest
from tests.platform_helpers import insert_analysis

from thicket.api.schemas import EventReviewUpdate, ReviewStatus
from thicket.ids import LOCAL_USER_ID
from thicket.services.dashboard import (
    build_dashboard,
    build_phenology,
    build_site_comparison,
)

A, B, C, D = (
    "Turdus migratorius",
    "Cyanocitta cristata",
    "Haemorhous mexicanus",
    "Pseudacris crucifer",
)
D1, D2 = date(2026, 5, 14), date(2026, 5, 16)


@pytest.fixture
def farm(container):
    c = container
    org = c.platform.create_org(
        LOCAL_USER_ID,
        name="Rollup Farm",
        kind="farm",
        timezone="America/New_York",
        country=None,
        region=None,
    )
    s1 = c.platform.create_site(org.id, {"name": "S1", "latitude": 42.44, "longitude": -76.5})
    s2 = c.platform.create_site(org.id, {"name": "S2"})
    ids = {}
    # D1 at S1: 06:00 and 10:00 local, plus 23:00 local which is already the 15th in UTC.
    ids["r1"] = insert_analysis(
        c,
        org_id=org.id,
        site_id=s1.id,
        captured_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        species={A: 2, B: 1},
    )
    ids["r2"] = insert_analysis(
        c,
        org_id=org.id,
        site_id=s1.id,
        captured_at=datetime(2026, 5, 14, 14, 0, tzinfo=UTC),
        duration=120.0,
        species={A: 1, C: 1},
        quality_status="usable_with_warnings",
    )
    ids["r3"] = insert_analysis(
        c,
        org_id=org.id,
        site_id=s1.id,
        captured_at=datetime(2026, 5, 15, 3, 0, tzinfo=UTC),
        species={D: 1},
        quality_status="not_usable",
    )
    # D2 at S1, D1 at S2.
    ids["r4"] = insert_analysis(
        c,
        org_id=org.id,
        site_id=s1.id,
        captured_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
        species={A: 1},
    )
    ids["r5"] = insert_analysis(
        c,
        org_id=org.id,
        site_id=s2.id,
        captured_at=datetime(2026, 5, 14, 16, 0, tzinfo=UTC),
        species={B: 2},
    )
    return c, org, s1, s2, ids


def day(c, org_id, site_id, d):
    rows = c.platform.site_days(org_id, start=d, end=d, site_ids=[site_id])
    return rows[0] if rows else None


def test_recording_stats_use_org_local_time(farm):
    c, org, s1, _, ids = farm
    st = c.platform.get_recording_stats(ids["r3"][1])
    assert st.local_date == D1 and st.local_hour == 23 and st.hour_bucket == "night"
    st1 = c.platform.get_recording_stats(ids["r1"][1])
    assert st1.local_hour == 6 and st1.hour_bucket == "dawn"  # sun-based: site has coordinates
    assert (st1.iso_year, st1.iso_week) == (2026, 20)
    assert st1.richness == 2 and st1.events == 3 and st1.events_per_minute == 3.0


def test_site_day_hand_checked(farm):
    c, org, s1, _, _ = farm
    d = day(c, org.id, s1.id, D1)
    # r1 + r2 + r3: 3 recordings, 1 + 2 + 1 = 4 minutes, events A3 B1 C1 D1 = 6.
    assert (d.recordings, d.minutes, d.events, d.richness) == (3, 4.0, 6, 4)
    assert d.events_per_minute == 1.5
    # Shannon over [3, 1, 1, 1]: -(0.5 ln 0.5 + 3 * (1/6) ln (1/6)) = 1.2425
    assert d.shannon == pytest.approx(1.2425, abs=1e-4)
    assert d.usable_fraction == pytest.approx(2 / 3, abs=1e-4)
    assert d.quality_counts == {"usable": 1, "usable_with_warnings": 1, "not_usable": 1}
    assert d.activity == {"6": [1, 3, 1.0], "10": [1, 2, 2.0], "23": [1, 1, 1.0]}
    assert d.indices["ndsi"] == pytest.approx(0.2)
    sp = {
        s.scientific_name: s
        for s in c.platform.species_days(org.id, start=D1, end=D1, site_ids=[s1.id])
    }
    assert (
        sp[A].events == 3 and sp[A].recordings_with_detection == 2 and sp[A].max_confidence == 0.9
    )
    assert sp[D].taxon == "amphibian" and sp[D].common_name == "Spring Peeper"
    assert sp[A].first_detected_at == datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    assert sp[A].last_detected_at == datetime(2026, 5, 14, 14, 0, tzinfo=UTC)


def test_each_analysis_counts_at_its_own_threshold(container):
    c = container
    s = c.platform.create_site(c.platform.local_org_id(), {"name": "T"})
    t = datetime(2026, 5, 14, 12, tzinfo=UTC)
    insert_analysis(c, site_id=s.id, captured_at=t, species={A: 2}, threshold=0.6, confidence=0.7)
    insert_analysis(c, site_id=s.id, captured_at=t, species={B: 3}, threshold=0.8, confidence=0.7)
    d = day(c, c.platform.local_org_id(), s.id, D1)
    # The second analysis's windows (0.7) are below its own 0.8 threshold.
    assert d.events == 2 and d.richness == 1 and d.recordings == 2


def test_rebuild_matches_incremental(farm):
    c, org, *_ = farm

    def snapshot():
        days = c.platform.site_days(org.id, start=date(2026, 1, 1), end=date(2026, 12, 31))
        sp = c.platform.species_days(org.id)
        return (
            [
                (d.site_id, d.local_date, d.recordings, d.minutes, d.events, d.richness, d.shannon)
                for d in days
            ],
            [
                (s.site_id, s.local_date, s.scientific_name, s.events, s.recordings_with_detection)
                for s in sp
            ],
        )

    before = snapshot()
    assert c.rollups.rebuild()["recordings"] == 5
    assert snapshot() == before
    c.platform.clear_rollups(org.id)
    assert snapshot() == ([], [])
    c.rollups.rebuild(org.id)
    assert snapshot() == before


def test_review_updates_the_rollup(farm):
    c, org, _, s2, ids = farm
    aid = ids["r5"][0]
    event = c.analysis.view(aid).events[0]
    assert day(c, org.id, s2.id, D1).events == 2
    c.analysis.review(event.id, EventReviewUpdate(review_status=ReviewStatus.rejected), None)
    # The review hook recomputed the day: one of the two Blue Jay events is rejected.
    assert day(c, org.id, s2.id, D1).events == 1
    assert c.platform.get_recording_stats(ids["r5"][1]).events == 1


def test_removing_a_recording_recomputes_its_day(farm):
    c, org, s1, _, ids = farm
    c.rollups.remove_recording(ids["r3"][1])
    d = day(c, org.id, s1.id, D1)
    assert (d.recordings, d.events, d.richness) == (2, 5, 3)
    c.rollups.remove_recording(ids["r4"][1])
    assert day(c, org.id, s1.id, D2) is None


def test_dashboard_hand_checked(farm):
    c, org, s1, s2, _ = farm
    dash = build_dashboard(
        c.platform, org.id, start=date(2026, 5, 1), end=date(2026, 5, 31), site_id=None
    )
    assert dash.recordings == 5 and dash.minutes_recorded == 6.0
    assert dash.detection_events == 9 and dash.species_counted == 4
    assert dash.quality == {"usable": 3, "usable_with_warnings": 1, "not_usable": 1}
    d1, d2 = dash.richness_by_day
    # D1 across both sites: union {A, B, C, D}; events A3 B3 C1 D1 = 8 over 5 minutes.
    assert (d1.date, d1.species_richness, d1.detection_events, d1.minutes) == (D1, 4, 8, 5.0)
    assert d1.events_per_minute == 1.6 and d1.site_id is None
    assert d1.shannon_index == pytest.approx(1.2555, abs=1e-4)
    assert d1.usable_fraction == pytest.approx(0.75, abs=1e-4)
    assert (d2.date, d2.species_richness, d2.detection_events) == (D2, 1, 1)
    top = dash.species[0]
    assert top.scientific_name == A and top.detection_events == 4
    assert top.recordings_with_detection == 3 and top.presence_fraction == 0.6
    assert set(top.site_ids) == {s1.id}
    taxa = {t.taxon.value: (t.detection_events, t.species) for t in dash.by_taxon}
    assert taxa == {"amphibian": (1, 1), "bird": (8, 3)}
    cells = {(h.weekday, h.hour): h for h in dash.activity_heatmap}
    assert (
        cells[(D1.weekday(), 6)].recordings == 1
        and cells[(D1.weekday(), 6)].events_per_minute == 3.0
    )
    assert len(dash.indices_by_day) == 2 and dash.open_alerts == 0
    assert "History starts" in dash.baseline_note


def test_dashboard_site_filter_and_empty_period(farm):
    c, org, s1, s2, _ = farm
    only = build_dashboard(c.platform, org.id, start=D1, end=D2, site_id=s2.id)
    assert only.recordings == 1 and only.species_counted == 1 and only.site_ids == [s2.id]
    empty = build_dashboard(
        c.platform, org.id, start=date(2025, 1, 1), end=date(2025, 1, 31), site_id=None
    )
    assert empty.recordings == 0 and empty.richness_by_day == [] and empty.species == []


def test_phenology_weeks(farm):
    c, org, *_ = farm
    ph = build_phenology(c.platform, org.id, scientific_name=A, site_id=None, years=1)
    assert ph.species.common_name == "American Robin" and ph.taxon.value == "bird"
    (cell,) = ph.cells
    # ISO week 20: 5 recordings, A in r1, r2 (S1 D1) and r4 (S1 D2) = 3; 4 events over 6 minutes.
    assert (cell.year, cell.iso_week, cell.recordings, cell.recordings_with_detection) == (
        2026,
        20,
        5,
        3,
    )
    assert cell.presence_fraction == 0.6 and cell.events_per_minute == pytest.approx(
        0.6667, abs=1e-4
    )
    assert ph.first_detection_by_year == {2026: D1} and ph.last_detection_by_year == {2026: D2}


def test_phenology_unknown_species(farm):
    c, org, *_ = farm
    from thicket.errors import ThicketError

    with pytest.raises(ThicketError):
        build_phenology(
            c.platform, org.id, scientific_name="Nonexistent bird", site_id=None, years=2
        )


def test_site_comparison(farm):
    c, org, s1, s2, _ = farm
    sites = c.services.list_sites(org.id)
    comp = build_site_comparison(
        c.platform, org.id, sites, start=date(2026, 5, 1), end=date(2026, 5, 31)
    )
    rows = {r.site.name: r for r in comp.rows}
    # S1: 4 recordings, 5 minutes, events A4 B1 C1 D1 = 7.
    assert (rows["S1"].recordings, rows["S1"].minutes, rows["S1"].species_richness) == (4, 5.0, 4)
    assert rows["S1"].events_per_minute == 1.4 and rows["S1"].top_species[0].scientific_name == A
    assert (rows["S2"].recordings, rows["S2"].species_richness, rows["S2"].events_per_minute) == (
        1,
        1,
        2.0,
    )
    assert rows["S2"].shannon_index == 0.0 and rows["S2"].usable_fraction == 1.0


def test_recordings_without_site_get_stats_but_no_site_day(container):
    c = container
    _, rid = insert_analysis(c, captured_at=datetime(2026, 5, 14, 12, tzinfo=UTC), species={A: 1})
    assert c.platform.get_recording_stats(rid).site_id is None
    assert c.platform.site_days(c.platform.local_org_id(), start=D1, end=D1) == []


def test_untimed_recordings_use_upload_time(container):
    c = container
    s = c.platform.create_site(c.platform.local_org_id(), {"name": "U"})
    _, rid = insert_analysis(c, site_id=s.id, captured_at=None, species={A: 1})
    st = c.platform.get_recording_stats(rid)
    assert st.captured_at is None and st.local_date == datetime.now(UTC).date()

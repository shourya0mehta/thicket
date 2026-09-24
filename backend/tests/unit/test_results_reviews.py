from datetime import UTC, datetime, timedelta

import pytest

from thicket.domain.consolidation import WindowDetection
from thicket.errors import ThicketError
from thicket.persistence.db import EventReviewRow
from thicket.services.results import (
    ABUNDANCE_DISCLAIMER,
    derive,
    derived_warnings,
    detection_events,
    validate_threshold,
)


def d(i, sci, start, conf, taxon="bird", plaus="unknown", run="run_a"):
    return WindowDetection(
        id=f"det_{i}",
        model_run_id=run,
        label_raw=f"{sci}_{sci}",
        scientific_name=sci,
        common_name=sci,
        taxon=taxon,
        start_seconds=start,
        end_seconds=start + 3.0,
        confidence=conf,
        plausibility=plaus,
    )


RAW = [
    d(0, "A a", 0.0, 0.9),
    d(1, "A a", 30.0, 0.7),
    d(2, "B b", 10.0, 0.8),
    d(3, "C c", 20.0, 0.65, plaus="unlikely"),
    d(4, "Human vocal", 40.0, 0.9, taxon="human"),
    d(5, "B b", 50.0, 0.3),
]


def run(threshold=0.6, reviews=None):
    return derive(
        RAW,
        threshold=threshold,
        merge_gap_seconds=1.0,
        analysis_id="ana_t",
        duration_seconds=60.0,
        reviews=reviews or {},
    )


def review(event_id, status, sci=None, common=None, taxon=None, windows=None, at=0):
    """A review; ``windows`` set = schema 2 (follows windows), None = schema 1 (by id)."""
    return EventReviewRow(
        event_id=event_id,
        analysis_id="ana_t",
        review_status=status,
        resolved_scientific_name=sci,
        resolved_common_name=common,
        resolved_taxon=taxon,
        detection_ids=windows,
        updated_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=at),
    )


def test_metrics_come_from_counted_events():
    r = run()
    assert len(r.events) == 5
    assert {e.scientific_name for e in r.counted} == {"A a", "B b"}
    assert r.metrics.species_richness == len({e.scientific_name for e in r.counted})
    assert r.metrics.total_detection_events == len(r.counted) == 3
    assert sum(s.detection_event_count for s in r.species) == r.metrics.total_detection_events
    assert [e.scientific_name for e in r.unlikely_excluded] == ["C c"]
    assert [e.taxon for e in r.non_biodiversity] == ["human"]
    warnings = derived_warnings(r)
    assert any("unlikely" in w and "is listed" in w for w in warnings)
    assert any("Non-wildlife sounds" in w and "Human vocal (1 event)" in w for w in warnings)


def test_lower_threshold_adds_events():
    assert run(0.3).metrics.total_detection_events == 4


def test_rejected_review_excluded():
    base = run()
    target = next(e for e in base.events if e.scientific_name == "B b")
    r = run(reviews={target.id: review(target.id, "rejected")})
    assert r.metrics.species_richness == 1
    assert target.id in r.rejected_ids
    assert any("rejected in review" in w for w in derived_warnings(r))


def test_corrected_review_relabels_or_excludes():
    base = run()
    target = next(e for e in base.events if e.scientific_name == "B b")
    relabeled = run(reviews={target.id: review(target.id, "corrected", "D d", "Dee", "bird")})
    assert {s.scientific_name for s in relabeled.species} == {"A a", "D d"}
    unknown = run(reviews={target.id: review(target.id, "corrected")})
    assert {s.scientific_name for s in unknown.species} == {"A a"}
    to_human = run(
        reviews={target.id: review(target.id, "corrected", "Human vocal", "Human vocal", "human")}
    )
    assert {s.scientific_name for s in to_human.species} == {"A a"}


def test_accepted_review_overrides_unlikely():
    base = run()
    target = next(e for e in base.events if e.scientific_name == "C c")
    r = run(reviews={target.id: review(target.id, "accepted")})
    assert "C c" in {s.scientific_name for s in r.species}
    assert r.unlikely_excluded == []


def test_validate_threshold():
    assert validate_threshold(None, 0.1, 0.6) == 0.6
    assert validate_threshold(0.1, 0.1, 0.6) == 0.1
    assert validate_threshold(1.0, 0.1, 0.6) == 1.0
    for bad in (0.05, 1.01, float("nan"), float("inf")):
        with pytest.raises(ThicketError) as e:
            validate_threshold(bad, 0.1, 0.6)
        assert "ingestion floor" in e.value.message


def test_unlikely_warning_pluralizes_species_correctly():
    raw = [
        d(0, "C c", 0.0, 0.9, plaus="unlikely"),
        d(1, "E e", 10.0, 0.9, plaus="unlikely"),
        d(2, "F f", 20.0, 0.9, plaus="unlikely"),
    ]
    two = derive(
        raw[:2],
        threshold=0.6,
        merge_gap_seconds=1.0,
        analysis_id="ana_t",
        duration_seconds=60.0,
        reviews={},
    )
    warning = next(w for w in derived_warnings(two) if "unlikely" in w)
    assert warning.startswith("2 detection events of 2 species unlikely")
    assert "speciess" not in warning
    one = derive(
        raw[:1],
        threshold=0.6,
        merge_gap_seconds=1.0,
        analysis_id="ana_t",
        duration_seconds=60.0,
        reviews={},
    )
    assert next(w for w in derived_warnings(one) if "unlikely" in w).startswith(
        "1 detection event of 1 species unlikely"
    )


def test_disclaimer_wording():
    assert ABUNDANCE_DISCLAIMER == (
        "Metrics are based on acoustic detection events and do not estimate individual abundance."
    )


# --------------------------------------------------- counted_in_metrics rows


def test_rows_flag_exactly_the_counted_set():
    r = run(0.6)
    rows = detection_events(r)
    assert [x.id for x in rows] == [e.id for e in r.events]
    assert {x.id for x in rows if x.counted_in_metrics} == {e.id for e in r.counted}
    unlikely = next(x for x in rows if x.scientific_name == "C c")
    assert unlikely.plausibility == "unlikely" and not unlikely.counted_in_metrics
    human = next(x for x in rows if x.taxon == "human")
    assert not human.counted_in_metrics
    for x in rows:  # no reviews: the counted-as label is the detected label
        assert (x.scientific_name, x.common_name, x.taxon) == (
            x.detected_scientific_name,
            x.detected_common_name,
            x.detected_taxon,
        )


def test_accepted_unlikely_row_is_counted_and_keeps_its_flag():
    base = run()
    target = next(e for e in base.events if e.scientific_name == "C c")
    r = run(reviews={target.id: review(target.id, "accepted", windows=["det_3"])})
    row = next(x for x in detection_events(r) if x.id == target.id)
    assert row.counted_in_metrics and row.review_status.value == "accepted"
    assert row.plausibility == "unlikely"  # the range model's flag is not rewritten
    assert "C c" in {s.scientific_name for s in r.species}


def test_corrected_row_counts_under_the_reviewers_species():
    base = run()
    target = next(e for e in base.events if e.scientific_name == "B b")
    fix = review(target.id, "corrected", "D d", "Dee", "bird", windows=["det_2"])
    fix.reviewed_label = "dee"
    rows = detection_events(run(reviews={target.id: fix}))
    row = next(x for x in rows if x.id == target.id)
    assert (row.scientific_name, row.common_name, row.taxon.value) == ("D d", "Dee", "bird")
    assert (row.detected_scientific_name, row.detected_common_name) == ("B b", "B b")
    assert row.reviewed_label == "dee" and row.counted_in_metrics
    unknown = review(target.id, "corrected", windows=["det_2"])
    row = next(x for x in detection_events(run(reviews={target.id: unknown})) if x.id == target.id)
    assert row.scientific_name == "B b" and not row.counted_in_metrics
    to_human = review(target.id, "corrected", "Human vocal", "Human vocal", "human", ["det_2"])
    row = next(x for x in detection_events(run(reviews={target.id: to_human})) if x.id == target.id)
    assert row.taxon.value == "human" and row.detected_taxon.value == "bird"
    assert not row.counted_in_metrics


# ------------------------------------------------ reviews follow the windows

# One strong chickadee window, then two weak ones that only pass at low thresholds.
CHICKADEE = [
    d(10, "K k", 0.0, 0.81),
    d(11, "K k", 3.0, 0.31),
    d(12, "K k", 6.0, 0.22),
]
UNLIKELY = [
    d(20, "U u", 20.0, 0.9, plaus="unlikely"),
    d(21, "U u", 23.0, 0.4, plaus="unlikely"),
]


def run2(threshold, reviews=None, raw=CHICKADEE + UNLIKELY):
    return derive(
        raw,
        threshold=threshold,
        merge_gap_seconds=1.0,
        analysis_id="ana_t",
        duration_seconds=60.0,
        reviews=reviews or {},
    )


def windows_of(derived, sci):
    return [e.contributing_detection_ids for e in derived.counted if e.scientific_name == sci]


def test_rejection_sticks_to_its_windows_at_lower_thresholds():
    at60 = run2(0.6)
    [chick] = [e for e in at60.events if e.scientific_name == "K k"]
    assert chick.contributing_detection_ids == ["det_10"]
    # Before window-level reviews, the 0.10 event [0, 9] had a new id and the
    # rejected window counted again, merged with the weak ones.
    assert windows_of(run2(0.1), "K k") == [["det_10", "det_11", "det_12"]]

    reviews = {chick.id: review(chick.id, "rejected", windows=["det_10"])}
    for t in (0.6, 0.3, 0.1):
        r = run2(t, reviews)
        rejected = next(e for e in r.events if e.id == chick.id)
        assert rejected.contributing_detection_ids == ["det_10"]
        assert (rejected.start_seconds, rejected.end_seconds) == (0.0, 3.0)
        assert chick.id in r.rejected_ids and chick.id not in r.counted_ids
        assert all("det_10" not in ids for ids in windows_of(r, "K k"))
        assert r.reviews[chick.id].review_status == "rejected"
    # Windows the reviewer never heard form their own, unreviewed event.
    low = run2(0.1, reviews)
    assert windows_of(low, "K k") == [["det_11", "det_12"]]
    new = next(e for e in low.counted if e.scientific_name == "K k")
    assert new.id != chick.id and new.id not in low.reviews
    # Above the rejected window's score the rejected event is simply not listed.
    assert chick.id not in {e.id for e in run2(0.9, reviews).events}


def test_rejecting_the_merged_low_threshold_event_keeps_all_its_windows():
    [merged] = [e for e in run2(0.1).events if e.scientific_name == "K k"]
    ids = merged.contributing_detection_ids
    reviews = {merged.id: review(merged.id, "rejected", windows=ids)}
    for t in (0.1, 0.3, 0.6):
        r = run2(t, reviews)
        assert windows_of(r, "K k") == []
        listed = next(e for e in r.events if e.id == merged.id)
        assert set(listed.contributing_detection_ids) <= set(ids)
    assert next(e for e in run2(0.6, reviews).events if e.id == merged.id).n_windows == 1


def test_correction_follows_its_windows():
    [chick] = [e for e in run2(0.6).events if e.scientific_name == "K k"]
    fix = review(chick.id, "corrected", "D d", "Dee", "bird", windows=["det_10"])
    low = run2(0.1, {chick.id: fix})
    counts = {s.scientific_name: s.detection_event_count for s in low.species}
    assert counts["D d"] == 1 and counts["K k"] == 1
    row = next(x for x in detection_events(low) if x.id == chick.id)
    assert row.scientific_name == "D d" and row.review_status.value == "corrected"
    assert row.contributing_detection_ids == ["det_10"] and row.counted_in_metrics
    assert windows_of(low, "K k") == [["det_11", "det_12"]]


def test_acceptance_is_inherited_only_by_events_inside_it():
    [merged] = [e for e in run2(0.1).events if e.scientific_name == "U u"]
    assert merged.contributing_detection_ids == ["det_20", "det_21"]
    ok = {merged.id: review(merged.id, "accepted", windows=["det_20", "det_21"])}
    at60 = run2(0.6, ok)
    [inside] = [e for e in at60.events if e.scientific_name == "U u"]
    assert inside.id != merged.id and inside.id in at60.counted_ids
    assert at60.reviews[inside.id].review_status == "accepted"
    # Accepting only the strong window does not vouch for the weak one.
    [strong] = [e for e in run2(0.6).events if e.scientific_name == "U u"]
    partial = {strong.id: review(strong.id, "accepted", windows=["det_20"])}
    low = run2(0.1, partial)
    [bigger] = [e for e in low.events if e.scientific_name == "U u"]
    assert bigger.id not in low.reviews and bigger.id not in low.counted_ids
    assert run2(0.6, partial).counted_ids >= {strong.id}


def test_latest_review_owns_a_shared_window():
    [chick] = [e for e in run2(0.6).events if e.scientific_name == "K k"]
    [merged] = [e for e in run2(0.1).events if e.scientific_name == "K k"]
    older = review(chick.id, "rejected", windows=["det_10"], at=0)
    newer = review(
        merged.id, "corrected", "D d", "Dee", "bird", windows=["det_10", "det_11", "det_12"], at=5
    )
    r = run2(0.1, {chick.id: older, merged.id: newer})
    assert chick.id not in {e.id for e in r.events}
    assert next(e for e in r.events if e.id == merged.id).n_windows == 3
    assert [s.scientific_name for s in r.species if s.scientific_name in ("D d", "K k")] == ["D d"]


def test_schema1_reviews_still_apply_by_event_id():
    [chick] = [e for e in run2(0.6).events if e.scientific_name == "K k"]
    legacy = {chick.id: review(chick.id, "rejected")}  # no window list
    assert chick.id in run2(0.6, legacy).rejected_ids
    assert windows_of(run2(0.1, legacy), "K k") == [["det_10", "det_11", "det_12"]]

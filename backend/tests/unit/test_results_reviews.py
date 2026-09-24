import pytest

from thicket.domain.consolidation import WindowDetection
from thicket.errors import ThicketError
from thicket.persistence.db import EventReviewRow
from thicket.services.results import (
    ABUNDANCE_DISCLAIMER,
    derive,
    derived_warnings,
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


def review(event_id, status, sci=None, common=None, taxon=None):
    return EventReviewRow(
        event_id=event_id,
        analysis_id="ana_t",
        review_status=status,
        resolved_scientific_name=sci,
        resolved_common_name=common,
        resolved_taxon=taxon,
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


def test_disclaimer_wording():
    assert ABUNDANCE_DISCLAIMER == (
        "Metrics are based on acoustic detection events and do not estimate individual abundance."
    )

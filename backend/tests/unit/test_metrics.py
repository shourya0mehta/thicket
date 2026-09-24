import math

import pytest

from thicket.domain.consolidation import Event
from thicket.domain.metrics import (
    compute_metrics,
    counted_events,
    gini_simpson,
    pielou_evenness,
    shannon_index,
    species_summaries,
)


def ev(i, sci, conf=0.9, taxon="bird", plaus="unknown", run="run_a", start=0.0):
    return Event(
        id=f"evt_{i}",
        scientific_name=sci,
        common_name=sci.upper(),
        taxon=taxon,
        model_run_id=run,
        start_seconds=start,
        end_seconds=start + 3.0,
        max_confidence=conf,
        mean_confidence=conf,
        contributing_detection_ids=[f"det_{i}"],
        plausibility=plaus,
    )


def test_hand_computed_values():
    counts = [2, 1, 1]
    assert shannon_index(counts) == pytest.approx(1.0397, abs=1e-4)
    assert pielou_evenness(counts) == pytest.approx(0.9464, abs=1e-4)
    assert gini_simpson(counts) == pytest.approx(0.625)
    # Explicit formulas
    p = [0.5, 0.25, 0.25]
    assert shannon_index(counts) == pytest.approx(-sum(x * math.log(x) for x in p))


def test_single_species_and_empty():
    assert shannon_index([5]) == 0.0
    assert pielou_evenness([5]) == 0.0
    assert gini_simpson([5]) == 0.0
    assert shannon_index([]) == 0.0
    assert pielou_evenness([]) == 0.0
    assert gini_simpson([]) == 0.0


def test_compute_metrics_matches_formulas():
    events = [ev(0, "A a", start=0), ev(1, "A a", start=10), ev(2, "B b", 0.8), ev(3, "C c", 0.7)]
    m = compute_metrics(events, duration_seconds=120.0)
    assert m.species_richness == 3
    assert m.shannon_index == pytest.approx(1.0397, abs=1e-4)
    assert m.pielou_evenness == pytest.approx(0.9464, abs=1e-4)
    assert m.simpson_diversity == pytest.approx(0.625)
    assert m.total_detection_events == 4
    assert m.events_per_minute == pytest.approx(2.0)
    assert m.dominant_species == ("A a", "A A")
    assert m.events_by_taxon == {"bird": 4}


def test_compute_metrics_empty():
    m = compute_metrics([], 60.0)
    assert (m.species_richness, m.shannon_index, m.pielou_evenness, m.simpson_diversity) == (
        0,
        0,
        0,
        0,
    )
    assert m.dominant_species is None
    assert m.events_per_minute == 0.0


def test_dominant_tie_breaks_on_confidence_then_name():
    m = compute_metrics([ev(0, "B b", 0.9), ev(1, "A a", 0.9)], 60)
    assert m.dominant_species[0] == "A a"
    m = compute_metrics([ev(0, "B b", 0.95), ev(1, "A a", 0.9)], 60)
    assert m.dominant_species[0] == "B b"


def test_counted_events_exclusions():
    events = [
        ev(0, "A a"),
        ev(1, "Human vocal", taxon="human"),
        ev(2, "Engine", taxon="anthropogenic"),
        ev(3, "Noise", taxon="noise"),
        ev(4, "B b", plaus="unlikely"),
        ev(5, "C c"),
        ev(6, "Pseudacris crucifer", taxon="amphibian"),
    ]
    counted = counted_events(events, rejected_ids={"evt_5"})
    assert [e.id for e in counted] == ["evt_0", "evt_6"]
    with_unlikely = counted_events(events, rejected_ids={"evt_5"}, include_unlikely=True)
    assert [e.id for e in with_unlikely] == ["evt_0", "evt_4", "evt_6"]


def test_species_summaries_merge_runs_by_scientific_name():
    events = [ev(0, "A a", run="run_a"), ev(1, "A a", run="run_b", start=5)]
    [s] = species_summaries(events, [])
    assert s.model_run_ids == ["run_a", "run_b"]
    assert s.detection_event_count == 2

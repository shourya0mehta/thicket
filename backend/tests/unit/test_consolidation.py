import pytest

from thicket.domain.consolidation import WindowDetection, consolidate, event_id, filter_by_threshold


def det(i, start, end, conf, sci="Turdus migratorius", run="run_a", plaus="unknown", taxon="bird"):
    return WindowDetection(
        id=f"det_{i}",
        model_run_id=run,
        label_raw=f"{sci}_X",
        scientific_name=sci,
        common_name=sci.split()[-1],
        taxon=taxon,
        start_seconds=start,
        end_seconds=end,
        confidence=conf,
        plausibility=plaus,
    )


def test_gap_exactly_equal_to_merge_gap_merges():
    events = consolidate([det(0, 0.0, 3.0, 0.9), det(1, 4.0, 7.0, 0.8)], 0.5, merge_gap_seconds=1.0)
    assert len(events) == 1
    assert (events[0].start_seconds, events[0].end_seconds) == (0.0, 7.0)
    assert events[0].n_windows == 2


def test_gap_just_over_merge_gap_splits():
    events = consolidate(
        [det(0, 0.0, 3.0, 0.9), det(1, 4.01, 7.0, 0.8)], 0.5, merge_gap_seconds=1.0
    )
    assert len(events) == 2


def test_overlapping_windows_merge_and_aggregate_confidence():
    dets = [det(0, 0.0, 3.0, 0.9), det(1, 1.5, 4.5, 0.7), det(2, 3.0, 6.0, 0.5)]
    [e] = consolidate(dets, 0.5, merge_gap_seconds=0.0)
    assert (e.start_seconds, e.end_seconds) == (0.0, 6.0)
    assert e.max_confidence == 0.9
    assert e.mean_confidence == pytest.approx(0.7)
    assert e.contributing_detection_ids == ["det_0", "det_1", "det_2"]


def test_separate_species_never_merge():
    dets = [det(0, 0.0, 3.0, 0.9, sci="A a"), det(1, 0.0, 3.0, 0.9, sci="B b")]
    events = consolidate(dets, 0.5)
    assert sorted(e.scientific_name for e in events) == ["A a", "B b"]


def test_separate_model_runs_never_merge():
    dets = [det(0, 0.0, 3.0, 0.9, run="run_a"), det(1, 0.0, 3.0, 0.9, run="run_b")]
    events = consolidate(dets, 0.5)
    assert len(events) == 2
    assert {e.model_run_id for e in events} == {"run_a", "run_b"}
    assert events[0].id != events[1].id


def test_threshold_is_inclusive():
    assert len(filter_by_threshold([det(0, 0, 3, 0.6)], 0.6)) == 1
    assert len(consolidate([det(0, 0, 3, 0.6)], 0.6)) == 1
    assert consolidate([det(0, 0, 3, 0.5999)], 0.6) == []


def test_below_threshold_windows_break_events():
    dets = [det(0, 0.0, 3.0, 0.9), det(1, 3.0, 6.0, 0.2), det(2, 6.0, 9.0, 0.9)]
    assert len(consolidate(dets, 0.5, merge_gap_seconds=0.0)) == 2
    assert len(consolidate(dets, 0.1, merge_gap_seconds=0.0)) == 1


def test_order_and_ids_are_deterministic():
    dets = [
        det(3, 9.0, 12.0, 0.7, sci="B b"),
        det(1, 0.0, 3.0, 0.8, sci="B b"),
        det(2, 0.0, 3.0, 0.9, sci="A a"),
    ]
    a = consolidate(dets, 0.5, analysis_id="ana_x")
    b = consolidate(list(reversed(dets)), 0.5, analysis_id="ana_x")
    assert [(e.id, e.scientific_name, e.start_seconds) for e in a] == [
        (e.id, e.scientific_name, e.start_seconds) for e in b
    ]
    assert [(e.scientific_name, e.start_seconds) for e in a] == [
        ("A a", 0.0),
        ("B b", 0.0),
        ("B b", 9.0),
    ]
    assert a[0].id == event_id("ana_x", "run_a", "A a", 0.0, 3.0)
    assert a[0].id.startswith("evt_") and len(a[0].id) == 20


def test_event_id_stable_across_thresholds_when_extent_unchanged():
    dets = [det(0, 0.0, 3.0, 0.9), det(1, 20.0, 23.0, 0.4)]
    high = consolidate(dets, 0.8, analysis_id="ana_x")
    low = consolidate(dets, 0.3, analysis_id="ana_x")
    assert high[0].id in {e.id for e in low}


def test_unlikely_plausibility_propagates():
    [e] = consolidate(
        [det(0, 0, 3, 0.9, plaus="plausible"), det(1, 3, 6, 0.9, plaus="unlikely")], 0.5
    )
    assert e.plausibility == "unlikely"


def test_negative_merge_gap_rejected():
    with pytest.raises(ValueError):
        consolidate([], 0.5, merge_gap_seconds=-1)


def test_empty_input():
    assert consolidate([], 0.5) == []

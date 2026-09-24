"""BirdNET adapter contract on the committed soundscape fixture."""

from dataclasses import asdict
from datetime import date

import numpy as np
import pytest
from tests.helpers import SOUNDSCAPE

from thicket.api.schemas import RawDetection
from thicket.domain.consolidation import consolidate
from thicket.models.base import AcousticModelAdapter, AnalysisContext, UnsupportedAudio
from thicket.models.birdnet import BirdNETAdapter, SharedBirdNET
from thicket.services.audio_io import decode

pytestmark = pytest.mark.birdnet

ITHACA = {"latitude": 42.44, "longitude": -76.50, "recording_date": date(2026, 5, 15)}


@pytest.fixture(scope="module")
def adapter():
    a = BirdNETAdapter(SharedBirdNET())
    a.load()
    assert a.status() == "ready", a.unavailable_reason()
    return a


@pytest.fixture(scope="module")
def soundscape():
    x, sr = decode(SOUNDSCAPE, target_sr=48_000)
    return x


def ctx(**kw):
    return AnalysisContext(analysis_id="ana_test", model_run_id="run_test", **kw)


def test_protocol_and_metadata(adapter):
    assert isinstance(adapter, AcousticModelAdapter)
    assert (adapter.key, adapter.name, adapter.version) == ("birdnet", "BirdNET", "2.4")
    assert adapter.model_name == "BirdNET GLOBAL 6K V2.4"
    assert adapter.taxon_scope == ["bird", "amphibian", "insect", "mammal"]
    assert adapter.license == "CC BY-NC-SA 4.0"
    assert adapter.window_seconds == 3.0 and adapter.required_sample_rate_hz == 48_000
    assert not adapter.experimental
    assert len(adapter.model_sha256()) == 64


def test_canonical_detections(adapter, soundscape):
    out = adapter.analyze(soundscape, 48_000, ctx())
    assert out.n_windows == 10
    assert out.embeddings.shape == (10, 1024)
    assert list(out.window_starts) == [3.0 * i for i in range(10)]
    assert [d.id for d in out.detections] == [f"det_{i}" for i in range(len(out.detections))]
    for d in out.detections:
        RawDetection.model_validate(asdict(d))
        assert d.confidence >= 0.1 and 0 <= d.start_seconds < d.end_seconds <= 30.0
        assert d.model_run_id == "run_test" and d.plausibility == "unknown"
    events = consolidate(out.detections, 0.3, 1.0, "ana_test")
    by_name = {}
    for e in events:
        by_name.setdefault(e.common_name, []).append(e)
    chickadee = by_name["Black-capped Chickadee"][0]
    assert chickadee.start_seconds == 0.0
    assert chickadee.max_confidence == pytest.approx(0.81, abs=0.02)
    finch = by_name["House Finch"][0]
    assert finch.start_seconds == 9.0 and finch.max_confidence == pytest.approx(0.64, abs=0.02)
    jay = by_name["Blue Jay"][0]
    assert jay.start_seconds == 18.0 and jay.max_confidence > 0.3
    assert out.extras["human_vocal_max"] < 0.5
    assert len(out.extras["human_vocal_by_window"]) == 10
    assert out.configuration["location_filter_applied"] is False


def test_location_and_season_plausibility(adapter, soundscape):
    out = adapter.analyze(soundscape, 48_000, ctx(**ITHACA))
    plaus = {(d.common_name): d.plausibility for d in out.detections}
    assert plaus["Black-capped Chickadee"] == "plausible"
    assert plaus["Chestnut-winged Cuckoo"] == "unlikely"
    assert out.configuration["location_filter_applied"] is True
    assert out.configuration["week"] == 19


def test_non_bird_labels_never_filtered(adapter):
    labels = adapter.runtime.labels
    plaus, _ = adapter.plausibility(labels, ctx(**ITHACA))
    by_sci = {lab.scientific_name: p for lab, p in zip(labels, plaus, strict=True)}
    assert by_sci["Pseudacris crucifer"] == "unknown"  # meta model gives it ~2e-5
    assert by_sci["Gryllus pennsylvanicus"] == "unknown"
    assert by_sci["Human vocal"] == "unknown"
    assert by_sci["Poecile atricapillus"] == "plausible"


def test_no_date_uses_week_minus_one(adapter, soundscape):
    out = adapter.analyze(soundscape, 48_000, ctx(latitude=42.44, longitude=-76.5))
    assert out.configuration["week"] == -1


def test_filter_disabled(adapter, soundscape):
    out = adapter.analyze(soundscape, 48_000, ctx(location_filter=False, **ITHACA))
    assert {d.plausibility for d in out.detections} == {"unknown"}


def test_silence_has_no_bird_detections(adapter):
    out = adapter.analyze(np.zeros(5 * 48_000, dtype=np.float32), 48_000, ctx())
    assert [d for d in out.detections if d.taxon == "bird"] == []


def test_overlap_hop(adapter, soundscape):
    out = adapter.analyze(soundscape, 48_000, ctx(hop_seconds=1.5))
    assert out.n_windows == 19
    assert out.window_starts[1] == 1.5


def test_raw_threshold_floor(adapter, soundscape):
    out = adapter.analyze(soundscape, 48_000, ctx(raw_threshold=0.5))
    assert out.detections and all(d.confidence >= 0.5 for d in out.detections)


def test_typed_errors(adapter):
    with pytest.raises(UnsupportedAudio):
        adapter.analyze(np.zeros(44_100, dtype=np.float32), 44_100, ctx())
    with pytest.raises(UnsupportedAudio):
        adapter.analyze(np.zeros(0, dtype=np.float32), 48_000, ctx())


def test_deterministic(adapter, soundscape):
    a = adapter.analyze(soundscape, 48_000, ctx())
    b = adapter.analyze(soundscape.copy(), 48_000, ctx())
    assert a.detections == b.detections

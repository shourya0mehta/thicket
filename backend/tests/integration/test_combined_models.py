"""Combined BirdNET + frog/insect runs with a synthetic head (plumbing, not accuracy)."""

import pytest
from tests.helpers import SOUNDSCAPE, post_analysis

from thicket.api.schemas import Analysis
from thicket.models.birdnet_runtime import BirdNETRuntime

pytestmark = pytest.mark.birdnet


@pytest.fixture
def infer_calls(monkeypatch):
    calls = []
    original = BirdNETRuntime.infer

    def counting(self, windows):
        calls.append(windows.shape[0])
        return original(self, windows)

    monkeypatch.setattr(BirdNETRuntime, "infer", counting)
    return calls


@pytest.fixture
def frog_client(make_client, frog_head):
    client = make_client(frog_insect_enabled=True, frog_insect_model_path=frog_head)
    reg = client.app.state.container.registry
    reg.require_ready("frog_insect", timeout=60)
    return client


def test_models_endpoint_shows_enabled_experimental(frog_client):
    models = {m["key"]: m for m in frog_client.get("/api/v1/models").json()["models"]}
    f = models["frog_insect"]
    assert f["status"] == "ready" and f["experimental"] is True
    assert f["version"] == "0.0.1-test"


def test_combined_runs_birdnet_once(frog_client, infer_calls):
    r = post_analysis(
        frog_client, SOUNDSCAPE, data={"models": "birdnet,frog_insect", "threshold": "0.3"}
    )
    assert r.status_code == 201, r.text
    a = Analysis.model_validate(r.json())
    assert infer_calls == [10]  # one BirdNET pass shared by both adapters
    assert [m.adapter for m in a.model_runs] == ["birdnet", "frog_insect"]
    bird_run, frog_run = a.model_runs
    assert bird_run.id != frog_run.id
    assert frog_run.experimental and frog_run.configuration["embeddings_from_run"] == bird_run.id
    frog_events = [e for e in a.events if e.model_run_id == frog_run.id]
    assert frog_events and {e.common_name for e in frog_events} == {"Spring Peeper"}
    assert all(e.plausibility == "unknown" for e in frog_events)
    # Consecutive windows merge into one event spanning the clip.
    assert (frog_events[0].start_seconds, frog_events[0].end_seconds) == (0.0, 30.0)
    peeper = next(s for s in a.species if s.common_name == "Spring Peeper")
    assert peeper.taxon.value == "amphibian" and peeper.model_run_ids == [frog_run.id]
    assert a.metrics.events_by_taxon["amphibian"] == 1
    assert any("experimental" in w for w in a.warnings)
    ids = [d.id for d in a.raw_detections]
    assert ids == [f"det_{i}" for i in range(len(ids))]  # unique across runs


def test_frog_only_computes_embeddings_itself(frog_client, infer_calls):
    r = post_analysis(frog_client, SOUNDSCAPE, data={"models": "frog_insect"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert infer_calls == [10]
    assert [m["adapter"] for m in a["model_runs"]] == ["frog_insect"]
    assert a["model_runs"][0]["configuration"]["embeddings"] == "computed"
    assert any(c["name"] == "speech" for c in a["quality"]["checks"])
    assert {s["common_name"] for s in a["species"]} == {"Spring Peeper"}
    # BirdNET's range filter is not applied to frog/insect runs: no location note.
    assert not any("coordinates" in w for w in a["warnings"])


def test_same_species_from_two_runs_never_deduplicated(frog_client, monkeypatch, tmp_path):
    """If both models report one species, events stay separate and species merge by name."""
    import numpy as np

    head_path = tmp_path / "chickadee.npz"
    np.savez(
        head_path,
        W1=np.zeros((1024, 1), dtype=np.float32),
        b1=np.array([3.0], dtype=np.float32),
        labels=np.array(["Poecile atricapillus"]),
        common_names=np.array(["Black-capped Chickadee"]),
        taxa=np.array(["bird"]),
        thresholds=np.array([0.0]),
        temperature=np.array(1.0),
        embedding_mean=np.zeros(1024),
        embedding_std=np.ones(1024),
    )
    from thicket.models.frog_insect import FrogInsectHead

    adapter = frog_client.app.state.container.registry.lookup("frog_insect")
    monkeypatch.setattr(adapter, "head", FrogInsectHead.from_npz(head_path))
    a = post_analysis(
        frog_client, SOUNDSCAPE, data={"models": "birdnet,frog_insect", "threshold": "0.3"}
    ).json()
    chick_events = [e for e in a["events"] if e["scientific_name"] == "Poecile atricapillus"]
    assert len({e["model_run_id"] for e in chick_events}) == 2
    chick = next(s for s in a["species"] if s["scientific_name"] == "Poecile atricapillus")
    assert len(chick["model_run_ids"]) == 2
    assert chick["detection_event_count"] == len(chick_events)

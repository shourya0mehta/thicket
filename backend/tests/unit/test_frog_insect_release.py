"""The shipped frog/insect head and the shared-species ensemble rule."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pytest

from thicket.domain.consolidation import WindowDetection
from thicket.models.frog_insect import FrogInsectHead
from thicket.models.registry import packaged_frog_insect_head
from thicket.services.results import shared_species_rule


@dataclass
class _Run:
    id: str
    adapter: str
    configuration: dict = field(default_factory=dict)


def _det(i: int, run: str, sci: str) -> WindowDetection:
    return WindowDetection(
        id=f"det_{i}",
        model_run_id=run,
        label_raw=sci,
        scientific_name=sci,
        common_name=sci,
        taxon="amphibian",
        start_seconds=0.0,
        end_seconds=3.0,
        confidence=0.9,
    )


def test_packaged_head_loads_with_card():
    path = packaged_frog_insect_head()
    assert path is not None, "frog_insect_v1.npz should ship with the package"
    head = FrogInsectHead.from_npz(path)
    card = json.loads(path.with_suffix(".json").read_text())
    assert head.n_classes == len(card["released_classes"]) >= 20
    assert set(card["released_classes"]) == {lab.scientific_name for lab in head.labels}
    # Every released class cleared the bar recorded in the card.
    bar = card["release_bar"]
    for lab in card["released_classes"]:
        c = card["classes"][lab]
        assert c["released"] and c["ap"][1] >= bar["min_ap_lower_95"]
        assert c["test_recordings"] >= bar["min_test_recordings"]
    # Withheld classes cannot fire because they are not in the head at all.
    assert not set(card["withheld_classes"]) & set(card["released_classes"])
    assert np.all(np.isfinite(head.thresholds)) and head.temperature > 0


def test_shared_species_rule_prefers_head_for_its_species():
    runs = [
        _Run("run_b", "birdnet"),
        _Run("run_h", "frog_insect", {"labels": ["Lithobates sylvaticus"]}),
    ]
    raw = [
        _det(1, "run_b", "Lithobates sylvaticus"),
        _det(2, "run_b", "Pseudacris crucifer"),
        _det(3, "run_h", "Lithobates sylvaticus"),
    ]
    kept, set_aside = shared_species_rule(raw, runs)  # type: ignore[arg-type]
    assert [d.id for d in kept] == ["det_2", "det_3"]
    assert set_aside == ["Lithobates sylvaticus"]


@pytest.mark.parametrize(
    "runs",
    [
        [_Run("run_b", "birdnet")],
        [_Run("run_h", "frog_insect", {"labels": ["Lithobates sylvaticus"]})],
        [_Run("run_b", "birdnet"), _Run("run_h", "frog_insect", {})],
    ],
)
def test_shared_species_rule_is_a_no_op_without_both_runs(runs):
    raw = [_det(1, runs[0].id, "Lithobates sylvaticus")]
    kept, set_aside = shared_species_rule(raw, runs)  # type: ignore[arg-type]
    assert kept == raw and set_aside == []


@pytest.mark.birdnet
def test_combined_analysis_applies_rule_and_records_head_labels(tmp_path):
    from fastapi.testclient import TestClient
    from tests.helpers import make_settings, post_analysis

    from thicket.main import create_app

    fixture = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "fixtures"
        / "soundscape_30s.flac"
    )
    settings = make_settings(tmp_path, frog_insect_enabled=True)
    with TestClient(create_app(settings)) as client:
        for _ in range(300):
            st = {m["key"]: m["status"] for m in client.get("/api/v1/models").json()["models"]}
            if st["birdnet"] == "ready" and st["frog_insect"] == "ready":
                break
            __import__("time").sleep(0.1)
        assert st["frog_insect"] == "ready"
        r = post_analysis(
            client, fixture, data={"models": '["birdnet","frog_insect"]', "threshold": "0.3"}
        )
        assert r.status_code == 201, r.text
        a = r.json()
        runs = {m["adapter"]: m for m in a["model_runs"]}
        labels = runs["frog_insect"]["configuration"]["labels"]
        assert labels and all(" " in s for s in labels)
        head_ids = {runs["birdnet"]["id"]}
        assert not any(
            e["model_run_id"] in head_ids and e["scientific_name"] in labels for e in a["events"]
        )
        # Birds from BirdNET are untouched by the rule.
        assert any(e["taxon"] == "bird" for e in a["events"])


def test_default_models_include_the_head_only_when_enabled(tmp_path):
    from tests.helpers import make_settings
    from thicket.models.registry import build_registry

    on = build_registry(make_settings(tmp_path, frog_insect_enabled=True))
    off = build_registry(make_settings(tmp_path, frog_insect_enabled=False))
    assert on.default_models() == ["birdnet", "frog_insect"]
    assert off.default_models() == ["birdnet"]

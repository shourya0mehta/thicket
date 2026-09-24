import pytest
from tests.helpers import make_settings

from thicket.api.schemas import ErrorCode
from thicket.errors import ThicketError
from thicket.models.birdnet import BirdNETAdapter
from thicket.models.frog_insect import FrogInsectAdapter
from thicket.models.registry import ModelRegistry, build_registry


def test_registry_holds_instances_and_rejects_classes(tmp_path):
    reg = build_registry(make_settings(tmp_path))
    assert reg.keys() == ["birdnet", "frog_insect"]
    assert isinstance(reg.lookup("birdnet"), BirdNETAdapter)
    assert isinstance(reg.lookup("frog_insect"), FrogInsectAdapter)
    with pytest.raises(TypeError):
        ModelRegistry().register(BirdNETAdapter)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        reg.register(reg.lookup("birdnet"))


def test_unknown_model(tmp_path):
    reg = build_registry(make_settings(tmp_path))
    with pytest.raises(ThicketError) as e:
        reg.get("perch")
    assert e.value.code == ErrorCode.unknown_model and e.value.status_code == 422


def test_disabled_models(tmp_path):
    reg = build_registry(make_settings(tmp_path, birdnet_enabled=False))
    assert reg.statuses() == {"birdnet": "disabled", "frog_insect": "disabled"}
    for key in ("birdnet", "frog_insect"):
        with pytest.raises(ThicketError) as e:
            reg.get(key)
        assert e.value.code == ErrorCode.model_unavailable and e.value.status_code == 422
    infos = {i.key: i for i in reg.infos()}
    assert infos["frog_insect"].experimental and infos["frog_insect"].status == "disabled"
    assert infos["frog_insect"].model_card_url == "docs/model-cards/frog-insect.md"
    assert infos["birdnet"].unavailable_reason


def test_status_before_load(tmp_path):
    reg = build_registry(make_settings(tmp_path))
    # Disabled is known from configuration immediately; enabled models are loading.
    assert reg.statuses() == {"birdnet": "loading", "frog_insect": "disabled"}
    assert reg.get("birdnet").status() == "loading"  # usable, jobs wait for it


@pytest.mark.birdnet
def test_background_loading_becomes_ready(tmp_path):
    reg = build_registry(make_settings(tmp_path))
    reg.start_loading(background=True)
    adapter = reg.require_ready("birdnet", timeout=60)
    assert adapter.is_ready()
    assert reg.statuses()["birdnet"] == "ready"
    assert reg.resolve_label("american robin").scientific_name == "Turdus migratorius"
    assert reg.resolve_label("Pseudacris crucifer").taxon == "amphibian"
    assert reg.resolve_label("not a species") is None


def test_unavailable_birdnet(tmp_path):
    reg = build_registry(make_settings(tmp_path, birdnet_model_dir=tmp_path / "nowhere"))
    # Only the explicit dir is wrong; bundled weights may still resolve, so point
    # the adapter at a runtime that cannot load.
    adapter = reg.lookup("birdnet")

    def boom():
        raise RuntimeError("weights missing")

    adapter.shared.load = boom  # type: ignore[method-assign]
    reg.start_loading(background=False)
    assert adapter.status() == "unavailable"
    with pytest.raises(ThicketError) as e:
        reg.get("birdnet")
    assert e.value.status_code == 503
    with pytest.raises(ThicketError):
        reg.require_ready("birdnet", timeout=0.1)

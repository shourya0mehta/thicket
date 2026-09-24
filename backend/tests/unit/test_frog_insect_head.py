import numpy as np
import pytest

from thicket.models.base import AnalysisContext, ModelUnavailable
from thicket.models.birdnet import SharedBirdNET
from thicket.models.frog_insect import FrogInsectAdapter, FrogInsectHead, HeadFormatError


def test_head_loads_and_predicts(frog_head):
    head = FrogInsectHead.from_npz(frog_head)
    assert head.n_classes == 2
    assert [lab.taxon for lab in head.labels] == ["amphibian", "insect"]
    assert head.labels[0].raw == "Pseudacris crucifer_Spring Peeper"
    p = head.predict_proba(np.random.default_rng(0).standard_normal((5, 1024)))
    assert p.shape == (5, 2)
    assert np.allclose(p[:, 0], 1 / (1 + np.exp(-3.0)))
    assert np.allclose(p[:, 1], 1 / (1 + np.exp(3.0)))


def test_single_layer_head_and_temperature(tmp_path):
    path = tmp_path / "h.npz"
    W1 = np.zeros((1024, 1), dtype=np.float32)
    W1[0, 0] = 1.0
    np.savez(
        path,
        W1=W1,
        b1=np.zeros(1),
        labels=np.array(["Acris crepitans"]),
        common_names=np.array(["Northern Cricket Frog"]),
        taxa=np.array(["amphibian"]),
        thresholds=np.array([0.0]),
        temperature=np.array(2.0),
        embedding_mean=np.zeros(1024),
        embedding_std=np.ones(1024),
    )
    head = FrogInsectHead.from_npz(path)
    emb = np.zeros((1, 1024))
    emb[0, 0] = 4.0
    assert head.predict_proba(emb)[0, 0] == pytest.approx(1 / (1 + np.exp(-2.0)))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.pop("labels"),
        lambda a: a.__setitem__("W1", np.zeros((10, 8))),
        lambda a: a.__setitem__("taxa", np.array(["amphibian", "human"])),
        lambda a: a.__setitem__("thresholds", np.array([0.2, 1.5])),
        lambda a: a.__setitem__("temperature", np.array(0.0)),
        lambda a: a.pop("b2"),
        lambda a: a.__setitem__("embedding_std", np.ones(3)),
    ],
)
def test_invalid_heads_rejected(frog_head, tmp_path, mutate):
    with np.load(frog_head) as z:
        arrays = {k: z[k] for k in z.files}
    mutate(arrays)
    path = tmp_path / "bad.npz"
    np.savez(path, **arrays)
    with pytest.raises(HeadFormatError):
        FrogInsectHead.from_npz(path)


def test_object_arrays_are_refused(tmp_path):
    path = tmp_path / "pickle.npz"
    np.savez(path, labels=np.array([{"x": 1}], dtype=object))
    with pytest.raises(ValueError):
        FrogInsectHead.from_npz(path)


def test_adapter_disabled_by_default(frog_head):
    a = FrogInsectAdapter(SharedBirdNET(), model_path=frog_head, enabled=False)
    a.load()
    assert a.status() == "disabled"
    assert "validated" in a.unavailable_reason()
    assert a.experimental is True and a.taxon_scope == ["amphibian", "insect"]


def test_adapter_enabled_without_file_is_disabled(tmp_path):
    a = FrogInsectAdapter(SharedBirdNET(), model_path=tmp_path / "missing.npz", enabled=True)
    a.load()
    assert a.status() == "disabled"
    assert "missing.npz" in a.unavailable_reason()
    with pytest.raises(ModelUnavailable):
        a.analyze_embeddings(np.zeros((1, 1024)), np.zeros(1), 3.0, AnalysisContext("a", "r"))


def test_adapter_invalid_head_is_unavailable(tmp_path):
    bad = tmp_path / "bad.npz"
    np.savez(bad, W1=np.zeros((3, 3)))
    a = FrogInsectAdapter(SharedBirdNET(), model_path=bad, enabled=True)
    a.load()
    assert a.status() == "unavailable"
    assert "invalid" in a.unavailable_reason()


class _NoRuntime(SharedBirdNET):
    def load(self):
        return None


def test_analyze_embeddings_applies_per_class_floors(frog_head):
    a = FrogInsectAdapter(_NoRuntime(), model_path=frog_head, enabled=True)
    a.load()
    assert a.status() == "ready"
    assert a.version == "0.0.1-test" and a.license == "MIT"
    ctx = AnalysisContext(analysis_id="ana_x", model_run_id="run_f", raw_threshold=0.01)
    starts = np.array([0.0, 3.0, 6.0])
    out = a.analyze_embeddings(np.zeros((3, 1024), dtype=np.float32), starts, 7.5, ctx)
    # Cricket scores 0.047: above the raw floor 0.01 but below its class floor 0.5.
    assert [d.common_name for d in out.detections] == ["Spring Peeper"] * 3
    assert [d.id for d in out.detections] == ["det_0", "det_1", "det_2"]
    assert out.detections[-1].end_seconds == 7.5  # clipped to the recording end
    assert all(d.plausibility == "unknown" and d.taxon == "amphibian" for d in out.detections)
    assert out.detections[0].confidence == pytest.approx(0.9526)
    assert a.model_sha256() and len(a.model_sha256()) == 64
    with pytest.raises(Exception):  # noqa: B017
        a.analyze_embeddings(np.zeros((2, 1024)), starts, 7.5, ctx)

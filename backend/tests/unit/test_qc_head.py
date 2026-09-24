"""Tests for the soundscape QC head (thicket.models.qc_head).

Every packaged version (qc_head_v2 when present, and qc_head_v1) runs the same
checks through the parametrized ``head`` fixture.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from thicket.models.qc_head import (
    FORMAT,
    QCHead,
    QCHeadUnavailable,
    artifact_path,
    available_versions,
    default_path,
    load_default,
    load_version,
)

EXPECTED = (
    "rain",
    "wind",
    "thunder",
    "water",
    "engine_machinery",
    "human_nonspeech",
    "domestic_animal",
    "bird",
    "insect",
    "frog",
)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "soundscape_30s.flac"


VERSIONS = available_versions()


@pytest.fixture(scope="module", params=VERSIONS)
def head(request) -> QCHead:
    return load_version(request.param)


def _synthetic(head: QCHead, n: int = 3, seed: int = 0) -> np.ndarray:
    """Embeddings near the training distribution (per-dim mean +- std of the mean half)."""
    rng = np.random.default_rng(seed)
    d = head.embedding_dim
    mu, sd = head.feature_mean[:d], head.feature_std[:d]
    return np.maximum(mu + 0.5 * sd * rng.standard_normal((n, d)), 0.0).astype(np.float32)


def test_v1_is_packaged_and_loadable_by_name():
    assert "qc_head_v1" in VERSIONS
    assert load_version("qc_head_v1").version == "qc_head_v1"
    with pytest.raises(QCHeadUnavailable):
        artifact_path("qc_head_v0")


def test_default_is_the_newest_packaged_version():
    assert default_path() == artifact_path(VERSIONS[0])
    assert load_default().version == VERSIONS[0]
    if "qc_head_v2" in VERSIONS:
        assert load_default().version == "qc_head_v2"


@pytest.mark.parametrize("version", VERSIONS)
def test_artifact_is_pickle_free_and_complete(version):
    with np.load(artifact_path(version), allow_pickle=False) as z:
        assert str(z["format"]) == FORMAT
        assert str(z["version"]) == version
        for key in ("feature_mean", "feature_std", "W", "b", "platt_a", "platt_b", "thresholds"):
            assert z[key].dtype == np.float32
            assert np.all(np.isfinite(z[key]))
        assert len(str(z["birdnet_sha256"])) == 64


def test_shapes_and_categories(head: QCHead):
    assert head.categories == EXPECTED
    k, d = len(EXPECTED), head.embedding_dim
    assert d == 1024
    assert head.W.shape == (2 * d, k)
    assert head.thresholds.shape == (k,)
    assert np.all((head.thresholds > 0) & (head.thresholds < 1))
    # Strict thresholds are the lowest cut reaching precision >= 0.9 on
    # cross-validated predictions; they can sit below the F1 cut when that
    # cut is already above 0.9 precision.
    assert np.all((head.thresholds_high_precision > 0) & (head.thresholds_high_precision <= 1))
    assert head.category_kind["rain"] == "geophony"
    assert head.category_kind["bird"] == "biophony"
    assert head.card.get("version") == head.version
    assert head.card.get("artifact") == f"{head.version}.npz"


def test_predict_on_synthetic_embedding(head: QCHead):
    emb = _synthetic(head)
    probs = head.predict(emb)
    assert list(probs) == list(EXPECTED)
    assert all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in probs.values())
    arr = head.predict_array(emb)
    assert arr.shape == (len(EXPECTED),)
    np.testing.assert_allclose(arr, [probs[c] for c in EXPECTED])


def test_deterministic_and_order_invariant_within_a_segment(head: QCHead):
    emb = _synthetic(head, n=2, seed=1)
    a = head.predict_array(emb)
    b = head.predict_array(emb.copy())
    assert np.array_equal(a, b)
    np.testing.assert_allclose(head.predict_array(emb[::-1]), a, rtol=0, atol=1e-12)
    # One segment or fewer: segment_max and whole pooling agree.
    np.testing.assert_allclose(
        head.predict_array(emb, mode="whole"), head.predict_array(emb, mode="segment_max")
    )


def test_single_window_input_accepted(head: QCHead):
    e = _synthetic(head, n=1)
    np.testing.assert_allclose(head.predict_array(e[0]), head.predict_array(e))


def test_segment_max_is_max_over_segments(head: QCHead):
    emb = _synthetic(head, n=7, seed=2)
    segs = head.predict_segments(emb)
    assert segs.shape == (len(head.segments(7)), len(EXPECTED))
    np.testing.assert_allclose(head.predict_array(emb, mode="segment_max"), segs.max(axis=0))


def test_default_recording_pooling_needs_persistence(head: QCHead):
    assert head.recording_pooling == "segment_quantile"
    assert 0.0 < head.segment_quantile < 1.0
    emb = _synthetic(head, n=12, seed=4)  # 6 segments of 2 windows
    segs = head.predict_segments(emb)
    k = max(1, int(np.ceil(head.segment_quantile * len(segs))))
    expected = -np.sort(-segs, axis=0)[k - 1]
    np.testing.assert_allclose(head.predict_array(emb), expected)
    assert np.all(head.predict_array(emb) <= head.predict_array(emb, mode="segment_max") + 1e-12)
    # Short recordings (one segment) are scored like a single clip.
    short = emb[:2]
    np.testing.assert_allclose(head.predict_array(short), head.predict_array(short, mode="whole"))


def test_flags_match_thresholds(head: QCHead):
    emb = _synthetic(head, n=4, seed=3)
    probs = head.predict(emb)
    expected = [c for c in EXPECTED if probs[c] >= head.threshold(c)]
    assert head.flags(probs) == expected
    assert head.flags(emb) == expected
    fake = {c: 0.0 for c in EXPECTED} | {"wind": 0.999, "bird": 0.999}
    assert head.flags(fake) == ["wind", "bird"]
    assert head.contamination_flags(fake) == ["wind"]
    assert set(head.flags(fake, high_precision=True)) <= {"wind", "bird"}


@pytest.mark.parametrize(
    "bad",
    [np.zeros((0, 1024)), np.zeros((3, 512)), np.zeros((2, 3, 1024)), np.full((2, 1024), np.nan)],
)
def test_rejects_bad_input(head: QCHead, bad):
    with pytest.raises(ValueError):
        head.predict(bad)


def test_inference_does_not_import_sklearn():
    code = (
        "import sys, numpy as np\n"
        "from thicket.models.qc_head import load_default\n"
        "h = load_default()\n"
        "h.predict(np.zeros((3, 1024), dtype=np.float32))\n"
        "assert 'sklearn' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.birdnet
def test_real_soundscape_fixture(head: QCHead):
    """30 s dawn-chorus soundscape (BirdNET-Analyzer example): no contamination warning.

    The head's own ``bird`` score is NOT high on this real recording (ESC-50's
    close 'chirping birds' clips differ from a distant chorus; see the real
    soundscape checks in ml/reports/qc_esc50_v1.md and qc_esc50_v2.md), so we
    do not assert it.
    """
    from thicket.models.birdnet_runtime import BirdNETRuntime, BirdNETUnavailable, frame_windows
    from thicket.services.audio_io import decode

    try:
        rt = BirdNETRuntime()
        rt.load()
    except BirdNETUnavailable as exc:
        pytest.skip(str(exc))
    assert head.matches_backbone(rt.model_sha256)
    x, _ = decode(FIXTURE, target_sr=48000)
    windows, _ = frame_windows(x)
    _, emb = rt.infer(windows)
    probs = head.predict(emb)
    assert probs["engine_machinery"] < head.threshold("engine_machinery")
    assert head.contamination_flags(probs) == []
    # The backend warns only when p > max(0.5, threshold).
    assert all(
        probs[c] <= max(0.5, head.threshold(c))
        for c in head.categories
        if head.category_kind[c] != "biophony"
    )

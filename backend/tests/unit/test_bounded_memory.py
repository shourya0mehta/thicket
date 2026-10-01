"""The bounded-memory paths give the same numbers as the whole-array ones.

These paths keep a 10 minute recording under a 512 MB server: Welch in blocks,
frame statistics in blocks, spectral indices from per-row sums, BirdNET windows
in batches, and decoding through a temporary file instead of a pipe.
"""

from __future__ import annotations

import glob
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import welch

from thicket.domain import acoustic_indices as ai
from thicket.domain.quality import low_frequency_fraction, silence_fraction
from thicket.domain.signal_profile import band_fractions_and_centroid
from thicket.domain.spectral import frame_blocks, welch_psd
from thicket.models import birdnet as birdnet_mod
from thicket.models.birdnet_runtime import frame_windows
from thicket.services.audio_io import AudioDecodeError, decode

SR = 48_000
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "soundscape_30s.flac"


def noise(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) * 0.2 + 0.01).astype(np.float32)


@pytest.mark.parametrize("n", [1, 63, 64, 4095, 4096, 4097, 9000, 600_001])
@pytest.mark.parametrize("nperseg", [4096, 4095, 256, 7])
def test_welch_psd_matches_scipy(n: int, nperseg: int) -> None:
    x = noise(n).astype(np.float64)
    f_ref, p_ref = welch(x, fs=SR, nperseg=min(nperseg, n), detrend="constant")
    f, p = welch_psd(x, SR, nperseg=nperseg)
    np.testing.assert_allclose(f, f_ref)
    np.testing.assert_allclose(p, p_ref, rtol=1e-10, atol=1e-30)


def test_welch_psd_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        welch_psd(np.zeros(0), SR)


def test_frame_blocks_cover_whole_frames_only() -> None:
    x = np.arange(10_007, dtype=np.float32)
    blocks = list(frame_blocks(x, frame=100, block=1_000))
    assert all(b.dtype == np.float64 for b in blocks)
    joined = np.concatenate([b.reshape(-1) for b in blocks])
    np.testing.assert_array_equal(joined, x[:10_000])


def test_quality_and_profile_match_whole_array_welch() -> None:
    x = noise(SR * 20, seed=3)
    x[: SR * 5] *= 1e-5  # a quiet stretch, so the silence fraction is not trivial
    f, p = welch(x.astype(np.float64), fs=SR, nperseg=4096, detrend="constant")
    keep = f > 0
    low_ref = p[keep & (f < 200.0)].sum() / p[keep].sum()
    assert low_frequency_fraction(x, SR) == pytest.approx(low_ref, rel=1e-9)
    centroid_ref = float(np.sum(f[keep] * p[keep]) / p[keep].sum())
    assert band_fractions_and_centroid(x, SR)[1] == pytest.approx(centroid_ref, rel=1e-9)

    frame = int(0.05 * SR)
    y = x[: (x.size // frame) * frame].astype(np.float64).reshape(-1, frame)
    quiet_ref = float(np.mean(np.sqrt(np.mean(y * y, axis=1)) < 10 ** (-60 / 20)))
    assert silence_fraction(x, SR) == pytest.approx(quiet_ref)
    assert 0.2 < quiet_ref < 0.3


def test_streamed_spectrum_stats_match_the_full_array() -> None:
    x = noise(SR * 3, seed=5)
    A, freqs = ai.amplitude_spectrogram(x, SR)
    full = ai.SpectrumStats.from_array(A)
    # Tiny blocks put many block boundaries inside the signal (ACI spans them).
    streamed = ai.SpectrumStats.from_blocks(lambda: ai.spectrogram_blocks(x, block=7))
    assert streamed.n_frames == full.n_frames == A.shape[1]
    assert streamed.peak == full.peak
    for name in ("row_sum", "row_sumsq", "row_absdiff", "row_above"):
        np.testing.assert_allclose(getattr(streamed, name), getattr(full, name), rtol=1e-9)
    np.testing.assert_allclose(full.row_absdiff, np.abs(np.diff(A, axis=1)).sum(axis=1), 1e-6)

    values = ai.compute_indices(x, SR)
    assert values.acoustic_complexity_index == ai.acoustic_complexity_index(A)
    assert values.acoustic_diversity_index == ai.acoustic_diversity_index(A, freqs)
    assert values.acoustic_evenness_index == ai.acoustic_evenness_index(A, freqs)
    assert values.bioacoustic_index == ai.bioacoustic_index(A, freqs)
    assert values.ndsi == ai.ndsi(A, freqs)
    assert values.spectral_entropy == ai.spectral_entropy(A)


def test_silent_input_still_gives_zero_indices() -> None:
    assert all(v == 0.0 for k, v in ai.compute_indices(np.zeros(SR), SR).as_dict().items())


class FakeRuntime:
    """Deterministic stand-in for BirdNET: logits and embeddings from window sums."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def infer(self, windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        self.batches.append(windows.shape[0])
        s = windows.astype(np.float64).sum(axis=1, keepdims=True)
        logits = (s * np.array([[0.001, -0.002, 0.003]])).astype(np.float32)
        return logits, windows[:, :4].copy()


@pytest.mark.parametrize("hop", [3.0, 1.0])
def test_infer_windows_in_batches_matches_framing_everything(
    monkeypatch: pytest.MonkeyPatch, hop: float
) -> None:
    monkeypatch.setattr(birdnet_mod, "INFER_BATCH", 2)
    x = noise(int(SR * 13.4), seed=7)
    rt = FakeRuntime()
    starts, probs, embs = birdnet_mod.infer_windows(rt, x, hop)  # type: ignore[arg-type]

    windows, ref_starts = frame_windows(x, hop_seconds=hop, min_tail_seconds=1.0)
    ref_logits, ref_embs = FakeRuntime().infer(windows)
    np.testing.assert_array_equal(starts, ref_starts)
    np.testing.assert_array_equal(probs, 1.0 / (1.0 + np.exp(-ref_logits.astype(np.float64))))
    np.testing.assert_array_equal(embs, ref_embs)
    assert max(rt.batches) == 2 and sum(rt.batches) == len(ref_starts)


def _decode_temp_files() -> set[str]:
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "thicket-decode-*")))


def test_decode_reads_through_a_temp_file_and_removes_it(tmp_path: Path) -> None:
    before = _decode_temp_files()
    x, sr = decode(FIXTURE, target_sr=SR, mono=True, max_seconds=5.0)
    assert sr == SR and x.dtype == np.float32 and x.flags.writeable
    assert abs(x.size - 5 * SR) <= SR // 100
    assert _decode_temp_files() == before

    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"RIFF....not audio")
    with pytest.raises(AudioDecodeError):
        decode(broken, target_sr=SR)
    assert _decode_temp_files() == before

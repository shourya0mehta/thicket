import math

import numpy as np
import pytest
from tests.helpers import SR, tone, white_noise

from thicket.domain import acoustic_indices as ai


def spec(x):
    return ai.amplitude_spectrogram(x, SR)


def test_spectral_entropy_noise_higher_than_tone():
    A_noise, _ = spec(white_noise(3.0))
    A_tone, _ = spec(tone(3000, 3.0))
    hn, ht = ai.spectral_entropy(A_noise), ai.spectral_entropy(A_tone)
    assert hn > 0.95
    assert ht < 0.3
    assert hn > ht


def test_temporal_entropy_stationary_higher_than_impulsive():
    stationary = white_noise(3.0)
    clicks = np.zeros(3 * SR, dtype=np.float32)
    clicks[:: SR // 2] = 1.0
    assert ai.temporal_entropy(stationary) > 0.95
    assert ai.temporal_entropy(clicks) < 0.5


def test_ndsi_sign_follows_band():
    A4, f = spec(tone(4000, 3.0))
    A15, _ = spec(tone(1500, 3.0))
    assert ai.ndsi(A4, f) > 0.9
    assert ai.ndsi(A15, f) < -0.9


def test_adi_multiband_noise_higher_than_single_tone():
    A_noise, f = spec(white_noise(3.0))
    A_tone, _ = spec(tone(2500, 3.0))
    adi_noise = ai.acoustic_diversity_index(A_noise, f)
    adi_tone = ai.acoustic_diversity_index(A_tone, f)
    assert adi_noise == pytest.approx(math.log(10), abs=0.05)  # even over 10 bands
    assert adi_tone < adi_noise
    # Evenness goes the other way: AEI (Gini) is high for a single band.
    assert ai.acoustic_evenness_index(A_tone, f) > ai.acoustic_evenness_index(A_noise, f)


def test_bi_higher_with_birdband_energy():
    base = white_noise(3.0, std=0.001)
    A_quiet, f = spec(base)
    A_song, _ = spec(base + tone(4000, 3.0, amp=0.3))
    assert ai.bioacoustic_index(A_song, f) > ai.bioacoustic_index(A_quiet, f)


def test_aci_higher_for_modulated_than_steady():
    t = np.arange(3 * SR) / SR
    steady = tone(3000, 3.0, amp=0.3)
    chirps = (steady * (np.sin(2 * np.pi * 4 * t) > 0)).astype(np.float32)
    A_s, _ = spec(steady)
    A_c, _ = spec(chirps)
    assert ai.acoustic_complexity_index(A_c) > ai.acoustic_complexity_index(A_s)


def test_gini_formula():
    assert ai.gini(np.array([1.0, 1.0, 1.0])) == pytest.approx(0.0)
    assert ai.gini(np.array([0.0, 0.0, 1.0])) == pytest.approx(2 / 3)
    assert ai.gini(np.zeros(4)) == 0.0


def test_band_mask_snaps_to_nearest_bins():
    f = np.fft.rfftfreq(512, 1 / SR)  # 93.75 Hz bins
    band = f[ai.band_mask(f, 1000, 2000)]
    assert band[0] == pytest.approx(1031.25) and band[-1] == pytest.approx(1968.75)
    # Adjacent bands share a snapped edge bin, as in soundecology and scikit-maad.
    assert f[ai.band_mask(f, 3000, 4000)][-1] == pytest.approx(4031.25)
    assert f[ai.band_mask(f, 4000, 5000)][0] == pytest.approx(4031.25)


def test_silence_gives_zeros_and_no_nan():
    v = ai.compute_indices(np.zeros(2 * SR, dtype=np.float32), SR)
    assert all(val == 0.0 for val in v.as_dict().values())


def test_short_input_and_finite_values():
    v = ai.compute_indices(white_noise(0.005), SR)
    assert all(math.isfinite(val) for val in v.as_dict().values())


def test_deterministic():
    x = white_noise(2.0) + tone(3000, 2.0, amp=0.1)
    assert ai.compute_indices(x, SR) == ai.compute_indices(x.copy(), SR)

"""Cross-check against scikit-maad (dev-only dependency; skipped if not installed).

Both implementations get the same amplitude spectrogram, so this checks the
index formulas and band conventions, not spectrogram parameters.
"""

import warnings

import numpy as np
import pytest
from tests.helpers import SR, tone, white_noise

from thicket.domain import acoustic_indices as ai

maad_alpha = pytest.importorskip("maad.features.alpha_indices")


@pytest.fixture(scope="module")
def signal():
    rng = np.random.default_rng(7)
    t = np.arange(4 * SR) / SR
    x = (
        0.3 * np.sin(2 * np.pi * 4000 * t) * (1 + np.sin(2 * np.pi * 3 * t)) / 2
        + 0.1 * np.sin(2 * np.pi * 1500 * t)
        + 0.02 * rng.standard_normal(t.size)
    ).astype(np.float32)
    return x + tone(7000, 4.0, amp=0.05) + white_noise(4.0, std=0.005)


def test_matches_maad(signal):
    A, fn = ai.amplitude_spectrogram(signal, SR)
    A64 = A.astype(np.float64)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, _, aci = maad_alpha.acoustic_complexity_index(A64)
        adi = maad_alpha.acoustic_diversity_index(
            A64, fn, fmin=0, fmax=10000, bin_step=1000, dB_threshold=-50
        )
        aei = maad_alpha.acoustic_eveness_index(
            A64, fn, fmin=0, fmax=10000, bin_step=1000, dB_threshold=-50
        )
        bi = maad_alpha.bioacoustics_index(A64, fn, flim=(2000, 8000), R_compatible="soundecology")
        # maad labels 1 kHz bins by their lower edge and selects labels inclusively.
        ndsi = maad_alpha.soundscape_index(
            A64**2, fn, flim_bioPh=(2000, 10000), flim_antroPh=(1000, 1000), R_compatible="seewave"
        )[0]
    df = fn[1] - fn[0]
    assert ai.acoustic_complexity_index(A) == pytest.approx(aci, rel=1e-5)
    assert ai.acoustic_diversity_index(A, fn) == pytest.approx(adi, abs=1e-5)
    assert ai.acoustic_evenness_index(A, fn) == pytest.approx(aei, abs=1e-5)
    # maad's soundecology variant divides by df in Hz; ours multiplies by df in kHz.
    assert ai.bioacoustic_index(A, fn) == pytest.approx(bi * df * df / 1000.0, rel=1e-5)
    # maad averages then rescales by the mean bin count, so allow a small difference.
    assert ai.ndsi(A, fn) == pytest.approx(ndsi, abs=0.02)

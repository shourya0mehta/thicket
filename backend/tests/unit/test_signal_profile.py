"""Signal profile: band fractions, centroid, per-channel levels, imbalance."""

import numpy as np
import pytest
from tests.helpers import SR, tone, white_noise

from thicket.domain.quality import level_stats
from thicket.domain.signal_profile import (
    band_fractions_and_centroid,
    channel_imbalance_db,
    compute_signal_profile,
    high_band_fraction,
)


@pytest.mark.parametrize(
    "freq, band",
    [(500, 0), (2000, 1), (6000, 2), (12000, 3)],
)
def test_tone_lands_in_its_band(freq, band):
    fractions, centroid = band_fractions_and_centroid(tone(freq, 2.0), SR)
    assert fractions[band] > 0.98
    assert sum(fractions) == pytest.approx(1.0, abs=1e-6)
    assert centroid == pytest.approx(freq, rel=0.05)


def test_white_noise_is_spread_by_bandwidth():
    (b0, b1, b2, b3), centroid = band_fractions_and_centroid(white_noise(4.0), SR)
    # Flat spectrum to 24 kHz: shares follow band widths 1, 3, 4 and 16 kHz.
    assert b0 == pytest.approx(1 / 24, abs=0.01)
    assert b1 == pytest.approx(3 / 24, abs=0.01)
    assert b2 == pytest.approx(4 / 24, abs=0.01)
    assert b3 == pytest.approx(16 / 24, abs=0.02)
    assert centroid == pytest.approx(12000, rel=0.03)


def test_profile_levels_and_channels():
    left = tone(1000, 2.0, amp=0.5)
    right = tone(1000, 2.0, amp=0.05)
    stereo = np.stack([left, right], axis=1)
    levels = level_stats(stereo)
    p = compute_signal_profile((left + right) / 2, SR, levels)
    assert p.channel_rms_dbfs[0] == pytest.approx(-9.03, abs=0.05)
    assert p.channel_rms_dbfs[1] == pytest.approx(-29.03, abs=0.05)
    assert channel_imbalance_db(p) == pytest.approx(20.0, abs=0.1)
    assert p.peak_dbfs == pytest.approx(-6.02, abs=0.05)
    assert p.clipping_fraction == 0.0


def test_mono_has_no_imbalance_and_dead_channel_is_flagged():
    mono = compute_signal_profile(tone(1000, 1.0), SR, level_stats(tone(1000, 1.0)))
    assert channel_imbalance_db(mono) is None
    dead = {"channel_rms_dbfs": [-30.0, -120.0]}
    assert channel_imbalance_db(dead) == pytest.approx(90.0)


def test_dc_and_clipping_are_reported():
    x = np.clip(tone(1000, 1.0, amp=2.0) + 0.05, -1, 1)
    p = compute_signal_profile(x, SR, level_stats(x))
    assert p.clipping_fraction > 0.3
    assert p.dc_offset > 0.01


def test_high_band_fraction_helper():
    assert high_band_fraction(
        {"band_fraction_4_8k": 0.2, "band_fraction_8k_plus": 0.1}
    ) == pytest.approx(0.3)


def test_silence_and_short_input():
    p = compute_signal_profile(np.zeros(SR, dtype=np.float32), SR, level_stats(np.zeros(SR)))
    assert p.rms_dbfs == -120.0 and p.spectral_centroid_hz == 0.0
    assert band_fractions_and_centroid(np.zeros(10), SR) == ((0.0, 0.0, 0.0, 0.0), 0.0)

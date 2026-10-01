"""Per-recording signal profile for recorder health baselines.

A :class:`~thicket.api.platform_schemas.SignalProfile` summarizes how a
recording sounds, independent of any species model, so that recordings from
the same deployment can be compared over weeks: a microphone that fills with
water loses its high band, a loose cable shows as a DC offset, a recorder
turned into a wall drops its level.

Measurements
------------
* Band energy fractions from a Welch PSD of the 48 kHz mono mix (DC bin
  excluded): 0 to 1 kHz, 1 to 4 kHz, 4 to 8 kHz, 8 kHz and up. They sum to 1.
* Spectral centroid in Hz over the same PSD.
* Level: RMS and peak in dBFS, clipping fraction and DC offset from the
  native-rate level statistics (every original channel).
* Per-channel RMS in dBFS from the original channels, so a stereo recorder
  with one dead microphone is visible.

Everything is pure NumPy/SciPy and deterministic for the same input.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import welch

from thicket.api.platform_schemas import SignalProfile
from thicket.domain.quality import DB_FLOOR, LevelStats, to_dbfs

BAND_EDGES_HZ = (0.0, 1000.0, 4000.0, 8000.0)
PSD_NPERSEG = 4096


def band_fractions_and_centroid(
    mono: np.ndarray, sample_rate: int
) -> tuple[tuple[float, float, float, float], float]:
    """Welch PSD energy fractions per band and the spectral centroid (Hz)."""
    x = np.asarray(mono, dtype=np.float64)
    if x.size < 64:
        return (0.0, 0.0, 0.0, 0.0), 0.0
    nperseg = min(PSD_NPERSEG, x.size)
    f, p = welch(x, fs=sample_rate, nperseg=nperseg, detrend="constant")
    keep = f > 0
    f, p = f[keep], p[keep]
    total = float(np.sum(p))
    if total <= 0 or not math.isfinite(total):
        return (0.0, 0.0, 0.0, 0.0), 0.0
    e0, e1, e2 = BAND_EDGES_HZ[1], BAND_EDGES_HZ[2], BAND_EDGES_HZ[3]
    b0 = float(np.sum(p[f < e0])) / total
    b1 = float(np.sum(p[(f >= e0) & (f < e1)])) / total
    b2 = float(np.sum(p[(f >= e1) & (f < e2)])) / total
    b3 = float(np.sum(p[f >= e2])) / total
    centroid = float(np.sum(f * p) / total)
    return (b0, b1, b2, b3), centroid


def compute_signal_profile(mono: np.ndarray, sample_rate: int, levels: LevelStats) -> SignalProfile:
    (b0, b1, b2, b3), centroid = band_fractions_and_centroid(mono, sample_rate)
    channel_rms = [round(to_dbfs(v), 2) for v in (levels.channel_rms or [])]
    if not channel_rms:
        channel_rms = [round(to_dbfs(levels.rms), 2)]
    return SignalProfile(
        rms_dbfs=round(to_dbfs(levels.rms), 2),
        peak_dbfs=round(to_dbfs(levels.peak), 2),
        clipping_fraction=round(float(levels.clipping_fraction), 6),
        dc_offset=round(float(levels.dc_offset), 5),
        band_fraction_0_1k=round(b0, 4),
        band_fraction_1_4k=round(b1, 4),
        band_fraction_4_8k=round(b2, 4),
        band_fraction_8k_plus=round(b3, 4),
        spectral_centroid_hz=round(centroid, 1),
        channel_rms_dbfs=channel_rms,
    )


def high_band_fraction(profile: SignalProfile | dict) -> float:
    """``band_fraction_4_8k + band_fraction_8k_plus``: the share that muffling removes."""
    if isinstance(profile, dict):
        return float(profile.get("band_fraction_4_8k", 0.0)) + float(
            profile.get("band_fraction_8k_plus", 0.0)
        )
    return profile.band_fraction_4_8k + profile.band_fraction_8k_plus


def channel_imbalance_db(profile: SignalProfile | dict) -> float | None:
    """Difference between the loudest and quietest channel in dB; None for mono."""
    values = (
        profile.get("channel_rms_dbfs", [])
        if isinstance(profile, dict)
        else profile.channel_rms_dbfs
    )
    levels = [float(v) for v in values if v is not None and float(v) > DB_FLOOR + 1e-9]
    if len(values) < 2:
        return None
    if len(levels) < len(values):
        # A channel at the floor is a dead channel: report the largest possible gap.
        return abs(float(max(values)) - DB_FLOOR)
    return float(max(levels) - min(levels))

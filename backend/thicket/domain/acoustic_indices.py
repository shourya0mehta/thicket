"""Signal-level soundscape indices (no species model involved).

All indices are computed on the 48 kHz mono mix from one amplitude
spectrogram ``A(f, t)``: Hann window, ``n_fft = 512`` (93.75 Hz bins),
no overlap, magnitude of the one-sided FFT. Where a band edge does not fall
on an FFT bin, it snaps to the nearest bin and the band is inclusive of both
edge bins; this is the convention of the soundecology R package and of
scikit-maad, so values are comparable with those tools given the same
spectrogram.

Indices
-------
ACI, Acoustic Complexity Index (Pieretti, Farina and Morri 2011, Ecological
Indicators 11: 868-873)::

    ACI = sum_f [ sum_t |A(f, t+1) - A(f, t)| / sum_t A(f, t) ]

computed over the whole recording as one temporal step and summed over all
frequency bins (scikit-maad's ``ACI_sum``). Bins with no energy add 0.

ADI and AEI, Acoustic Diversity and Evenness Indices (Villanueva-Rivera,
Pijanowski, Doucette and Pekin 2011, Landscape Ecology 26: 1233-1246): the
spectrogram is converted to dB relative to its loudest cell,
``L = 20 log10(A / max A)``. For ten 1 kHz bands from 0 to 10 kHz, the band
score ``s_b`` is the share of cells with ``L >= -50 dB``. Then::

    ADI = -sum_b p_b ln p_b,  p_b = s_b / sum s_b     (Shannon, natural log)
    AEI = Gini(s_1..s_10)

(-50 dB relative to the loudest cell is soundecology's "dBFS" convention.)

BI, Bioacoustic Index (Boelman, Asner, Hart and Martin 2007, Ecological
Applications 17: 2137-2144): the mean spectrum ``M(f) = mean_t A(f, t) / max A``
in dB, restricted to 2 to 8 kHz, minus its minimum; the area under that curve
in dB x kHz::

    BI = sum_{2 kHz <= f <= 8 kHz} (M_dB(f) - min M_dB) * df_kHz

scikit-maad's soundecology-compatible variant returns the same sum divided
by df in Hz instead of multiplied by df in kHz.

NDSI, Normalized Difference Soundscape Index (Kasten, Gage, Fox and Joo 2012,
Ecological Informatics 12: 50-67), from the mean power spectrum
``P(f) = mean_t A(f, t)^2``::

    alpha = sum_{1 <= f < 2 kHz} P(f)    (anthrophony)
    beta  = sum_{2 <= f < 11 kHz} P(f)   (biophony)
    NDSI  = (beta - alpha) / (beta + alpha),  in [-1, 1]

Hf, spectral entropy, and Ht, temporal entropy (Sueur, Pavoine, Hamerlynck and
Duvail 2008, PLoS ONE 3: e4065), both normalized Shannon entropies in [0, 1]::

    Hf = -sum_f q_f ln q_f / ln N,   q_f = S(f) / sum S,  S(f) = mean_t A(f, t)
    Ht = -sum_t r_t ln r_t / ln T,   r_t = e_t / sum e

where ``e_t`` is the amplitude envelope, taken as the maximum of |x| over
consecutive 512-sample frames (scikit-maad's fast envelope, seewave
convention). White noise has Hf near 1; a pure tone has Hf near 0.

Silent input yields 0 for every index. Values never contain NaN or infinity.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

N_FFT = 512
FRAME_CHUNK = 4096
ADI_MAX_HZ = 10_000.0
ADI_STEP_HZ = 1_000.0
ADI_DB_THRESHOLD = -50.0
BI_BAND_HZ = (2_000.0, 8_000.0)
NDSI_ANTHRO_HZ = (1_000.0, 2_000.0)
NDSI_BIO_HZ = (2_000.0, 11_000.0)
ENVELOPE_FRAME = 512
_TINY = 1e-300


@dataclass(frozen=True)
class IndexValues:
    acoustic_complexity_index: float
    acoustic_diversity_index: float
    acoustic_evenness_index: float
    bioacoustic_index: float
    ndsi: float
    spectral_entropy: float
    temporal_entropy: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def _finite(x: float) -> float:
    x = float(x)
    return round(x, 6) if math.isfinite(x) else 0.0


def amplitude_spectrogram(
    x: np.ndarray, sample_rate: int, n_fft: int = N_FFT
) -> tuple[np.ndarray, np.ndarray]:
    """Magnitude STFT, Hann window, hop = n_fft. Returns (A[F, T] float32, freqs[F])."""
    x = np.asarray(x, dtype=np.float32)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    n_frames = x.size // n_fft
    if n_frames == 0:
        pad = np.zeros(n_fft, dtype=np.float32)
        pad[: x.size] = x
        x, n_frames = pad, 1
    frames = x[: n_frames * n_fft].reshape(n_frames, n_fft)
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)  # periodic Hann
    out = np.empty((freqs.size, n_frames), dtype=np.float32)
    for s in range(0, n_frames, FRAME_CHUNK):
        block = frames[s : s + FRAME_CHUNK] * window
        out[:, s : s + block.shape[0]] = np.abs(np.fft.rfft(block, axis=1)).T
    return out, freqs


def band_mask(freqs: np.ndarray, f_lo: float, f_hi: float) -> np.ndarray:
    """Inclusive band with edges snapped to the nearest FFT bin (soundecology/maad)."""
    lo = freqs[int(np.argmin(np.abs(freqs - f_lo)))]
    hi = freqs[int(np.argmin(np.abs(freqs - f_hi)))]
    return (freqs >= lo) & (freqs <= hi)


def acoustic_complexity_index(A: np.ndarray) -> float:
    A = np.asarray(A, dtype=np.float64)
    if A.shape[1] < 2:
        return 0.0
    num = np.sum(np.abs(np.diff(A, axis=1)), axis=1)
    den = np.sum(A, axis=1)
    per_bin = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
    return _finite(per_bin.sum())


def _band_scores(A: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    peak = float(np.max(A)) if A.size else 0.0
    n_bands = int(math.floor(ADI_MAX_HZ / ADI_STEP_HZ))
    if peak <= 0:
        return np.zeros(n_bands)
    # A / max >= 10^(-50/20)  <=>  20 log10(A / max) >= -50 dB
    thresh = peak * 10 ** (ADI_DB_THRESHOLD / 20.0)
    scores = np.zeros(n_bands)
    for b in range(n_bands):
        f0 = b * ADI_STEP_HZ
        mask = band_mask(freqs, f0, f0 + ADI_STEP_HZ)
        cells = A[mask]
        scores[b] = float(np.mean(cells >= thresh)) if cells.size else 0.0
    return scores


def acoustic_diversity_index(A: np.ndarray, freqs: np.ndarray) -> float:
    s = _band_scores(A, freqs)
    total = s.sum()
    if total <= 0:
        return 0.0
    p = s[s > 0] / total
    return _finite(-np.sum(p * np.log(p)))


def gini(values: np.ndarray) -> float:
    """Gini coefficient (R ``ineq`` convention, uncorrected)."""
    x = np.sort(np.asarray(values, dtype=np.float64))
    n = x.size
    total = x.sum()
    if n == 0 or total <= 0:
        return 0.0
    g = np.sum(x * np.arange(1, n + 1))
    return float((2.0 * g / total - (n + 1)) / n)


def acoustic_evenness_index(A: np.ndarray, freqs: np.ndarray) -> float:
    return _finite(gini(_band_scores(A, freqs)))


def bioacoustic_index(A: np.ndarray, freqs: np.ndarray) -> float:
    A = np.asarray(A, dtype=np.float64)
    peak = float(np.max(A)) if A.size else 0.0
    if peak <= 0:
        return 0.0
    mean_spec = np.mean(A / peak, axis=1)
    db = 20.0 * np.log10(np.maximum(mean_spec, _TINY))
    seg = db[band_mask(freqs, *BI_BAND_HZ)]
    if seg.size == 0:
        return 0.0
    df_khz = float(freqs[1] - freqs[0]) / 1000.0
    return _finite(np.sum(seg - seg.min()) * df_khz)


def ndsi(A: np.ndarray, freqs: np.ndarray) -> float:
    A = np.asarray(A, dtype=np.float64)
    psd = np.mean(A * A, axis=1)
    anthro = float(psd[(freqs >= NDSI_ANTHRO_HZ[0]) & (freqs < NDSI_ANTHRO_HZ[1])].sum())
    bio = float(psd[(freqs >= NDSI_BIO_HZ[0]) & (freqs < NDSI_BIO_HZ[1])].sum())
    if anthro + bio <= 0:
        return 0.0
    return _finite((bio - anthro) / (bio + anthro))


def normalized_entropy(values: np.ndarray) -> float:
    v = np.asarray(values, dtype=np.float64)
    n = v.size
    total = v.sum()
    if n < 2 or total <= 0:
        return 0.0
    p = v[v > 0] / total
    return _finite(-np.sum(p * np.log(p)) / math.log(n))


def spectral_entropy(A: np.ndarray) -> float:
    return normalized_entropy(np.mean(np.asarray(A, dtype=np.float64), axis=1))


def amplitude_envelope(x: np.ndarray, frame: int = ENVELOPE_FRAME) -> np.ndarray:
    x = np.abs(np.asarray(x, dtype=np.float32))
    n = x.size // frame
    if n == 0:
        return np.array([x.max()]) if x.size else np.zeros(1)
    return x[: n * frame].reshape(n, frame).max(axis=1)


def temporal_entropy(x: np.ndarray) -> float:
    return normalized_entropy(amplitude_envelope(x))


def compute_indices(x: np.ndarray, sample_rate: int) -> IndexValues:
    """All indices for a mono signal (expected at 48 kHz)."""
    A, freqs = amplitude_spectrogram(x, sample_rate)
    return IndexValues(
        acoustic_complexity_index=acoustic_complexity_index(A),
        acoustic_diversity_index=acoustic_diversity_index(A, freqs),
        acoustic_evenness_index=acoustic_evenness_index(A, freqs),
        bioacoustic_index=bioacoustic_index(A, freqs),
        ndsi=ndsi(A, freqs),
        spectral_entropy=spectral_entropy(A),
        temporal_entropy=temporal_entropy(x),
    )

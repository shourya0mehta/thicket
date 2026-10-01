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
from collections.abc import Callable, Iterable, Iterator
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


def _frames_and_window(x: np.ndarray, n_fft: int) -> tuple[np.ndarray, np.ndarray]:
    """Non-overlapping frames (a view) and the periodic Hann window."""
    x = np.asarray(x, dtype=np.float32)
    n_frames = x.size // n_fft
    if n_frames == 0:
        pad = np.zeros(n_fft, dtype=np.float32)
        pad[: x.size] = x
        x, n_frames = pad, 1
    frames = x[: n_frames * n_fft].reshape(n_frames, n_fft)
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)  # periodic Hann
    return frames, window


def spectrogram_blocks(
    x: np.ndarray, n_fft: int = N_FFT, block: int = FRAME_CHUNK
) -> Iterator[np.ndarray]:
    """The magnitude spectrogram as (frames, F) float32 blocks, in time order."""
    frames, window = _frames_and_window(x, n_fft)
    for s in range(0, frames.shape[0], block):
        spec = np.abs(np.fft.rfft(frames[s : s + block] * window, axis=1))
        yield spec.astype(np.float32, copy=False)


def amplitude_spectrogram(
    x: np.ndarray, sample_rate: int, n_fft: int = N_FFT
) -> tuple[np.ndarray, np.ndarray]:
    """Magnitude STFT, Hann window, hop = n_fft. Returns (A[F, T] float32, freqs[F])."""
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    blocks = [b.T for b in spectrogram_blocks(x, n_fft)]
    return np.concatenate(blocks, axis=1).astype(np.float32, copy=False), freqs


def band_mask(freqs: np.ndarray, f_lo: float, f_hi: float) -> np.ndarray:
    """Inclusive band with edges snapped to the nearest FFT bin (soundecology/maad)."""
    lo = freqs[int(np.argmin(np.abs(freqs - f_lo)))]
    hi = freqs[int(np.argmin(np.abs(freqs - f_hi)))]
    return (freqs >= lo) & (freqs <= hi)


def adi_threshold(peak: float) -> float:
    """A / max >= 10^(-50/20)  <=>  20 log10(A / max) >= -50 dB."""
    return peak * 10 ** (ADI_DB_THRESHOLD / 20.0)


@dataclass
class SpectrumStats:
    """Per-frequency-row sums of a magnitude spectrogram A[F, T], in float64.

    Every spectral index needs only these, so a long recording can be reduced
    block by block instead of holding A (58 MB for 10 minutes at 48 kHz).
    """

    n_frames: int
    peak: float
    row_sum: np.ndarray  # sum_t A(f, t)
    row_sumsq: np.ndarray  # sum_t A(f, t)^2
    row_absdiff: np.ndarray  # sum_t |A(f, t+1) - A(f, t)|
    row_above: np.ndarray  # count of t with A(f, t) >= adi_threshold(peak)

    @classmethod
    def from_blocks(cls, blocks: Callable[[], Iterable[np.ndarray]]) -> SpectrumStats:
        """Two passes over (frames, F) blocks: sums and peak, then the ADI counts."""
        n = 0
        peak = 0.0
        row_sum = row_sumsq = row_absdiff = None
        prev: np.ndarray | None = None
        for blk in blocks():
            b = np.asarray(blk, dtype=np.float64)
            if row_sum is None:
                row_sum = np.zeros(b.shape[1])
                row_sumsq = np.zeros(b.shape[1])
                row_absdiff = np.zeros(b.shape[1])
            row_sum += b.sum(axis=0)
            row_sumsq += (b * b).sum(axis=0)
            if prev is not None:
                row_absdiff += np.abs(b[0] - prev)
            row_absdiff += np.abs(np.diff(b, axis=0)).sum(axis=0)
            prev = b[-1].copy()
            peak = max(peak, float(b.max()))
            n += b.shape[0]
        assert row_sum is not None and row_sumsq is not None and row_absdiff is not None
        row_above = np.zeros(row_sum.size)
        if peak > 0:
            thresh = adi_threshold(peak)
            for blk in blocks():
                row_above += np.count_nonzero(np.asarray(blk) >= thresh, axis=0)
        return cls(n, peak, row_sum, row_sumsq, row_absdiff, row_above)

    @classmethod
    def from_array(cls, A: np.ndarray) -> SpectrumStats:
        """Stats of a full spectrogram A[F, T] (time blocks of its transpose)."""
        A = np.asarray(A)
        return cls.from_blocks(
            lambda: (A[:, s : s + FRAME_CHUNK].T for s in range(0, A.shape[1], FRAME_CHUNK))
        )

    def row_mean(self) -> np.ndarray:
        return self.row_sum / max(self.n_frames, 1)


def aci_from_stats(st: SpectrumStats) -> float:
    if st.n_frames < 2:
        return 0.0
    per_bin = np.divide(
        st.row_absdiff, st.row_sum, out=np.zeros_like(st.row_sum), where=st.row_sum > 0
    )
    return _finite(per_bin.sum())


def band_scores_from_stats(st: SpectrumStats, freqs: np.ndarray) -> np.ndarray:
    n_bands = int(math.floor(ADI_MAX_HZ / ADI_STEP_HZ))
    scores = np.zeros(n_bands)
    if st.peak <= 0:
        return scores
    for b in range(n_bands):
        f0 = b * ADI_STEP_HZ
        mask = band_mask(freqs, f0, f0 + ADI_STEP_HZ)
        cells = int(np.count_nonzero(mask)) * st.n_frames
        scores[b] = float(st.row_above[mask].sum()) / cells if cells else 0.0
    return scores


def adi_from_scores(s: np.ndarray) -> float:
    total = s.sum()
    if total <= 0:
        return 0.0
    p = s[s > 0] / total
    return _finite(-np.sum(p * np.log(p)))


def bi_from_stats(st: SpectrumStats, freqs: np.ndarray) -> float:
    if st.peak <= 0:
        return 0.0
    mean_spec = st.row_mean() / st.peak
    db = 20.0 * np.log10(np.maximum(mean_spec, _TINY))
    seg = db[band_mask(freqs, *BI_BAND_HZ)]
    if seg.size == 0:
        return 0.0
    df_khz = float(freqs[1] - freqs[0]) / 1000.0
    return _finite(np.sum(seg - seg.min()) * df_khz)


def ndsi_from_stats(st: SpectrumStats, freqs: np.ndarray) -> float:
    psd = st.row_sumsq / max(st.n_frames, 1)
    anthro = float(psd[(freqs >= NDSI_ANTHRO_HZ[0]) & (freqs < NDSI_ANTHRO_HZ[1])].sum())
    bio = float(psd[(freqs >= NDSI_BIO_HZ[0]) & (freqs < NDSI_BIO_HZ[1])].sum())
    if anthro + bio <= 0:
        return 0.0
    return _finite((bio - anthro) / (bio + anthro))


def acoustic_complexity_index(A: np.ndarray) -> float:
    return aci_from_stats(SpectrumStats.from_array(A))


def _band_scores(A: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    return band_scores_from_stats(SpectrumStats.from_array(A), freqs)


def acoustic_diversity_index(A: np.ndarray, freqs: np.ndarray) -> float:
    return adi_from_scores(_band_scores(A, freqs))


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
    return bi_from_stats(SpectrumStats.from_array(A), freqs)


def ndsi(A: np.ndarray, freqs: np.ndarray) -> float:
    return ndsi_from_stats(SpectrumStats.from_array(A), freqs)


def normalized_entropy(values: np.ndarray) -> float:
    v = np.asarray(values, dtype=np.float64)
    n = v.size
    total = v.sum()
    if n < 2 or total <= 0:
        return 0.0
    p = v[v > 0] / total
    return _finite(-np.sum(p * np.log(p)) / math.log(n))


def spectral_entropy(A: np.ndarray) -> float:
    return normalized_entropy(SpectrumStats.from_array(A).row_mean())


def amplitude_envelope(x: np.ndarray, frame: int = ENVELOPE_FRAME) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    n = x.size // frame
    if n == 0:
        return np.array([np.abs(x).max()]) if x.size else np.zeros(1)
    out = np.empty(n, dtype=np.float32)
    per_block = max(1, (1 << 20) // frame)
    for first in range(0, n, per_block):  # |x| one block at a time
        count = min(per_block, n - first)
        seg = np.abs(x[first * frame : (first + count) * frame]).reshape(count, frame)
        out[first : first + count] = seg.max(axis=1)
    return out


def temporal_entropy(x: np.ndarray) -> float:
    return normalized_entropy(amplitude_envelope(x))


def compute_indices(x: np.ndarray, sample_rate: int) -> IndexValues:
    """All indices for a mono signal (expected at 48 kHz), in bounded memory.

    The spectrogram is reduced block by block (twice: once for sums and the
    peak, once for the ADI counts), never held whole.
    """
    freqs = np.fft.rfftfreq(N_FFT, d=1.0 / sample_rate)
    st = SpectrumStats.from_blocks(lambda: spectrogram_blocks(x))
    scores = band_scores_from_stats(st, freqs)
    return IndexValues(
        acoustic_complexity_index=aci_from_stats(st),
        acoustic_diversity_index=adi_from_scores(scores),
        acoustic_evenness_index=_finite(gini(scores)),
        bioacoustic_index=bi_from_stats(st, freqs),
        ndsi=ndsi_from_stats(st, freqs),
        spectral_entropy=normalized_entropy(st.row_mean()),
        temporal_entropy=temporal_entropy(x),
    )

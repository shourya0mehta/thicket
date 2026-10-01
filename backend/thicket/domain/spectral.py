"""Memory-bounded spectral helpers for long recordings.

``scipy.signal.welch`` on a whole recording builds every overlapping segment,
its detrended copy and its FFT at once: about ten times the signal in float64,
so a 5 minute file at 48 kHz briefly needs more than 500 MB. These helpers give
the same numbers while holding only a block of segments or frames at a time,
which keeps an analysis inside a 512 MB server.

Welch is implemented with NumPy (checked against SciPy in the tests) so the
server does not import ``scipy.signal``, which alone costs about 70 MB.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

#: Segments per Welch block (4096-sample segments: about 8 MB of float64 each block).
WELCH_BLOCK_SEGMENTS = 256
#: Samples per block for frame statistics (about 8 MB of float64).
SAMPLE_BLOCK = 1 << 20


def welch_psd(
    x: np.ndarray, sample_rate: float, nperseg: int = 4096
) -> tuple[np.ndarray, np.ndarray]:
    """``scipy.signal.welch(x, fs, nperseg=nperseg, detrend="constant")`` in bounded memory.

    Same defaults as SciPy otherwise: periodic Hann window, 50% overlap, density
    scaling, mean over segments, one-sided. Only whole segments are used, as in
    SciPy. Segments are processed ``WELCH_BLOCK_SEGMENTS`` at a time and ``x``
    is converted to float64 one block at a time.
    """
    x = np.asarray(x)
    n = x.size
    if n == 0:
        raise ValueError("welch_psd needs at least one sample")
    nperseg = min(int(nperseg), n)
    step = nperseg - nperseg // 2
    n_seg = (n - nperseg) // step + 1
    win = _hann_periodic(nperseg)
    scale = 1.0 / (sample_rate * float(np.sum(win * win)))
    total = np.zeros(nperseg // 2 + 1)
    for first in range(0, n_seg, WELCH_BLOCK_SEGMENTS):
        count = min(WELCH_BLOCK_SEGMENTS, n_seg - first)
        start = first * step
        stop = start + (count - 1) * step + nperseg
        block = np.asarray(x[start:stop], dtype=np.float64)
        segs = np.lib.stride_tricks.sliding_window_view(block, nperseg)[::step]
        segs = (segs - segs.mean(axis=1, keepdims=True)) * win  # detrend="constant"
        spec = np.fft.rfft(segs, n=nperseg, axis=1)
        total += np.sum(spec.real**2 + spec.imag**2, axis=0)
    psd = total * (scale / n_seg)
    # One-sided density: double every bin except DC (and Nyquist for even lengths).
    if nperseg % 2:
        psd[1:] *= 2.0
    else:
        psd[1:-1] *= 2.0
    return np.fft.rfftfreq(nperseg, d=1.0 / sample_rate), psd


def _hann_periodic(n: int) -> np.ndarray:
    """``scipy.signal.get_window("hann", n)``: the periodic Hann window Welch uses."""
    if n == 1:
        return np.ones(1)
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)


def frame_blocks(x: np.ndarray, frame: int, block: int = SAMPLE_BLOCK) -> Iterator[np.ndarray]:
    """Whole frames of ``x`` as (k, frame) float64 blocks; a trailing partial frame is dropped."""
    x = np.asarray(x)
    n = x.size // frame
    per_block = max(1, block // frame)
    for first in range(0, n, per_block):
        count = min(per_block, n - first)
        seg = x[first * frame : (first + count) * frame]
        yield np.asarray(seg, dtype=np.float64).reshape(count, frame)

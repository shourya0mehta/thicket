"""The one canonical spectrogram renderer.

Input is the 48 kHz mono mix. Parameters:

* STFT: ``n_fft = 1024`` (46.9 Hz bins), periodic Hann window, hop 256 samples
  (5.3 ms). Frames are processed in blocks and power is averaged into at most
  :data:`MAX_WIDTH` columns, so long recordings never hold the full STFT in
  memory and a column always covers an equal share of the recording.
* Frequency axis: linear, 0 to 16 kHz (:data:`MIN_HZ`, :data:`MAX_HZ`),
  interpolated to :data:`HEIGHT` rows, low frequencies at the bottom.
* Level: ``10 log10(power)``, clipped to a fixed :data:`DYNAMIC_RANGE_DB`
  below the 99.5th percentile of the bins at or above :data:`REFERENCE_MIN_HZ`
  (so distant low-frequency rumble, which carries most of the energy in many
  field recordings, cannot push calls into the dark end), then mapped through a calm dark forest to cream
  colormap (monotonic lightness, no rainbow).
* No axes or labels; the frontend draws them from ``spectrogram_min_hz`` /
  ``spectrogram_max_hz`` and the recording duration.

Output is deterministic: identical audio gives byte-identical PNGs.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

SAMPLE_RATE = 48_000
N_FFT = 1024
HOP = 256
MAX_WIDTH = 2400
HEIGHT = 512
MIN_HZ = 0
MAX_HZ = 16_000
DYNAMIC_RANGE_DB = 65.0
REFERENCE_PERCENTILE = 99.5
REFERENCE_MIN_HZ = 1000.0
_BLOCK_FRAMES = 2048

# Dark forest to cream. Lightness increases monotonically along the ramp; the
# lower half stays dark because a typical noise floor sits 40 to 50 dB below
# the reference, which keeps calls visible against the background.
_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.00, (6, 14, 11)),
    (0.30, (10, 26, 19)),
    (0.45, (20, 48, 36)),
    (0.58, (40, 88, 67)),
    (0.70, (72, 128, 92)),
    (0.82, (140, 180, 125)),
    (0.92, (205, 218, 165)),
    (1.00, (246, 241, 220)),
]


def colormap_lut() -> np.ndarray:
    """256 x 3 uint8 lookup table built from :data:`_STOPS`."""
    pos = np.array([p for p, _ in _STOPS])
    cols = np.array([c for _, c in _STOPS], dtype=np.float64)
    x = np.linspace(0.0, 1.0, 256)
    lut = np.stack([np.interp(x, pos, cols[:, k]) for k in range(3)], axis=1)
    return np.round(lut).astype(np.uint8)


def power_columns(x: np.ndarray, max_width: int = MAX_WIDTH) -> tuple[np.ndarray, np.ndarray]:
    """Mean STFT power per output column. Returns (P[F, W], freqs[F]) for 0..MAX_HZ."""
    x = np.asarray(x, dtype=np.float32)
    if x.size < N_FFT:
        x = np.pad(x, (0, N_FFT - x.size))
    n_frames = 1 + (x.size - N_FFT) // HOP
    width = max(1, min(max_width, n_frames))
    freqs = np.fft.rfftfreq(N_FFT, d=1.0 / SAMPLE_RATE)
    keep = freqs <= MAX_HZ + 1e-6
    n_bins = int(keep.sum())
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float32)
    col_of_frame = (np.arange(n_frames, dtype=np.int64) * width) // n_frames
    sums = np.zeros((n_bins, width), dtype=np.float64)
    counts = np.bincount(col_of_frame, minlength=width).astype(np.float64)
    frames = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::HOP]
    for s in range(0, n_frames, _BLOCK_FRAMES):
        block = frames[s : s + _BLOCK_FRAMES] * window
        spec = np.fft.rfft(block, axis=1)[:, :n_bins]
        power = (spec.real**2 + spec.imag**2).astype(np.float64)
        cols = col_of_frame[s : s + block.shape[0]]
        # Columns are non-decreasing, so sum each run of equal columns at once.
        firsts = np.flatnonzero(np.r_[True, cols[1:] != cols[:-1]])
        sums[:, cols[firsts]] += np.add.reduceat(power, firsts, axis=0).T
    sums /= np.maximum(counts, 1.0)
    return sums, freqs[keep]


def to_index_array(power: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """Map power columns to (HEIGHT, W) colormap indices, low frequencies at the bottom."""
    db = 10.0 * np.log10(power + 1e-12)
    band = db[freqs >= REFERENCE_MIN_HZ]
    ref = float(np.percentile(band if band.size else db, REFERENCE_PERCENTILE))
    lo = ref - DYNAMIC_RANGE_DB
    norm = np.clip((db - lo) / DYNAMIC_RANGE_DB, 0.0, 1.0)
    if ref <= -119.0:  # digital silence: render the floor colour
        norm = np.zeros_like(norm)
    # Linear interpolation of every column onto HEIGHT evenly spaced frequencies.
    target = np.linspace(MIN_HZ, MAX_HZ, HEIGHT)
    pos = np.interp(target, freqs, np.arange(freqs.size, dtype=np.float64))
    i0 = np.floor(pos).astype(np.int64)
    i1 = np.minimum(i0 + 1, freqs.size - 1)
    w = (pos - i0)[:, None]
    rows = norm[i0] * (1.0 - w) + norm[i1] * w
    return np.round(rows[::-1] * 255.0).astype(np.uint8)


def to_image_array(power: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """(HEIGHT, W, 3) uint8 RGB version of :func:`to_index_array`."""
    return colormap_lut()[to_index_array(power, freqs)]


def render_png(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Render a PNG spectrogram of 48 kHz mono audio (paletted, exact colormap)."""
    if sample_rate != SAMPLE_RATE:
        raise ValueError("render_png expects 48 kHz mono audio")
    power, freqs = power_columns(samples)
    idx = np.ascontiguousarray(to_index_array(power, freqs))
    img = Image.frombytes("P", (idx.shape[1], idx.shape[0]), idx.tobytes())
    img.putpalette(colormap_lut().reshape(-1).tolist())
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def write_png(samples: np.ndarray, path: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    data = render_png(samples, sample_rate)
    tmp = path.with_suffix(".png.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path

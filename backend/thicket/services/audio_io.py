"""Audio decoding, probing, and writing.

FFmpeg is the canonical decoder because it handles WAV, MP3, M4A/AAC, FLAC and
OGG with one code path. When FFmpeg is missing we fall back to libsndfile
(WAV/FLAC/OGG, and MP3 on libsndfile >= 1.1) plus polyphase resampling.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf


class AudioDecodeError(Exception):
    """Raised when a file cannot be decoded as audio."""


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    codec: str | None
    bit_depth: int | None
    container: str | None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe(path: Path) -> AudioProbe:
    """Inspect an audio file without fully decoding it."""
    if ffmpeg_available():
        try:
            out = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_format",
                    str(path),
                ],
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
            info = json.loads(out)
            streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
            if not streams:
                raise AudioDecodeError("No audio stream found in file.")
            s = streams[0]
            fmt = info.get("format", {})
            duration = float(s.get("duration") or fmt.get("duration") or 0.0)
            bits = s.get("bits_per_raw_sample") or s.get("bits_per_sample")
            return AudioProbe(
                duration_seconds=duration,
                sample_rate_hz=int(s.get("sample_rate", 0)),
                channels=int(s.get("channels", 0)),
                codec=s.get("codec_name"),
                bit_depth=int(bits) if bits and str(bits).isdigit() and int(bits) > 0 else None,
                container=fmt.get("format_name"),
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
            raise AudioDecodeError("FFprobe could not read this file as audio.") from exc
    try:
        info = sf.info(str(path))
    except Exception as exc:  # noqa: BLE001 - libsndfile raises several types
        raise AudioDecodeError("This file could not be read as audio.") from exc
    bits = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "PCM_U8": 8, "PCM_S8": 8}.get(info.subtype)
    return AudioProbe(
        duration_seconds=float(info.frames) / float(info.samplerate),
        sample_rate_hz=int(info.samplerate),
        channels=int(info.channels),
        codec=info.subtype,
        bit_depth=bits,
        container=info.format,
    )


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    frac = Fraction(sr_out, sr_in).limit_denominator(1000)
    # Only the no-FFmpeg fallback resamples; importing SciPy costs ~70 MB, so do it here.
    from scipy.signal import resample_poly

    return resample_poly(x, frac.numerator, frac.denominator).astype(np.float32)


def decode(
    path: Path,
    target_sr: int | None = None,
    mono: bool = True,
    max_seconds: float | None = None,
) -> tuple[np.ndarray, int]:
    """Decode audio to float32 in [-1, 1].

    Returns (samples, sample_rate). With ``mono=True`` the result is 1-D.
    With ``mono=False`` the result has shape (frames, channels).
    """
    if ffmpeg_available():
        src = probe(path)
        sr = target_sr or src.sample_rate_hz
        channels = 1 if mono else max(src.channels, 1)
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path)]
        if max_seconds is not None:
            cmd += ["-t", f"{max_seconds:.3f}"]
        cmd += [
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(sr),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-y",
        ]
        # Decode to a temporary file and read it straight into the array: piping
        # through stdout would hold the bytes and a copy of them at once (twice
        # the audio in memory, 230 MB for 10 minutes at 48 kHz).
        fd, tmp_name = tempfile.mkstemp(prefix="thicket-decode-", suffix=".f32")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            try:
                subprocess.run(cmd + [str(tmp)], capture_output=True, check=True, timeout=300)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise AudioDecodeError("FFmpeg could not decode this file.") from exc
            x = np.fromfile(tmp, dtype=np.float32)
        finally:
            tmp.unlink(missing_ok=True)
        if not mono:
            x = x.reshape(-1, channels)
        if x.size == 0:
            raise AudioDecodeError("The file decoded to zero audio samples.")
        return x, sr

    try:
        data, sr_in = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:  # noqa: BLE001
        raise AudioDecodeError(
            "This file could not be decoded (install FFmpeg for MP3/M4A)."
        ) from exc
    if max_seconds is not None:
        data = data[: int(math.ceil(max_seconds * sr_in))]
    if data.size == 0:
        raise AudioDecodeError("The file decoded to zero audio samples.")
    sr = target_sr or sr_in
    if mono:
        x = data.mean(axis=1)
        return _resample(x, sr_in, sr), sr
    chans = [_resample(data[:, c], sr_in, sr) for c in range(data.shape[1])]
    return np.stack(chans, axis=1), sr


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write 16-bit PCM WAV (the normalized, model-ready artifact)."""
    sf.write(str(path), np.clip(samples, -1.0, 1.0), sample_rate, subtype="PCM_16")

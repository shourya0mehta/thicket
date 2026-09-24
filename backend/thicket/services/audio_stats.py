"""Streaming native-rate level statistics (peak, RMS, clipping, DC).

Decodes the original file at its own sample rate and channel count in
blocks, so a 10 minute 96 kHz stereo file never sits in memory as a whole.
FFmpeg is the decoder; libsndfile is the fallback when FFmpeg is missing.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from thicket.domain.quality import LevelAccumulator, LevelStats
from thicket.services.audio_io import AudioDecodeError, ffmpeg_available

BLOCK_BYTES = 1 << 20
TIMEOUT_SECONDS = 300


def native_level_stats(path: Path, channels: int) -> LevelStats:
    acc = LevelAccumulator()
    if ffmpeg_available():
        _ffmpeg_blocks(path, max(1, channels), acc)
    else:
        try:
            for block in sf.blocks(str(path), blocksize=65536, dtype="float32", always_2d=True):
                acc.update(block)
        except Exception as exc:  # noqa: BLE001 - libsndfile raises several types
            raise AudioDecodeError("This file could not be decoded.") from exc
    if acc.total == 0:
        raise AudioDecodeError("The file decoded to zero audio samples.")
    return acc.result()


def _ffmpeg_blocks(path: Path, channels: int, acc: LevelAccumulator) -> None:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-vn",
        "-ac",
        str(channels),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-",
    ]
    frame_bytes = 4 * channels
    block = BLOCK_BYTES - (BLOCK_BYTES % frame_bytes)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    carry = b""
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(block)
            if not chunk:
                break
            data = carry + chunk
            usable = len(data) - (len(data) % frame_bytes)
            carry = data[usable:]
            if usable:
                acc.update(np.frombuffer(data[:usable], dtype=np.float32).reshape(-1, channels))
            if time.monotonic() > deadline:
                raise AudioDecodeError("Decoding took too long.")
        if proc.wait(timeout=30) != 0:
            raise AudioDecodeError("FFmpeg could not decode this file.")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

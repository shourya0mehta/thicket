"""Helpers shared by tests (importable as ``tests.helpers``)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from thicket.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
SOUNDSCAPE = FIXTURES / "soundscape_30s.flac"
SR = 48_000


def tone(freq: float, seconds: float, amp: float = 0.5, sr: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def white_noise(seconds: float, std: float = 0.1, sr: int = SR, seed: int = 0) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(seconds * sr)) * std).astype(np.float32)


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict = {
        "_env_file": None,
        "thicket_data_dir": tmp_path / "data",
        "rate_limit_per_minute": 0,
        "log_level": "WARNING",
        "environment": "test",
    }
    values.update(overrides)
    return Settings(**values)


def post_analysis(
    client: TestClient,
    path: Path | None,
    *,
    wait: bool = True,
    data: dict | None = None,
    filename: str | None = None,
):  # type: ignore[no-untyped-def]
    """POST /analyses as multipart. ``path=None`` sends text fields only."""
    url = "/api/v1/analyses" + ("?wait=true" if wait else "")
    if path is None:
        return client.post(url, files={k: (None, str(v)) for k, v in (data or {}).items()})
    with open(path, "rb") as fh:
        return client.post(url, data=data or {}, files={"file": (filename or path.name, fh)})

"""Adapter contract shared by every acoustic model.

An adapter turns normalized audio into canonical window detections. It must
declare its input requirements, load once, and fail with typed errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

import numpy as np

from thicket.domain.consolidation import WindowDetection


class AdapterError(Exception):
    code = "internal_error"


class ModelUnavailable(AdapterError):
    code = "model_unavailable"


class UnsupportedAudio(AdapterError):
    code = "unsupported_audio"


@dataclass(frozen=True)
class AnalysisContext:
    analysis_id: str
    model_run_id: str
    latitude: float | None = None
    longitude: float | None = None
    recording_date: date | None = None
    raw_threshold: float = 0.1
    hop_seconds: float = 3.0
    location_filter: bool = True
    location_filter_threshold: float = 0.03


@dataclass
class AdapterOutput:
    detections: list[WindowDetection]
    n_windows: int
    runtime_ms: int
    configuration: dict = field(default_factory=dict)
    # Optional per-window extras other components may use (e.g. QC).
    window_starts: np.ndarray | None = None
    embeddings: np.ndarray | None = None
    extras: dict = field(default_factory=dict)


@runtime_checkable
class AcousticModelAdapter(Protocol):
    key: str
    name: str
    version: str
    taxon_scope: list[str]
    required_sample_rate_hz: int
    window_seconds: float
    experimental: bool
    license: str
    description: str

    def is_ready(self) -> bool: ...

    def status(self) -> str: ...

    def unavailable_reason(self) -> str | None: ...

    def load(self) -> None: ...

    def model_sha256(self) -> str | None: ...

    def analyze(
        self, samples: np.ndarray, sample_rate: int, context: AnalysisContext
    ) -> AdapterOutput: ...

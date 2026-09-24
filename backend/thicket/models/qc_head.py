"""Soundscape QC head: flags likely contamination and non-target sound sources.

A small linear head on BirdNET v2.4 window embeddings (1024-d), trained on
ESC-50 (see ``docs/model-cards/qc-soundscape-v1.md``). Pure NumPy at inference;
the artifact is a pickle-free ``.npz`` loaded with ``allow_pickle=False``.

Usage::

    from thicket.models.qc_head import load_default

    head = load_default()
    _, emb = runtime.infer(windows)          # (n_windows, 1024)
    probs = head.predict(emb)                # {"rain": 0.03, "wind": 0.91, ...}
    warnings = head.flags(probs)             # ["wind"]
    contamination = head.contamination_flags(probs)  # excludes bird/insect/frog

Pooling: a segment feature is concat(mean, max) of its window embeddings.
The head was trained on 5 s clips (3 windows). A recording is split into
consecutive segments of ``segment_windows`` windows (2 windows = 6 s at the
default 3 s hop) and each segment is scored. The default recording score
(``recording_pooling="segment_quantile"``, ``segment_quantile=0.25``) is, per
category, the k-th highest segment probability with
k = max(1, ceil(0.25 * n_segments)): a category is flagged only when it is
present in at least about a quarter of the recording. This keeps the false
warning rate from growing with recording length (a plain max over segments
flagged most clean 60 s test recordings) at the cost of not flagging short
bursts; use ``predict_segments`` to localize those. Recordings of one or two
segments are scored like a single clip. See ml/reports/qc_esc50_v1.md.

Probabilities are Platt-calibrated on ESC-50 cross-validation predictions.
They are calibrated for ESC-50-like 5 s clips, not for field recordings. Treat
them as QC scores, not as validated event probabilities.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

import numpy as np

ARTIFACT_NAME = "qc_head_v1.npz"
FORMAT = "thicket-qc-head/1"
CONTAMINATION_KINDS = ("geophony", "anthropophony", "biophony_non_target")
POOLING_MODES = ("whole", "segment_max", "segment_quantile")


class QCHeadUnavailable(RuntimeError):
    """The QC head artifact is missing or malformed."""


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


@dataclass(frozen=True, eq=False)
class QCHead:
    version: str
    categories: tuple[str, ...]
    category_kind: dict[str, str]
    feature_mean: np.ndarray
    feature_std: np.ndarray
    W: np.ndarray
    b: np.ndarray
    platt_a: np.ndarray
    platt_b: np.ndarray
    thresholds: np.ndarray
    thresholds_high_precision: np.ndarray
    recording_pooling: str
    segment_windows: int
    segment_quantile: float
    embedding_dim: int
    birdnet_sha256: str
    license: str
    card: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: str | Path) -> QCHead:
        path = Path(path)
        if not path.exists():
            raise QCHeadUnavailable(f"QC head artifact not found: {path}")
        with np.load(path, allow_pickle=False) as z:
            fmt = str(z["format"])
            if fmt != FORMAT:
                raise QCHeadUnavailable(f"Unsupported QC head format {fmt!r}")
            cats = tuple(str(c) for c in z["categories"])
            kinds = [str(k) for k in z["category_kind"]]
            head = cls(
                version=str(z["version"]),
                categories=cats,
                category_kind=dict(zip(cats, kinds, strict=True)),
                feature_mean=z["feature_mean"].astype(np.float64),
                feature_std=z["feature_std"].astype(np.float64),
                W=z["W"].astype(np.float64),
                b=z["b"].astype(np.float64),
                platt_a=z["platt_a"].astype(np.float64),
                platt_b=z["platt_b"].astype(np.float64),
                thresholds=z["thresholds"].astype(np.float64),
                thresholds_high_precision=z["thresholds_high_precision"].astype(np.float64),
                recording_pooling=str(z["recording_pooling"]),
                segment_windows=int(z["segment_windows"]),
                segment_quantile=float(z["segment_quantile"])
                if "segment_quantile" in z.files
                else 0.0,
                embedding_dim=int(z["embedding_dim"]),
                birdnet_sha256=str(z["birdnet_sha256"]),
                license=str(z["license"]),
                card=_read_card(path.with_suffix(".json")),
            )
        k, d = len(cats), head.embedding_dim
        shapes = {
            "feature_mean": (2 * d,),
            "feature_std": (2 * d,),
            "W": (2 * d, k),
            "b": (k,),
            "platt_a": (k,),
            "platt_b": (k,),
            "thresholds": (k,),
            "thresholds_high_precision": (k,),
        }
        for name, shape in shapes.items():
            if getattr(head, name).shape != shape:
                raise QCHeadUnavailable(
                    f"QC head array {name} has shape {getattr(head, name).shape}"
                )
        if (
            head.recording_pooling not in POOLING_MODES
            or head.segment_windows < 1
            or not 0.0 <= head.segment_quantile < 1.0
        ):
            raise QCHeadUnavailable("QC head pooling settings are invalid")
        return head

    # ------------------------------------------------------------------ inference

    def _check(self, window_embeddings: np.ndarray) -> np.ndarray:
        e = np.asarray(window_embeddings, dtype=np.float64)
        if e.ndim == 1:
            e = e[None, :]
        if e.ndim != 2 or e.shape[1] != self.embedding_dim or e.shape[0] == 0:
            raise ValueError(
                f"expected window embeddings of shape (n_windows>=1, {self.embedding_dim}), "
                f"got {np.shape(window_embeddings)}"
            )
        if not np.all(np.isfinite(e)):
            raise ValueError("window embeddings contain NaN or inf")
        return e

    @staticmethod
    def pool(window_embeddings: np.ndarray) -> np.ndarray:
        """Clip feature: concat(mean, max) over windows."""
        e = np.asarray(window_embeddings, dtype=np.float64)
        return np.concatenate([e.mean(axis=0), e.max(axis=0)])

    def _proba(self, feats: np.ndarray) -> np.ndarray:
        z = ((feats - self.feature_mean) / self.feature_std) @ self.W + self.b
        return _sigmoid(self.platt_a * z + self.platt_b)

    def segments(self, n_windows: int) -> list[tuple[int, int]]:
        """Window index ranges [start, end) of consecutive segments."""
        s = self.segment_windows
        return [(i, min(i + s, n_windows)) for i in range(0, n_windows, s)]

    def predict_segments(self, window_embeddings: np.ndarray) -> np.ndarray:
        """Calibrated probabilities per segment, shape (n_segments, n_categories)."""
        e = self._check(window_embeddings)
        feats = np.stack([self.pool(e[a:b]) for a, b in self.segments(len(e))])
        return self._proba(feats)

    def predict_array(self, window_embeddings: np.ndarray, mode: str | None = None) -> np.ndarray:
        """Recording-level probabilities as an array ordered like ``categories``.

        ``mode``: ``"segment_quantile"`` (default from the artifact),
        ``"segment_max"`` or ``"whole"`` (pool every window into one feature).
        """
        e = self._check(window_embeddings)
        mode = mode or self.recording_pooling
        if mode not in POOLING_MODES:
            raise ValueError(f"unknown pooling mode {mode!r}")
        if mode == "whole" or len(e) <= self.segment_windows:
            return self._proba(self.pool(e)[None, :])[0]
        segs = self.predict_segments(e)
        if mode == "segment_max":
            return segs.max(axis=0)
        k = max(1, int(np.ceil(self.segment_quantile * len(segs))))
        return -np.sort(-segs, axis=0)[k - 1]

    def predict(self, window_embeddings: np.ndarray, mode: str | None = None) -> dict[str, float]:
        """Recording-level probability per QC category (deterministic)."""
        p = self.predict_array(window_embeddings, mode)
        return {c: float(v) for c, v in zip(self.categories, p, strict=True)}

    def flags(
        self,
        x: np.ndarray | Mapping[str, float],
        high_precision: bool = False,
    ) -> list[str]:
        """Categories whose probability is at or above their threshold.

        ``x`` is either window embeddings or the dict returned by ``predict``.
        ``high_precision=True`` uses the stricter thresholds chosen for
        precision >= 0.9 on ESC-50 cross-validation.
        """
        probs = x if isinstance(x, Mapping) else self.predict(np.asarray(x))
        thr = self.thresholds_high_precision if high_precision else self.thresholds
        return [c for c, t in zip(self.categories, thr, strict=True) if probs[c] >= t]

    def contamination_flags(
        self, x: np.ndarray | Mapping[str, float], high_precision: bool = False
    ) -> list[str]:
        """Like ``flags`` but only non-target sources (weather, water, human,
        machinery, domestic animals); bird, insect and frog are excluded."""
        return [
            c
            for c in self.flags(x, high_precision)
            if self.category_kind.get(c) in CONTAMINATION_KINDS
        ]

    def threshold(self, category: str, high_precision: bool = False) -> float:
        i = self.categories.index(category)
        thr = self.thresholds_high_precision if high_precision else self.thresholds
        return float(thr[i])

    def matches_backbone(self, birdnet_sha256: str) -> bool:
        """True when embeddings come from the BirdNET weights the head was trained on."""
        return birdnet_sha256 == self.birdnet_sha256

    def provenance(self) -> dict:
        return {
            "model": "thicket-qc-head",
            "version": self.version,
            "backbone_sha256": self.birdnet_sha256,
            "recording_pooling": self.recording_pooling,
            "segment_windows": self.segment_windows,
            "segment_quantile": self.segment_quantile,
            "thresholds": {
                c: float(t) for c, t in zip(self.categories, self.thresholds, strict=True)
            },
            "license": self.license,
        }


def _read_card(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def default_path() -> Path:
    return Path(str(resources.files("thicket.models.data").joinpath(ARTIFACT_NAME)))


@lru_cache(maxsize=1)
def load_default() -> QCHead:
    """Load the packaged QC head once per process."""
    return QCHead.load(default_path())

"""BirdNET v2.4 adapter.

Wraps :class:`~thicket.models.birdnet_runtime.BirdNETRuntime` behind the
:class:`~thicket.models.base.AcousticModelAdapter` contract:

* input: mono 48 kHz float32; 3 s windows at ``context.hop_seconds`` (3.0 by
  default, 1.5 for 50% overlap); a trailing partial window of at least 1 s is
  zero padded, and its end time is clipped to the recording's end;
* output: one :class:`WindowDetection` per (window, label) whose sigmoid score,
  rounded to 4 decimals, is at least ``context.raw_threshold`` (the ingestion
  floor). Ids are ``det_<n>`` in window then label order, so output is
  deterministic;
* plausibility: with coordinates (and ``location_filter``), BirdNET's
  range/season meta model scores every label for the location and week (week
  -1 when the date is unknown). Bird labels below
  ``location_filter_threshold`` are ``unlikely``, others ``plausible``.
  Non-bird labels stay ``unknown``: the meta model gives roughly 0 to every
  frog and insect (Spring Peeper scores 2e-5 in Ithaca in May), so it must
  never filter them;
* extras: per-window "Human vocal" probability (speech QC) and the 1024-d
  window embeddings (QC head, frog/insect head).

BirdNET v2.4 covers 6522 labels: birds plus 41 frogs and toads, 42 insects,
7 mammals and a few human/noise classes (see ``data/birdnet_v24_taxa.json``).
Weights are licensed CC BY-NC-SA 4.0 (non-commercial).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np

from thicket.domain.consolidation import WindowDetection
from thicket.models.base import (
    AdapterError,
    AdapterOutput,
    AnalysisContext,
    ModelUnavailable,
    UnsupportedAudio,
)
from thicket.models.birdnet_runtime import (
    MODEL_FILE,
    MODEL_LICENSE,
    SAMPLE_RATE,
    WINDOW_SECONDS,
    BirdNETRuntime,
    BirdNETUnavailable,
    Label,
    frame_windows,
    week_48,
)
from thicket.models.lifecycle import AdapterLifecycle

HUMAN_VOCAL = "Human vocal"
MIN_TAIL_SECONDS = 1.0
CONFIDENCE_DECIMALS = 4


class SharedBirdNET:
    """One BirdNET runtime per process and model directory.

    The BirdNET and frog/insect adapters share it, and so do several app
    instances in one process (tests), so the interpreter loads once.
    """

    _cache: dict[str, BirdNETRuntime] = {}
    _cache_lock = threading.Lock()

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir

    def _key(self) -> str:
        return str(self.model_dir or os.environ.get("BIRDNET_MODEL_DIR") or "<bundled>")

    def get(self) -> BirdNETRuntime:
        key = self._key()
        with self._cache_lock:
            rt = self._cache.get(key)
            if rt is None:
                rt = BirdNETRuntime(self.model_dir)
                self._cache[key] = rt
            return rt

    def load(self) -> BirdNETRuntime:
        rt = self.get()
        rt.load()
        return rt


def human_vocal_scores(runtime: BirdNETRuntime, probs: np.ndarray) -> np.ndarray:
    idx = runtime.index_by_scientific.get(HUMAN_VOCAL)
    if idx is None or probs.size == 0:
        return np.zeros(probs.shape[0])
    return probs[:, idx].astype(np.float64)


def infer_windows(
    runtime: BirdNETRuntime, samples: np.ndarray, hop_seconds: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Frame and run BirdNET. Returns (window_starts, probabilities, embeddings)."""
    windows, starts = frame_windows(
        np.asarray(samples, dtype=np.float32),
        hop_seconds=hop_seconds,
        min_tail_seconds=MIN_TAIL_SECONDS,
    )
    logits, embeddings = runtime.infer(windows)
    probs = BirdNETRuntime.sigmoid(logits.astype(np.float64))
    return starts, probs, embeddings


def check_input(samples: np.ndarray, sample_rate: int) -> None:
    if sample_rate != SAMPLE_RATE:
        raise UnsupportedAudio(f"BirdNET needs 48 kHz audio; got {sample_rate} Hz.")
    if samples.ndim != 1 or samples.size == 0:
        raise UnsupportedAudio("BirdNET needs non-empty mono audio.")


class BirdNETAdapter(AdapterLifecycle):
    key = "birdnet"
    name = "BirdNET"
    version = "2.4"
    model_name = "BirdNET GLOBAL 6K V2.4"
    taxon_scope = ["bird", "amphibian", "insect", "mammal"]
    required_sample_rate_hz = SAMPLE_RATE
    window_seconds = WINDOW_SECONDS
    experimental = False
    license = MODEL_LICENSE
    model_card_url = "https://github.com/birdnet-team/BirdNET-Analyzer"
    description = (
        "BirdNET v2.4 (Cornell Lab of Ornithology and Chemnitz University of Technology). "
        "Recognizes over 6,000 bird species plus some frogs, toads, insects and mammals "
        "in 3 s windows. Licensed CC BY-NC-SA 4.0 for non-commercial use."
    )

    def __init__(self, shared: SharedBirdNET, enabled: bool = True) -> None:
        super().__init__()
        self.shared = shared
        self.enabled = enabled

    # -- lifecycle ----------------------------------------------------------
    def _disabled_reason(self) -> str | None:
        if not self.enabled:
            return "BirdNET is turned off on this server (BIRDNET_ENABLED=false)."
        return None

    def _load(self) -> None:
        self.shared.load()

    def _describe_failure(self, exc: Exception) -> str:
        if isinstance(exc, BirdNETUnavailable):
            return str(exc)
        return "BirdNET could not be loaded on this server."

    @property
    def runtime(self) -> BirdNETRuntime:
        if not self.is_ready():
            raise ModelUnavailable(self.unavailable_reason() or "BirdNET is not loaded yet.")
        return self.shared.get()

    def model_sha256(self) -> str | None:
        return self.shared.get().model_sha256 if self.is_ready() else None

    # -- plausibility -------------------------------------------------------
    def plausibility(self, labels: list[Label], context: AnalysisContext) -> tuple[list[str], dict]:
        """Per-label plausibility plus the configuration that produced it."""
        unknown = ["unknown"] * len(labels)
        if not context.location_filter:
            return unknown, {"location_filter_applied": False, "reason": "disabled"}
        if context.latitude is None or context.longitude is None:
            return unknown, {"location_filter_applied": False, "reason": "no_coordinates"}
        week = week_48(context.recording_date) if context.recording_date else -1
        occurrence = self.runtime.species_filter(context.latitude, context.longitude, week)
        thr = context.location_filter_threshold
        out = [
            ("plausible" if float(occurrence[i]) >= thr else "unlikely")
            if lab.taxon == "bird"
            else "unknown"
            for i, lab in enumerate(labels)
        ]
        return out, {
            "location_filter_applied": True,
            "week": week,
            "location_filter_threshold": thr,
            "meta_model": "BirdNET_GLOBAL_6K_V2.4_MData_Model_V2_FP16",
            "applies_to": "bird labels only",
        }

    # -- inference ----------------------------------------------------------
    def analyze(
        self, samples: np.ndarray, sample_rate: int, context: AnalysisContext
    ) -> AdapterOutput:
        check_input(samples, sample_rate)
        t0 = time.perf_counter()
        try:
            runtime = self.runtime
            starts, probs, embeddings = infer_windows(runtime, samples, context.hop_seconds)
            plaus, plaus_cfg = self.plausibility(runtime.labels, context)
        except BirdNETUnavailable as exc:
            raise ModelUnavailable(str(exc)) from exc
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed error
            raise AdapterError("BirdNET inference failed.") from exc

        duration = samples.size / float(sample_rate)
        detections = build_detections(
            probs=probs,
            window_starts=starts,
            window_seconds=WINDOW_SECONDS,
            duration_seconds=duration,
            labels=runtime.labels,
            plausibility=plaus,
            context=context,
            floors=None,
        )
        hv = human_vocal_scores(runtime, probs)
        return AdapterOutput(
            detections=detections,
            n_windows=int(starts.size),
            runtime_ms=int(round((time.perf_counter() - t0) * 1000)),
            configuration={
                "model_file": MODEL_FILE,
                "model_name": self.model_name,
                "license": self.license,
                "sensitivity": 1.0,
                "min_tail_seconds": MIN_TAIL_SECONDS,
                "confidence_decimals": CONFIDENCE_DECIMALS,
                **plaus_cfg,
            },
            window_starts=starts,
            embeddings=embeddings,
            extras={
                "human_vocal_max": float(hv.max()) if hv.size else 0.0,
                "human_vocal_by_window": [round(float(v), 4) for v in hv],
            },
        )


def build_detections(
    *,
    probs: np.ndarray,
    window_starts: np.ndarray,
    window_seconds: float,
    duration_seconds: float,
    labels: list[Label],
    plausibility: list[str],
    context: AnalysisContext,
    floors: np.ndarray | None,
) -> list[WindowDetection]:
    """Turn a (windows x labels) probability matrix into canonical detections.

    A detection is kept when its score rounded to 4 decimals is at least the
    ingestion floor (``context.raw_threshold``, or a per-label ``floors``
    value when larger). Order is window, then label index; ids ``det_<n>``.
    """
    rounded = np.round(np.asarray(probs, dtype=np.float64), CONFIDENCE_DECIMALS)
    floor = np.full(rounded.shape[1], context.raw_threshold, dtype=np.float64)
    if floors is not None:
        floor = np.maximum(floor, floors)
    hits = np.argwhere(rounded + 1e-9 >= floor[None, :])
    out: list[WindowDetection] = []
    for n, (w, j) in enumerate(hits):
        lab = labels[int(j)]
        start = float(window_starts[int(w)])
        end = min(start + window_seconds, duration_seconds)
        out.append(
            WindowDetection(
                id=f"det_{n}",
                model_run_id=context.model_run_id,
                label_raw=lab.raw,
                scientific_name=lab.scientific_name,
                common_name=lab.common_name,
                taxon=lab.taxon,
                start_seconds=round(start, 3),
                end_seconds=round(max(end, start), 3),
                confidence=float(min(1.0, max(0.0, rounded[int(w), int(j)]))),
                plausibility=plausibility[int(j)],
            )
        )
    return out

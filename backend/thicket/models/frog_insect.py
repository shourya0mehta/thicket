"""Experimental frog and insect adapter: a small NumPy head on BirdNET embeddings.

Status: experimental and off by default. It is enabled only when
``FROG_INSECT_ENABLED=true`` and ``FROG_INSECT_MODEL_PATH`` points at a head
file. A head must ship with a model card and a benchmark before it is enabled
for users (see docs/model-cards/frog-insect.md). The historical
OpenSoundscape frog/insect model failed validation and is not used.

Head file (``.npz``, loaded with ``allow_pickle=False``)
------------------------------------------------------
=================  ============  ================================================
array              shape         meaning
=================  ============  ================================================
``W1``, ``b1``     (1024, H), H  first layer (or the only, linear, layer)
``W2``, ``b2``     (H, C), C     optional second layer; ReLU between layers
``labels``         (C,) str      scientific names
``common_names``   (C,) str      common names
``taxa``           (C,) str      ``amphibian`` or ``insect`` (any biodiversity taxon)
``thresholds``     (C,) float    per-class validated minimum score
``temperature``    scalar > 0    logit temperature (calibration)
``embedding_mean`` (1024,)       standardization applied before the head
``embedding_std``  (1024,)
=================  ============  ================================================

Scores are ``sigmoid(logits / temperature)`` per class (multi-label). The
per-class ``thresholds`` act as ingestion floors: a window is stored only
when its score is at least ``max(raw_threshold, thresholds[c])``, so the
decision threshold can never surface scores below a class's validated floor.

A JSON model card sits next to the head (same stem, ``.json``) and may set
``name``, ``version``, ``license``, ``description`` and ``benchmark``.

Embeddings come from the shared BirdNET runtime. When BirdNET runs in the
same analysis, the analysis service passes its embeddings to
:meth:`FrogInsectAdapter.analyze_embeddings`, so BirdNET runs once.
Detections are ``plausibility="unknown"``: BirdNET's range model cannot score
frogs or insects.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from thicket.api.schemas import BIODIVERSITY_TAXA
from thicket.models.base import AdapterError, AdapterOutput, AnalysisContext, ModelUnavailable
from thicket.models.birdnet import (
    SharedBirdNET,
    build_detections,
    check_input,
    human_vocal_scores,
    infer_windows,
)
from thicket.models.birdnet_runtime import (
    SAMPLE_RATE,
    WINDOW_SECONDS,
    BirdNETUnavailable,
    Label,
    sha256_file,
)
from thicket.models.lifecycle import AdapterLifecycle

EMBEDDING_DIM = 1024


class HeadFormatError(ValueError):
    """The head file is missing arrays or has inconsistent shapes."""


@dataclass(frozen=True)
class FrogInsectHead:
    W1: np.ndarray
    b1: np.ndarray
    W2: np.ndarray | None
    b2: np.ndarray | None
    labels: list[Label]
    thresholds: np.ndarray
    temperature: float
    embedding_mean: np.ndarray
    embedding_std: np.ndarray

    @property
    def n_classes(self) -> int:
        return len(self.labels)

    @classmethod
    def from_npz(cls, path: Path) -> FrogInsectHead:
        with np.load(path, allow_pickle=False) as z:
            arrays = {k: z[k] for k in z.files}
        required = [
            "W1",
            "b1",
            "labels",
            "common_names",
            "taxa",
            "thresholds",
            "temperature",
            "embedding_mean",
            "embedding_std",
        ]
        missing = [k for k in required if k not in arrays]
        if missing:
            raise HeadFormatError(f"head file is missing arrays: {', '.join(missing)}")
        W1 = arrays["W1"].astype(np.float32)
        b1 = arrays["b1"].astype(np.float32).reshape(-1)
        if W1.ndim != 2 or W1.shape[0] != EMBEDDING_DIM or b1.shape[0] != W1.shape[1]:
            raise HeadFormatError("W1 must be (1024, H) and b1 must be (H,)")
        W2 = b2 = None
        if "W2" in arrays or "b2" in arrays:
            if "W2" not in arrays or "b2" not in arrays:
                raise HeadFormatError("W2 and b2 must be provided together")
            W2 = arrays["W2"].astype(np.float32)
            b2 = arrays["b2"].astype(np.float32).reshape(-1)
            if W2.ndim != 2 or W2.shape[0] != W1.shape[1] or b2.shape[0] != W2.shape[1]:
                raise HeadFormatError("W2 must be (H, C) and b2 must be (C,)")
        n_classes = (W2 if W2 is not None else W1).shape[1]
        names = [str(s) for s in arrays["labels"].reshape(-1)]
        commons = [str(s) for s in arrays["common_names"].reshape(-1)]
        taxa = [str(s) for s in arrays["taxa"].reshape(-1)]
        if not (len(names) == len(commons) == len(taxa) == n_classes):
            raise HeadFormatError("labels, common_names and taxa must have one entry per class")
        bad = sorted({t for t in taxa if t not in BIODIVERSITY_TAXA})
        if bad:
            raise HeadFormatError(f"unsupported taxa in head: {', '.join(bad)}")
        thresholds = arrays["thresholds"].astype(np.float64).reshape(-1)
        if thresholds.shape[0] != n_classes or np.any((thresholds < 0) | (thresholds > 1)):
            raise HeadFormatError("thresholds must be (C,) values in [0, 1]")
        temperature = float(np.asarray(arrays["temperature"]).reshape(-1)[0])
        if not np.isfinite(temperature) or temperature <= 0:
            raise HeadFormatError("temperature must be a positive number")
        mean = arrays["embedding_mean"].astype(np.float32).reshape(-1)
        std = arrays["embedding_std"].astype(np.float32).reshape(-1)
        if mean.shape[0] != EMBEDDING_DIM or std.shape[0] != EMBEDDING_DIM:
            raise HeadFormatError("embedding_mean and embedding_std must be (1024,)")
        labels = [
            Label(raw=f"{sci}_{com}", scientific_name=sci, common_name=com or sci, taxon=tax)
            for sci, com, tax in zip(names, commons, taxa, strict=True)
        ]
        return cls(
            W1=W1,
            b1=b1,
            W2=W2,
            b2=b2,
            labels=labels,
            thresholds=thresholds,
            temperature=temperature,
            embedding_mean=mean,
            embedding_std=np.maximum(std, 1e-6),
        )

    def predict_proba(self, embeddings: np.ndarray) -> np.ndarray:
        """(N, 1024) embeddings -> (N, C) calibrated per-class scores."""
        x = (np.asarray(embeddings, dtype=np.float32) - self.embedding_mean) / self.embedding_std
        h = x @ self.W1 + self.b1
        if self.W2 is not None and self.b2 is not None:
            h = np.maximum(h, 0.0) @ self.W2 + self.b2
        z = np.clip(h.astype(np.float64) / self.temperature, -40.0, 40.0)
        return 1.0 / (1.0 + np.exp(-z))


class FrogInsectAdapter(AdapterLifecycle):
    key = "frog_insect"
    name = "Frogs and insects"
    taxon_scope = ["amphibian", "insect"]
    required_sample_rate_hz = SAMPLE_RATE
    window_seconds = WINDOW_SECONDS
    experimental = True
    model_card_url = "docs/model-cards/frog-insect.md"
    embedding_source = "birdnet"

    def __init__(
        self,
        shared: SharedBirdNET,
        model_path: Path | None,
        enabled: bool = False,
        card_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.shared = shared
        self.model_path = Path(model_path) if model_path else None
        self.enabled = enabled
        self.card_path = card_path or (
            self.model_path.with_suffix(".json") if self.model_path else None
        )
        self.head: FrogInsectHead | None = None
        self.card: dict = {}
        self._sha: str | None = None

    # Metadata comes from the model card when present.
    @property
    def version(self) -> str:
        return str(self.card.get("version", "unvalidated"))

    @property
    def license(self) -> str:
        return str(self.card.get("license", "Not released"))

    @property
    def description(self) -> str:
        return str(
            self.card.get(
                "description",
                "Experimental frog and insect classifier on BirdNET embeddings. Not validated; "
                "detections are unverified and need review.",
            )
        )

    # -- lifecycle ----------------------------------------------------------
    def _disabled_reason(self) -> str | None:
        if not self.enabled:
            return (
                "Experimental. Disabled until a validated frog and insect model with a "
                "benchmark and model card is installed (FROG_INSECT_ENABLED=true and "
                "FROG_INSECT_MODEL_PATH)."
            )
        if self.model_path is None or not self.model_path.is_file():
            name = self.model_path.name if self.model_path else "(not set)"
            return (
                f"Experimental. The model file {name} was not found; a validated frog and "
                "insect model is required."
            )
        return None

    def _load(self) -> None:
        assert self.model_path is not None
        self.head = FrogInsectHead.from_npz(self.model_path)
        if self.card_path and self.card_path.is_file():
            self.card = json.loads(self.card_path.read_text(encoding="utf-8"))
        self._sha = sha256_file(self.model_path)
        self.shared.load()

    def _describe_failure(self, exc: Exception) -> str:
        if isinstance(exc, HeadFormatError):
            return f"The frog and insect head file is invalid: {exc}."
        if isinstance(exc, BirdNETUnavailable):
            return f"BirdNET embeddings are unavailable: {exc}"
        return "The frog and insect model could not be loaded."

    def model_sha256(self) -> str | None:
        return self._sha

    def _require_head(self) -> FrogInsectHead:
        if not self.is_ready() or self.head is None:
            raise ModelUnavailable(
                self.unavailable_reason() or "The frog and insect model is not loaded."
            )
        return self.head

    # -- inference ----------------------------------------------------------
    def analyze(
        self, samples: np.ndarray, sample_rate: int, context: AnalysisContext
    ) -> AdapterOutput:
        """Standalone path: compute BirdNET embeddings, then apply the head."""
        check_input(samples, sample_rate)
        self._require_head()
        t0 = time.perf_counter()
        try:
            runtime = self.shared.get()
            starts, probs, embeddings = infer_windows(runtime, samples, context.hop_seconds)
        except BirdNETUnavailable as exc:
            raise ModelUnavailable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError("Embedding extraction failed.") from exc
        out = self.analyze_embeddings(
            embeddings, starts, samples.size / float(sample_rate), context
        )
        hv = human_vocal_scores(runtime, probs)
        out.extras.update(
            {
                "human_vocal_max": float(hv.max()) if hv.size else 0.0,
                "human_vocal_by_window": [round(float(v), 4) for v in hv],
            }
        )
        out.runtime_ms = int(round((time.perf_counter() - t0) * 1000))
        out.configuration["embeddings"] = "computed"
        return out

    def analyze_embeddings(
        self,
        embeddings: np.ndarray,
        window_starts: np.ndarray,
        duration_seconds: float,
        context: AnalysisContext,
    ) -> AdapterOutput:
        """Apply the head to BirdNET window embeddings computed elsewhere."""
        head = self._require_head()
        t0 = time.perf_counter()
        emb = np.asarray(embeddings, dtype=np.float32)
        if emb.ndim != 2 or emb.shape[1] != EMBEDDING_DIM or emb.shape[0] != len(window_starts):
            raise AdapterError("Embeddings do not match the analysis windows.")
        probs = head.predict_proba(emb) if emb.shape[0] else np.zeros((0, head.n_classes))
        detections = build_detections(
            probs=probs,
            window_starts=np.asarray(window_starts, dtype=np.float64),
            window_seconds=WINDOW_SECONDS,
            duration_seconds=duration_seconds,
            labels=head.labels,
            plausibility=["unknown"] * head.n_classes,
            context=context,
            floors=head.thresholds,
        )
        return AdapterOutput(
            detections=detections,
            n_windows=int(emb.shape[0]),
            runtime_ms=int(round((time.perf_counter() - t0) * 1000)),
            configuration={
                "embedding_model": "BirdNET GLOBAL 6K V2.4",
                "embeddings": "shared",
                "n_classes": head.n_classes,
                "temperature": head.temperature,
                "per_class_floor": "max(raw_threshold, class threshold)",
                "model_card": {k: self.card[k] for k in ("name", "version") if k in self.card},
                "head_digest": hashlib.sha256(head.W1.tobytes()).hexdigest()[:16],
            },
            window_starts=np.asarray(window_starts, dtype=np.float64),
            embeddings=emb,
            extras={},
        )

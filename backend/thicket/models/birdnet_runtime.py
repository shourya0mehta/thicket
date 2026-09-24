"""Low-level BirdNET v2.4 runtime shared by the API adapter and the ML pipeline.

Design notes
------------
* Weights: BirdNET GLOBAL 6K V2.4 TFLite (FP32), license CC BY-NC-SA 4.0.
  We resolve them from ``BIRDNET_MODEL_DIR`` or from the pinned ``birdnetlib``
  wheel, which ships the exact files and is installable from PyPI.
* Embeddings: the stock model exposes only the 6522 logits. With the XNNPACK
  delegate intermediate tensors are not readable, so on first load we rewrite
  the flatbuffer so the subgraph also outputs ``GLOBAL_AVG_POOL/Mean`` (1024-d).
  The rewritten file is cached by source hash. Weights are untouched.
* One interpreter per runtime, guarded by a lock. Batch size 1 is fastest on
  CPU for this graph (measured ~27 windows/s on 2 vCPU).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from importlib import resources
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48_000
WINDOW_SECONDS = 3.0
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SECONDS)
MODEL_NAME = "BirdNET GLOBAL 6K"
MODEL_VERSION = "2.4"
MODEL_FILE = "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite"
META_FILE = "BirdNET_GLOBAL_6K_V2.4_MData_Model_V2_FP16.tflite"
LABELS_FILE = "BirdNET_GLOBAL_6K_V2.4_Labels.txt"
MODEL_LICENSE = "CC BY-NC-SA 4.0"


class BirdNETUnavailable(RuntimeError):
    """Weights or an inference runtime could not be found."""


def _interpreter_cls():
    try:
        from ai_edge_litert.interpreter import Interpreter  # type: ignore

        return Interpreter
    except ImportError:
        pass
    try:
        from tflite_runtime.interpreter import Interpreter  # type: ignore

        return Interpreter
    except ImportError:
        pass
    try:
        import tensorflow as tf  # type: ignore

        return tf.lite.Interpreter
    except ImportError as exc:
        raise BirdNETUnavailable(
            "No TFLite runtime found. Install with: pip install -e '.[birdnet]'"
        ) from exc


def resolve_model_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("BIRDNET_MODEL_DIR")
    if env:
        candidates.append(Path(env))
    # Locate birdnetlib's bundled weights without importing it (its __init__
    # imports tensorflow/tflite_runtime, which we do not require).
    import importlib.util

    spec = importlib.util.find_spec("birdnetlib")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            candidates.append(Path(loc) / "models" / "analyzer")
    for c in candidates:
        if (c / MODEL_FILE).exists() and (c / LABELS_FILE).exists():
            return c
    raise BirdNETUnavailable(
        "BirdNET v2.4 weights not found. Install with pip install -e '.[birdnet]' "
        "or set BIRDNET_MODEL_DIR to a folder containing "
        f"{MODEL_FILE} and {LABELS_FILE}."
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _dual_output_model(src: Path, cache_dir: Path) -> Path:
    """Return a copy of the model whose subgraph also outputs the embedding."""
    import flatbuffers

    try:
        from ai_edge_litert import schema_py_generated as schema  # type: ignore
    except ImportError:  # pragma: no cover - older runtimes
        from tensorflow.lite.python import schema_py_generated as schema  # type: ignore

    digest = sha256_file(src)[:16]
    dst = cache_dir / f"birdnet_v24_dual_{digest}.tflite"
    if dst.exists():
        return dst
    cache_dir.mkdir(parents=True, exist_ok=True)
    buf = src.read_bytes()
    model = schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]
    logits_idx = int(sg.outputs[0])
    emb_idx = logits_idx - 1
    name = sg.tensors[emb_idx].name
    if b"GLOBAL_AVG_POOL" not in (name or b""):
        raise BirdNETUnavailable(f"Unexpected BirdNET graph layout (tensor {name!r}).")
    sg.outputs = np.array([logits_idx, emb_idx], dtype=np.int32)
    builder = flatbuffers.Builder(1024)
    builder.Finish(model.Pack(builder), file_identifier=b"TFL3")
    tmp = dst.with_suffix(".tmp")
    tmp.write_bytes(bytes(builder.Output()))
    tmp.replace(dst)
    return dst


def week_48(d: date) -> int:
    """BirdNET's 48-week calendar: four 'weeks' per month."""
    return (d.month - 1) * 4 + min(4, (d.day - 1) // 7 + 1)


def load_non_bird_map() -> dict[str, str]:
    data = json.loads(
        resources.files("thicket.models.data").joinpath("birdnet_v24_taxa.json").read_text()
    )
    return dict(data["non_bird_labels"])


@dataclass(frozen=True)
class Label:
    raw: str
    scientific_name: str
    common_name: str
    taxon: str


def parse_label(raw: str, non_bird: dict[str, str]) -> Label:
    """BirdNET labels are 'Genus species_Common Name'. Parsed only here."""
    sci, _, common = raw.partition("_")
    return Label(
        raw=raw,
        scientific_name=sci.strip(),
        common_name=common.strip() or sci.strip(),
        taxon=non_bird.get(raw, "bird"),
    )


def frame_windows(
    samples: np.ndarray,
    hop_seconds: float = WINDOW_SECONDS,
    min_tail_seconds: float = 1.0,
    sample_rate: int = SAMPLE_RATE,
) -> tuple[np.ndarray, np.ndarray]:
    """Split mono 48 kHz audio into 3 s windows. Returns (windows, start_seconds).

    The final partial window is zero-padded when it holds at least
    ``min_tail_seconds`` of audio; otherwise it is dropped.
    """
    win = int(WINDOW_SECONDS * sample_rate)
    hop = max(1, int(hop_seconds * sample_rate))
    n = len(samples)
    starts: list[int] = []
    s = 0
    while s < n:
        remaining = n - s
        if remaining >= win or remaining >= min_tail_seconds * sample_rate or s == 0:
            starts.append(s)
        if s + win >= n:
            break
        s += hop
    out = np.zeros((len(starts), win), dtype=np.float32)
    for i, st in enumerate(starts):
        chunk = samples[st : st + win]
        out[i, : len(chunk)] = chunk
    return out, np.asarray(starts, dtype=np.float64) / sample_rate


class BirdNETRuntime:
    """Thread-safe BirdNET v2.4 inference with logits + embeddings."""

    def __init__(
        self,
        model_dir: str | os.PathLike[str] | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        num_threads: int | None = None,
    ) -> None:
        self.model_dir = resolve_model_dir(model_dir)
        self.cache_dir = Path(
            cache_dir or os.environ.get("THICKET_CACHE_DIR", Path.home() / ".cache" / "thicket")
        )
        self.num_threads = num_threads or max(1, min(4, os.cpu_count() or 1))
        self._lock = threading.Lock()
        self._interp = None
        self._meta = None
        raw = (self.model_dir / LABELS_FILE).read_text(encoding="utf-8").splitlines()
        non_bird = load_non_bird_map()
        self.labels: list[Label] = [parse_label(r.strip(), non_bird) for r in raw if r.strip()]
        self.index_by_scientific = {lab.scientific_name: i for i, lab in enumerate(self.labels)}

    @cached_property
    def model_sha256(self) -> str:
        return sha256_file(self.model_dir / MODEL_FILE)

    def load(self) -> None:
        with self._lock:
            if self._interp is not None:
                return
            Interpreter = _interpreter_cls()
            path = _dual_output_model(self.model_dir / MODEL_FILE, self.cache_dir)
            interp = Interpreter(model_path=str(path), num_threads=self.num_threads)
            interp.allocate_tensors()
            self._in_idx = interp.get_input_details()[0]["index"]
            outs = interp.get_output_details()
            by_width = {int(o["shape"][-1]): o["index"] for o in outs}
            self._logit_idx = by_width[len(self.labels)]
            self._emb_idx = by_width[1024]
            self._interp = interp

    @property
    def ready(self) -> bool:
        return self._interp is not None

    def infer(self, windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Run the model on (N, 144000) float32 windows.

        Returns (logits[N, 6522], embeddings[N, 1024]).
        """
        self.load()
        n = windows.shape[0]
        logits = np.zeros((n, len(self.labels)), dtype=np.float32)
        embs = np.zeros((n, 1024), dtype=np.float32)
        with self._lock:
            assert self._interp is not None
            for i in range(n):
                self._interp.set_tensor(
                    self._in_idx, windows[i : i + 1].astype(np.float32, copy=False)
                )
                self._interp.invoke()
                logits[i] = self._interp.get_tensor(self._logit_idx)[0]
                embs[i] = self._interp.get_tensor(self._emb_idx)[0]
        return logits, embs

    @staticmethod
    def sigmoid(logits: np.ndarray, sensitivity: float = 1.0) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-sensitivity * np.clip(logits, -20.0, 20.0)))

    def species_filter(self, latitude: float, longitude: float, week: int = -1) -> np.ndarray:
        """BirdNET meta-model occurrence probability for each label (0..1)."""
        with self._lock:
            if self._meta is None:
                Interpreter = _interpreter_cls()
                m = Interpreter(model_path=str(self.model_dir / META_FILE), num_threads=1)
                m.allocate_tensors()
                self._meta = m
            m = self._meta
            inp = m.get_input_details()[0]["index"]
            out = m.get_output_details()[0]["index"]
            m.set_tensor(inp, np.array([[latitude, longitude, float(week)]], dtype=np.float32))
            m.invoke()
            return np.asarray(m.get_tensor(out)[0], dtype=np.float32)

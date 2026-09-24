"""Optional second embedding backbone: Google Perch 2.0 (Apache-2.0).

Reads a shard manifest written by ``collect_inat.py embed`` plus the audio it
downloaded, and writes ``perch_part_XX.npz`` with 1536-d embeddings for 5 s
windows at 32 kHz. Used only to compare backbones in the benchmark; failures
here never block the dataset build.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))

SR = 32_000
WIN = 5 * SR
CANDIDATES = [
    "google/bird-vocalization-classifier/tensorFlow2/perch_v2_cpu",
    "google/bird-vocalization-classifier/tensorFlow2/perch_v2",
]


def load_model():
    import kagglehub
    import tensorflow as tf

    last: Exception | None = None
    for handle in CANDIDATES:
        try:
            path = kagglehub.model_download(handle)
            model = tf.saved_model.load(path)
            return model, path, handle
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[perch] could not load {handle}: {exc}", flush=True)
    raise RuntimeError(f"Perch unavailable: {last}")


def run(model, batch: np.ndarray) -> dict[str, np.ndarray]:
    import tensorflow as tf

    x = tf.constant(batch, dtype=tf.float32)
    if hasattr(model, "signatures") and "serving_default" in model.signatures:
        out = model.signatures["serving_default"](inputs=x)
    else:  # Perch v1 style
        out = model.infer_tf(x)
    return {k: v.numpy() for k, v in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--max-seconds", type=float, default=60.0)
    args = ap.parse_args()

    from thicket.services.audio_io import decode

    cfg = json.loads(Path(args.config).read_text())
    target_names = [n for grp in ("frogs", "insects") for n, _ in cfg["targets"][grp]]
    target_names += [n for n, _ in cfg["birds"]["species"]]

    model, path, handle = load_model()
    labels: list[str] = []
    for cand in ("assets/labels.csv", "assets/label.csv", "labels.csv"):
        p = Path(path) / cand
        if p.exists():
            with open(p) as f:
                rows = list(csv.reader(f))
            labels = (
                [r[0] for r in rows[1:]]
                if rows and not rows[0][0].startswith(" ")
                else [r[0] for r in rows]
            )
            break
    label_idx = {n: i for i, n in enumerate(labels)}
    subset = [n for n in target_names if n in label_idx]
    sub_idx = np.array([label_idx[n] for n in subset], dtype=np.int64)
    print(
        f"[perch] loaded {handle}; {len(labels)} labels; {len(subset)} target species covered",
        flush=True,
    )

    with open(args.manifest) as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "ok" and r.get("audio_file")]
    embs, sids, starts, subs = [], [], [], []
    t0 = time.time()
    emb_key = None
    for k, r in enumerate(rows):
        try:
            x, _ = decode(
                Path(args.audio_dir) / r["audio_file"], target_sr=SR, max_seconds=args.max_seconds
            )
        except Exception:  # noqa: BLE001
            continue
        n = max(1, int(np.ceil(len(x) / WIN)))
        if len(x) < n * WIN:
            x = np.concatenate([x, np.zeros(n * WIN - len(x), np.float32)])
        batch = x[: n * WIN].reshape(n, WIN)
        out = run(model, batch)
        if emb_key is None:
            emb_key = next((key for key, v in out.items() if key == "embedding"), None) or next(
                key for key, v in out.items() if v.ndim == 2 and v.shape[-1] in (1280, 1536)
            )
            print(
                f"[perch] outputs: {{{', '.join(f'{k}: {v.shape}' for k, v in out.items())}}}",
                flush=True,
            )
        embs.append(out[emb_key].astype(np.float16))
        sids.append(np.full(n, int(r["sound_id"]), dtype=np.int64))
        starts.append(np.arange(n, dtype=np.float32) * 5.0)
        logit_key = "label" if "label" in out else None
        if logit_key and len(sub_idx):
            subs.append(out[logit_key][:, sub_idx].astype(np.float16))
        if (k + 1) % 50 == 0:
            print(f"[perch] {k + 1}/{len(rows)} in {time.time() - t0:.0f}s", flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        embedding=np.concatenate(embs) if embs else np.zeros((0, 1536), np.float16),
        sound_id=np.concatenate(sids) if sids else np.zeros(0, np.int64),
        start_s=np.concatenate(starts) if starts else np.zeros(0, np.float32),
        subset_logits=np.concatenate(subs) if subs else np.zeros((0, len(subset)), np.float16),
        subset_labels=np.asarray(subset),
        model_handle=np.asarray(handle),
    )
    print(f"[perch] wrote {args.out} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

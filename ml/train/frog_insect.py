"""Frog and insect species head on BirdNET v2.4 embeddings (thicket-inat-v1 format).

Input: a dataset folder written by ``ml/pipeline/collect_inat.py merge``:
``manifest.csv`` + ``birdnet_part_XX.npz`` (and optionally ``perch_part_XX.npz``).

Steps
  1. Validate before any metric (spec section 8): run parameters, manifest
     integrity, label-set compatibility with the config, model identity.
  2. Observer-grouped, stratified train / val / test split (default 70/15/15,
     seeded). No observer appears in two splits.
  3. Negatives: bird benchmark recordings and the open-set groups
     (other_anura, other_orthoptera, other_cicadas, mammals) with all-zero targets.
  4. Drop windows quieter than an RMS floor.
  5. Stage 1: multi-label head on all windows, each window gets its
     recording's (weak) label. C tuned on validation recordings.
  6. Stage 2: multiple-instance refinement. For positive recordings keep only
     the top-k windows by stage-1 score for the labeled class; keep all
     windows of negative recordings; retrain (C re-tuned on validation).
     The stage used for export is chosen on validation macro AP.
  7. Recording level = max over windows. Temperature scaling and per-class
     thresholds are fit on validation only.
  8. Test metrics: per-class AP, ROC AUC, precision / recall / F1 at the
     validation thresholds, bootstrap CIs resampling observers, macro and
     micro, calibration, open-set false positive rate, BirdNET zero-shot on the
     classes BirdNET covers (``subset_logits``), optional Perch comparison.
  9. Writes a Markdown report, figures, ``results.json``, ``splits.csv`` and
     the exported head (``frog_insect_head_v1.npz``).

    python ml/train/frog_insect.py --data <dataset dir> --out <output dir>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend"))

import evalkit as ek  # noqa: E402
from linear import Standardizer, fit_mlp, fit_multilabel  # noqa: E402

DEFAULT_CONFIG = REPO / "ml" / "configs" / "inat_v1.json"
NEGATIVE_GROUPS = ("bird", "other_anura", "other_orthoptera", "other_cicadas", "mammals")
TARGET_GROUPS = {"frog": "amphibian", "insect": "insect"}
REQUIRED_COLUMNS = ("group", "label", "sound_id", "user_id", "status", "n_windows", "sha256")
BIRDNET_PART_KEYS = (
    "embedding",
    "sound_id",
    "start_s",
    "rms_dbfs",
    "subset_logits",
    "subset_labels",
    "top5_index",
    "top5_prob",
    "max_bird_prob",
)
EMBED_DIM = 1024
C_GRID = [0.001, 0.003, 0.01, 0.03, 0.1]


class ValidationError(RuntimeError):
    """The dataset or run parameters failed a pre-metric check."""


# ============================================================ config + checks


@dataclass
class LabelSet:
    labels: list[str]
    common: list[str]
    taxa: list[str]

    @classmethod
    def from_config(cls, cfg: dict) -> LabelSet:
        labels, common, taxa = [], [], []
        for group, taxon in (("frogs", "amphibian"), ("insects", "insect")):
            for sci, com in cfg["targets"][group]:
                labels.append(sci)
                common.append(com)
                taxa.append(taxon)
        if len(set(labels)) != len(labels):
            raise ValidationError("duplicate target labels in config")
        return cls(labels, common, taxa)

    def subset(self, keep: list[str]) -> LabelSet:
        idx = [self.labels.index(k) for k in keep]
        return LabelSet(
            [self.labels[i] for i in idx],
            [self.common[i] for i in idx],
            [self.taxa[i] for i in idx],
        )


@dataclass
class Checks:
    items: list[dict] = field(default_factory=list)

    def ok(self, name: str, detail: str = "") -> None:
        self.items.append({"check": name, "status": "pass", "detail": detail})

    def warn(self, name: str, detail: str) -> None:
        self.items.append({"check": name, "status": "warn", "detail": detail})
        print(f"[check] WARN {name}: {detail}", flush=True)

    def fail(self, name: str, detail: str) -> None:
        self.items.append({"check": name, "status": "fail", "detail": detail})
        raise ValidationError(f"{name}: {detail}")


def check_args(args: argparse.Namespace, checks: Checks) -> None:
    fr = [args.train_frac, args.val_frac, args.test_frac]
    if min(fr) <= 0 or abs(sum(fr) - 1.0) > 1e-6:
        checks.fail("run parameters", f"split fractions must be positive and sum to 1, got {fr}")
    if not -120.0 <= args.rms_floor <= 0.0:
        checks.fail("run parameters", f"rms floor {args.rms_floor} dBFS out of range")
    if args.top_k < 1:
        checks.fail("run parameters", "top-k must be >= 1")
    if args.model not in ("linear", "mlp"):
        checks.fail("run parameters", f"unknown model {args.model}")
    checks.ok(
        "run parameters",
        f"split {fr}, seed {args.seed}, rms floor {args.rms_floor} dBFS, top-k {args.top_k}, "
        f"model {args.model}, C grid {C_GRID}",
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_manifest(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def birdnet_label_space() -> tuple[set[str] | None, set[str], str | None]:
    """(all BirdNET labels if the runtime is installed, non-bird labels, model sha256)."""
    taxa = json.loads(
        (REPO / "backend" / "thicket" / "models" / "data" / "birdnet_v24_taxa.json").read_text()
    )
    non_bird = set(taxa["non_bird_labels"])
    try:
        from thicket.models.birdnet_runtime import LABELS_FILE, MODEL_FILE, resolve_model_dir

        d = resolve_model_dir()
        labels = {
            ln.strip()
            for ln in (d / LABELS_FILE).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        return labels, non_bird, sha256_file(d / MODEL_FILE)
    except Exception:  # noqa: BLE001 - BirdNET is optional for this script
        return None, non_bird, None


@dataclass
class Dataset:
    rec: dict  # column -> np.ndarray, one row per usable recording
    emb: np.ndarray
    win_rec: np.ndarray  # recording row index per window
    start_s: np.ndarray
    rms: np.ndarray
    subset_logits: np.ndarray
    subset_labels: list[str]
    perch: dict | None
    fingerprint: dict


def load_and_validate(data: Path, cfg: dict, labelset: LabelSet, args, checks: Checks) -> Dataset:
    man_path = data / "manifest.csv"
    parts = sorted(data.glob("birdnet_part_*.npz"))
    if not man_path.exists() or not parts:
        checks.fail("manifest integrity", f"need manifest.csv and birdnet_part_*.npz in {data}")
    rows = read_manifest(man_path)
    missing = [c for c in REQUIRED_COLUMNS if rows and c not in rows[0]]
    if not rows or missing:
        checks.fail("manifest integrity", f"manifest empty or missing columns {missing}")
    sids = [r["sound_id"] for r in rows]
    if len(set(sids)) != len(sids):
        checks.fail("manifest integrity", "duplicate sound_id in manifest")
    ok = [r for r in rows if r["status"] == "ok"]
    groups = {r["group"] for r in ok}
    unknown = groups - set(TARGET_GROUPS) - set(NEGATIVE_GROUPS)
    if unknown:
        checks.fail("manifest integrity", f"unknown groups {sorted(unknown)}")
    for r in ok:
        if r["group"] in TARGET_GROUPS and not r["label"]:
            checks.fail("manifest integrity", f"target recording {r['sound_id']} has no label")
        if r["group"] in NEGATIVE_GROUPS and r["group"] != "bird" and r["label"]:
            checks.fail("manifest integrity", f"open-set recording {r['sound_id']} has a label")
        if not r["user_id"]:
            checks.fail("manifest integrity", f"recording {r['sound_id']} has no user_id")
    # Duplicate audio (same bytes under two sound ids) would leak across splits.
    seen: dict[str, str] = {}
    dup: set[str] = set()
    for r in ok:
        if r["sha256"] and r["sha256"] in seen:
            dup.add(r["sound_id"])
        elif r["sha256"]:
            seen[r["sha256"]] = r["sound_id"]
    if dup:
        checks.warn(
            "manifest integrity",
            f"dropped {len(dup)} recordings whose audio bytes duplicate another recording",
        )
    ok = [r for r in ok if r["sound_id"] not in dup]

    # Label-set compatibility.
    tlabels = {r["label"] for r in ok if r["group"] in TARGET_GROUPS}
    extra = tlabels - set(labelset.labels)
    if extra:
        checks.fail(
            "label-set compatibility", f"manifest labels not in config targets: {sorted(extra)}"
        )
    for r in ok:
        if r["group"] in TARGET_GROUPS:
            want = TARGET_GROUPS[r["group"]]
            got = labelset.taxa[labelset.labels.index(r["label"])]
            if want != got:
                checks.fail(
                    "label-set compatibility",
                    f"{r['label']} is in group {r['group']} but config taxon {got}",
                )
    absent = [lab for lab in labelset.labels if lab not in tlabels]
    if absent:
        checks.warn(
            "label-set compatibility",
            f"{len(absent)} config targets have no usable recordings: {absent}",
        )
    else:
        checks.ok("label-set compatibility", f"all {len(labelset.labels)} config targets present")

    # Load parts.
    embs, wsid, st, rms, subl = [], [], [], [], []
    sub_labels: list[str] | None = None
    pshas = {}
    for p in parts:
        z = np.load(p, allow_pickle=False)
        miss = [k for k in BIRDNET_PART_KEYS if k not in z.files]
        if miss:
            checks.fail("model identity", f"{p.name} lacks {miss}")
        if z["embedding"].shape[1:] != (EMBED_DIM,):
            checks.fail(
                "model identity",
                f"{p.name} embedding dim {z['embedding'].shape[1:]} != {EMBED_DIM}",
            )
        labs = [str(x) for x in z["subset_labels"]]
        if sub_labels is None:
            sub_labels = labs
        elif labs != sub_labels:
            checks.fail("model identity", f"{p.name} subset_labels differ from the first part")
        if "birdnet_sha256" in z.files:
            exp = args.expected_birdnet_sha256 or birdnet_label_space()[2]
            if exp and str(z["birdnet_sha256"]) != exp:
                checks.fail(
                    "model identity",
                    f"{p.name} BirdNET sha256 {z['birdnet_sha256']} != expected {exp}",
                )
        embs.append(z["embedding"])
        wsid.append(z["sound_id"].astype(np.int64))
        st.append(z["start_s"].astype(np.float32))
        rms.append(z["rms_dbfs"].astype(np.float32))
        subl.append(z["subset_logits"])
        pshas[p.name] = sha256_file(p)
    assert sub_labels is not None
    all_labels, non_bird, model_sha = birdnet_label_space()
    not_birdnet = [s for s in sub_labels if (s not in all_labels if all_labels else ("_" not in s))]
    nb_in_subset = {s for s in sub_labels if s in non_bird}
    if not_birdnet:
        checks.fail("model identity", f"subset labels not in BirdNET v2.4: {not_birdnet[:5]}")
    if nb_in_subset != non_bird:
        checks.fail(
            "model identity",
            "subset labels do not contain exactly the BirdNET v2.4 non-bird label set",
        )
    checks.ok(
        "model identity",
        f"{len(parts)} parts, 1024-d embeddings, {len(sub_labels)} subset labels match BirdNET v2.4"
        + (
            f" (verified against local weights sha256 {model_sha[:12]})"
            if model_sha
            else " (label file check only; BirdNET weights not installed here)"
        )
        + (
            ""
            if any("birdnet_sha256" in np.load(p).files for p in parts)
            else "; parts carry no weights hash, so identity rests on the label space"
        ),
    )
    emb = np.concatenate(embs).astype(np.float32)
    wsid = np.concatenate(wsid)
    start_s = np.concatenate(st)
    rms_all = np.concatenate(rms)
    sub_all = np.concatenate(subl).astype(np.float32)

    # Window counts must match the manifest.
    ok_by_sid = {int(r["sound_id"]): r for r in ok}
    uniq, counts = np.unique(wsid, return_counts=True)
    dup_ids = {int(x) for x in dup}
    stray = [int(s) for s in uniq if int(s) not in ok_by_sid and int(s) not in dup_ids]
    if stray:
        checks.fail(
            "manifest integrity",
            f"{len(stray)} sound_ids in features are not 'ok' rows of the manifest, e.g. {stray[:3]}",
        )
    cnt = dict(zip(uniq.tolist(), counts.tolist(), strict=True))
    bad = [s for s, r in ok_by_sid.items() if cnt.get(s, 0) != int(r["n_windows"])]
    if bad:
        checks.fail(
            "manifest integrity",
            f"{len(bad)} recordings have a window count different from manifest n_windows, e.g. {bad[:3]}",
        )
    keep_w = np.isin(wsid, list(ok_by_sid))
    checks.ok(
        "manifest integrity",
        f"{len(rows)} manifest rows, {len(ok_by_sid)} usable recordings, {int(keep_w.sum())} windows; counts match",
    )

    # Recording table (only recordings with windows).
    order = sorted(ok_by_sid)
    rec = {
        "sound_id": np.array(order, dtype=np.int64),
        "group": np.array([ok_by_sid[s]["group"] for s in order]),
        "label": np.array(
            [ok_by_sid[s]["label"] if ok_by_sid[s]["group"] in TARGET_GROUPS else "" for s in order]
        ),
        "user_id": np.array([ok_by_sid[s]["user_id"] for s in order]),
        "license": np.array([ok_by_sid[s].get("license_code", "") for s in order]),
    }
    pos = {s: i for i, s in enumerate(order)}
    win_rec = np.array([pos.get(int(s), -1) for s in wsid])
    m = win_rec >= 0
    perch = load_perch(data, checks)
    fp = {
        "manifest_sha256": sha256_file(man_path),
        "parts": pshas,
        "config_sha256": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
    }
    return Dataset(
        rec, emb[m], win_rec[m], start_s[m], rms_all[m], sub_all[m], sub_labels, perch, fp
    )


def load_perch(data: Path, checks: Checks) -> dict | None:
    parts = sorted(data.glob("perch_part_*.npz"))
    if not parts:
        return None
    embs, sids, subs = [], [], []
    labels = handle = None
    for p in parts:
        z = np.load(p, allow_pickle=False)
        if len(z["sound_id"]) == 0:
            continue
        embs.append(z["embedding"].astype(np.float32))
        sids.append(z["sound_id"].astype(np.int64))
        subs.append(z["subset_logits"].astype(np.float32) if z["subset_logits"].size else None)
        labels = [str(x) for x in z["subset_labels"]]
        h = str(z["model_handle"])
        if handle is not None and h != handle:
            checks.fail(
                "model identity", f"Perch parts come from different models: {handle} vs {h}"
            )
        handle = h
    if not embs:
        return None
    checks.ok(
        "model identity (Perch)", f"{len(parts)} Perch parts from {handle}, dim {embs[0].shape[1]}"
    )
    return {
        "embedding": np.concatenate(embs),
        "sound_id": np.concatenate(sids),
        "handle": handle,
        "subset_labels": labels,
    }


# ============================================================ split


def observer_split(rec: dict, fracs: tuple[float, float, float], seed: int) -> np.ndarray:
    """Assign each recording to train / val / test so that observers never
    straddle splits, stratified by label (targets) or group (negatives)."""
    from sklearn.model_selection import StratifiedGroupKFold

    strata = np.where(rec["label"] != "", rec["label"], rec["group"])
    users = rec["user_id"]
    n_users = len(np.unique(users))
    n_splits = int(min(20, n_users))
    if n_splits < 3:
        raise ValidationError("need at least 3 observers to split")
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    fold = np.zeros(len(strata), dtype=int)
    for f, (_, te) in enumerate(sgkf.split(np.zeros(len(strata)), strata, users)):
        fold[te] = f
    perm = np.random.default_rng(seed).permutation(n_splits)
    n_tr = max(1, int(round(fracs[0] * n_splits)))
    n_va = max(1, int(round(fracs[1] * n_splits)))
    split = np.empty(len(strata), dtype=object)
    for rank, f in enumerate(perm):
        split[fold == f] = "train" if rank < n_tr else ("val" if rank < n_tr + n_va else "test")
    assert_observer_disjoint(users, split)
    return split.astype(str)


def assert_observer_disjoint(users: np.ndarray, split: np.ndarray) -> None:
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        both = set(users[split == a]) & set(users[split == b])
        if both:
            raise ValidationError(f"observers in both {a} and {b}: {sorted(both)[:5]}")


# ============================================================ model


@dataclass
class Head:
    sc: Standardizer
    W1: np.ndarray
    b1: np.ndarray
    W2: np.ndarray | None = None
    b2: np.ndarray | None = None
    C: float = 0.0

    def logits(self, X: np.ndarray) -> np.ndarray:
        H = self.sc(X).astype(np.float32) @ self.W1.astype(np.float32) + self.b1
        if self.W2 is None:
            return H.astype(np.float64)
        return (np.maximum(H, 0) @ self.W2.astype(np.float32) + self.b2).astype(np.float64)


def fit_head(X, T, sw, C, args) -> Head:
    sc = Standardizer.fit(X)
    Xs = sc(X)
    if args.model == "mlp":
        W1, b1, W2, b2 = fit_mlp(Xs, T, args.hidden, C, seed=args.seed, sample_weight=sw)
        return Head(sc, W1, b1, W2, b2, C)
    W, b = fit_multilabel(Xs, T, C, sample_weight=sw)
    return Head(sc, W, b, None, None, C)


def rec_max(Z: np.ndarray, win_rec: np.ndarray, n_rec: int) -> np.ndarray:
    out = np.full((n_rec, Z.shape[1]), -np.inf)
    np.maximum.at(out, win_rec, Z)
    return out


def macro_ap(Y: np.ndarray, S: np.ndarray) -> float:
    vals = [ek.safe_ap(Y[:, k], S[:, k]) for k in range(Y.shape[1]) if Y[:, k].any()]
    return float(np.mean(vals)) if vals else float("nan")


def window_weights(win_rec: np.ndarray) -> np.ndarray:
    """Each recording contributes total weight 1, rescaled to mean 1."""
    cnt = np.bincount(win_rec)
    w = 1.0 / cnt[win_rec]
    return w * (len(w) / w.sum())


def train_select(
    Xw, win_rec, Yrec, tr_w, va_rec, va_w, args, stage_name: str, keep=None
) -> tuple[Head, dict]:
    """Fit on training windows (optionally a subset ``keep``), choose C on validation recordings."""
    idx = np.flatnonzero(tr_w if keep is None else (tr_w & keep))
    sw = window_weights(np.unique(win_rec[idx], return_inverse=True)[1])
    T = Yrec[win_rec[idx]]
    best, scores = None, {}
    va_idx = np.flatnonzero(va_w)
    va_rows = np.flatnonzero(va_rec)
    for C in C_GRID:
        t0 = time.time()
        h = fit_head(Xw[idx], T, sw, C, args)
        Zv = rec_max(h.logits(Xw[va_idx]), win_rec[va_idx], len(Yrec))[va_rows]
        scores[C] = macro_ap(Yrec[va_rows], Zv)
        print(
            f"[{stage_name}] C={C} val macro AP {scores[C]:.4f} ({time.time() - t0:.0f}s, {len(idx)} windows)",
            flush=True,
        )
        if best is None or scores[C] > scores[best.C] + 1e-9:
            best = h
    assert best is not None
    return best, {
        "val_macro_ap_by_C": {str(k): v for k, v in scores.items()},
        "C": best.C,
        "n_windows": int(len(idx)),
    }


def mil_keep(h: Head, Xw, win_rec, Yrec, tr_w, k: int) -> np.ndarray:
    """Stage-2 window mask: top-k windows (by stage-1 score for the labeled
    class) of each positive training recording, all windows of negatives."""
    keep = np.zeros(len(win_rec), dtype=bool)
    tr_idx = np.flatnonzero(tr_w)
    r = win_rec[tr_idx]
    pos = Yrec[r].any(1)
    Z = h.logits(Xw[tr_idx])
    s = Z[np.arange(len(tr_idx)), np.argmax(Yrec[r], 1)]
    order = np.lexsort((-s, r))  # by recording, then by descending score
    r_sorted = r[order]
    first = np.r_[0, np.flatnonzero(r_sorted[1:] != r_sorted[:-1]) + 1]
    start = np.repeat(first, np.diff(np.r_[first, len(order)]))
    rank = np.arange(len(order)) - start
    sel = order[(rank < k) | ~pos[order]]
    keep[tr_idx[sel]] = True
    return keep


# ============================================================ evaluation


def evaluate_split(Y, P, D, users, labels, n_boot, seed) -> dict:
    keep = [k for k in range(Y.shape[1]) if Y[:, k].any()]
    tab = ek.per_class_table(
        Y[:, keep], P[:, keep], D[:, keep], [labels[k] for k in keep], users, n_boot, seed
    )
    tab["classes_without_test_positives"] = [labels[k] for k in range(Y.shape[1]) if k not in keep]
    return tab


def open_set(rec: dict, rows: np.ndarray, D: np.ndarray) -> dict:
    out = {}
    neg = rec["label"][rows] == ""
    for g in NEGATIVE_GROUPS:
        m = neg & (rec["group"][rows] == g)
        if m.any():
            out[g] = ek.wilson(int(D[m].any(1).sum()), int(m.sum()))
    out["all_negatives"] = ek.wilson(int(D[neg].any(1).sum()), int(neg.sum()))
    return out


def birdnet_zero_shot(
    ds: Dataset, labelset: LabelSet, va_rows, te_rows, Yrec, users, n_boot, seed
) -> dict:
    sci = [s.split("_")[0] for s in ds.subset_labels]
    covered = [(k, sci.index(lab)) for k, lab in enumerate(labelset.labels) if lab in sci]
    if not covered:
        return {"covered": []}
    ks = [k for k, _ in covered]
    js = [j for _, j in covered]
    Srec = ek.sigmoid(rec_max(ds.subset_logits[:, js], ds.win_rec, len(Yrec)))
    thr = np.array(
        [
            ek.choose_threshold(Yrec[va_rows, i], Srec[va_rows, n], "f1")
            if Yrec[va_rows, i].any()
            else 1.0
            for n, i in enumerate(ks)
        ]
    )
    y_te = Yrec[te_rows][:, ks]
    s_te = Srec[te_rows]
    names = [labelset.labels[k] for k in ks]
    out = {
        "covered": names,
        "thresholds_val_f1": dict(zip(names, thr.tolist(), strict=True)),
        "test": evaluate_split(y_te, s_te, s_te >= thr[None, :], users, names, n_boot, seed),
        "test_at_0.6": evaluate_split(y_te, s_te, s_te >= 0.6, users, names, n_boot, seed),
        "scores_test": s_te,
        "class_index": ks,
    }
    return out


def perch_compare(
    ds: Dataset, split: np.ndarray, Yrec: np.ndarray, users_rec: np.ndarray, args, n_boot
) -> dict | None:
    if ds.perch is None:
        return None
    pos = {int(s): i for i, s in enumerate(ds.rec["sound_id"])}
    wr = np.array([pos.get(int(s), -1) for s in ds.perch["sound_id"]])
    m = wr >= 0
    X, wr = ds.perch["embedding"][m], wr[m]
    have = np.zeros(len(Yrec), bool)
    have[wr] = True
    tr_w = split[wr] == "train"
    va_rec = (split == "val") & have
    te_rows = np.flatnonzero((split == "test") & have)
    h, info = train_select(
        X,
        wr,
        Yrec,
        tr_w,
        va_rec,
        split[wr] == "val",
        argparse.Namespace(**{**vars(args), "model": "linear"}),
        "perch",
    )
    Zt = rec_max(h.logits(X[split[wr] == "test"]), wr[split[wr] == "test"], len(Yrec))[te_rows]
    Yt = Yrec[te_rows]
    keep = [k for k in range(Yt.shape[1]) if Yt[:, k].any()]
    return {
        "handle": ds.perch["handle"],
        "n_test_recordings": int(len(te_rows)),
        "selection": info,
        "test_macro_ap": ek.cluster_bootstrap(
            lambda i: macro_ap(Yt[i][:, keep], Zt[i][:, keep]), users_rec[te_rows], n_boot, 77
        ),
        "test_rows": te_rows,
    }


# ============================================================ main pipeline


def run(args: argparse.Namespace) -> dict:
    t_start = time.time()
    out = Path(args.out)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(args.config).read_text())
    checks = Checks()
    check_args(args, checks)
    full = LabelSet.from_config(cfg)
    ds = load_and_validate(Path(args.data), cfg, full, args, checks)

    rec = ds.rec
    n_rec = len(rec["sound_id"])
    split = observer_split(rec, (args.train_frac, args.val_frac, args.test_frac), args.seed)
    checks.ok(
        "observer-disjoint split",
        f"{len(np.unique(rec['user_id']))} observers, no observer in two splits",
    )
    with open(out / "splits.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sound_id", "user_id", "group", "label", "split"])
        for i in range(n_rec):
            w.writerow(
                [rec["sound_id"][i], rec["user_id"][i], rec["group"][i], rec["label"][i], split[i]]
            )

    # Classes with enough training data are modeled; others are reported only.
    n_train_pos = {
        lab: int(((rec["label"] == lab) & (split == "train")).sum()) for lab in full.labels
    }
    modeled = [lab for lab in full.labels if n_train_pos[lab] >= args.min_train_recordings]
    dropped = [lab for lab in full.labels if lab not in modeled]
    if dropped:
        checks.warn(
            "label-set compatibility",
            f"{len(dropped)} classes have fewer than {args.min_train_recordings} training recordings and are not modeled: {dropped}",
        )
    if not modeled:
        checks.fail("label-set compatibility", "no class has enough training recordings")
    ls = full.subset(modeled)
    Yrec = np.zeros((n_rec, len(ls.labels)))
    for k, lab in enumerate(ls.labels):
        Yrec[:, k] = rec["label"] == lab
    # Recordings of dropped classes are neither positives nor clean negatives: exclude.
    usable = (rec["label"] == "") | np.isin(rec["label"], ls.labels)

    # RMS floor (keep the loudest window of a recording that would lose all).
    keep_w = ds.rms >= args.rms_floor
    loud = np.full(n_rec, -np.inf)
    np.maximum.at(loud, ds.win_rec, ds.rms)
    rescue = (~keep_w) & (ds.rms == loud[ds.win_rec]) & ~np.isin(ds.win_rec, ds.win_rec[keep_w])
    keep_w |= rescue
    keep_w &= usable[ds.win_rec]
    Xw, wr = ds.emb[keep_w], ds.win_rec[keep_w]
    sub_logits = ds.subset_logits[keep_w]
    rms_info = {
        "floor_dbfs": args.rms_floor,
        "windows_before": int(len(ds.rms)),
        "windows_after": int(keep_w.sum()),
        "recordings_rescued": int(len(np.unique(ds.win_rec[rescue]))),
    }
    ds = Dataset(
        rec,
        Xw,
        wr,
        ds.start_s[keep_w],
        ds.rms[keep_w],
        sub_logits,
        ds.subset_labels,
        ds.perch,
        ds.fingerprint,
    )
    has_win = np.zeros(n_rec, bool)
    has_win[wr] = True
    rows = {s: np.flatnonzero((split == s) & usable & has_win) for s in ("train", "val", "test")}
    tr_w, va_w, te_w = (split[wr] == s for s in ("train", "val", "test"))
    va_rec = np.zeros(n_rec, bool)
    va_rec[rows["val"]] = True

    counts = {}
    for k, lab in enumerate(ls.labels):
        counts[lab] = {s: int(Yrec[rows[s], k].sum()) for s in rows} | {
            f"{s}_observers": int(len(np.unique(rec["user_id"][rows[s]][Yrec[rows[s], k] > 0])))
            for s in rows
        }
    for g in NEGATIVE_GROUPS:
        m = (rec["label"] == "") & (rec["group"] == g)
        counts[f"[negative] {g}"] = {s: int(m[rows[s]].sum()) for s in rows}

    # Stage 1 and stage 2.
    h1, sel1 = train_select(Xw, wr, Yrec, tr_w, va_rec, va_w, args, "stage1")
    keep = mil_keep(h1, Xw, wr, Yrec, tr_w, args.top_k)
    h2, sel2 = train_select(Xw, wr, Yrec, tr_w, va_rec, va_w, args, "stage2", keep=keep)
    va_rows = rows["val"]

    def rec_logits(h: Head, mask: np.ndarray) -> np.ndarray:
        return rec_max(h.logits(Xw[mask]), wr[mask], n_rec)

    Zv1, Zv2 = rec_logits(h1, va_w)[va_rows], rec_logits(h2, va_w)[va_rows]
    val_ap = {"stage1": macro_ap(Yrec[va_rows], Zv1), "stage2": macro_ap(Yrec[va_rows], Zv2)}
    chosen = "stage2" if val_ap["stage2"] > val_ap["stage1"] else "stage1"
    head = h2 if chosen == "stage2" else h1
    Zv = Zv2 if chosen == "stage2" else Zv1

    # Calibration + thresholds on validation only.
    T = ek.fit_temperature(Zv, Yrec[va_rows])
    Pv = ek.sigmoid(Zv / T)
    thr = np.array(
        [
            ek.choose_threshold(Yrec[va_rows, k], Pv[:, k], "f1") if Yrec[va_rows, k].any() else 1.0
            for k in range(len(ls.labels))
        ]
    )
    untuned = [ls.labels[k] for k in range(len(ls.labels)) if not Yrec[va_rows, k].any()]

    # Test.
    te_rows = rows["test"]
    users = rec["user_id"]
    results: dict = {"stage_selection": {"val_macro_ap": val_ap, "chosen": chosen}}
    for name, h in (("stage1", h1), ("stage2", h2)):
        Zt = rec_logits(h, te_w)[te_rows]
        Pt = ek.sigmoid(Zt / T)
        results[f"test_{name}"] = evaluate_split(
            Yrec[te_rows], Pt, Pt >= thr, users[te_rows], ls.labels, args.n_boot, args.seed
        )
        if name == chosen:
            Pt_chosen, Zt_chosen = Pt, Zt
    Yt = Yrec[te_rows]
    Dt = Pt_chosen >= thr
    results["calibration_test"] = {
        "temperature": T,
        "raw": ek.reliability(Yt, ek.sigmoid(Zt_chosen)),
        "calibrated": ek.reliability(Yt, Pt_chosen),
    }
    results["open_set_false_positive_rate_test"] = open_set(rec, te_rows, Dt)
    bn = birdnet_zero_shot(
        ds, ls, va_rows, te_rows, Yrec, users[te_rows], args.n_boot, args.seed + 3
    )
    if bn["covered"]:
        ks = bn["class_index"]
        Ysub = Yt[:, ks]
        Pk, Sb = Pt_chosen[:, ks], bn.pop("scores_test")
        keepk = [i for i in range(len(ks)) if Ysub[:, i].any()]
        bn["head_same_classes"] = evaluate_split(
            Ysub, Pk, Dt[:, ks], users[te_rows], bn["covered"], args.n_boot, args.seed + 4
        )
        bn["macro_ap_difference_head_minus_birdnet"] = ek.cluster_bootstrap(
            lambda i: (
                macro_ap(Ysub[i][:, keepk], Pk[i][:, keepk])
                - macro_ap(Ysub[i][:, keepk], Sb[i][:, keepk])
            ),
            users[te_rows],
            args.n_boot,
            args.seed + 5,
        )
        bn.pop("class_index")
    results["birdnet_zero_shot"] = bn
    pc = perch_compare(ds, split, Yrec, users, args, args.n_boot)
    if pc:
        tr_rows = pc.pop("test_rows")
        Zb = rec_logits(h1, te_w)
        Yb = Yrec[tr_rows]
        keepk = [k for k in range(Yb.shape[1]) if Yb[:, k].any()]
        pc["birdnet_stage1_same_recordings_macro_ap"] = ek.cluster_bootstrap(
            lambda i: macro_ap(Yb[i][:, keepk], Zb[tr_rows][i][:, keepk]),
            users[tr_rows],
            args.n_boot,
            78,
        )
    results["perch_comparison"] = pc

    # Export.
    export_path = Path(args.export_path) if args.export_path else out / "frog_insect_head_v1.npz"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {
        "W1": head.W1.astype(np.float32),
        "b1": head.b1.astype(np.float32),
        "labels": np.array(ls.labels),
        "common_names": np.array(ls.common),
        "taxa": np.array(ls.taxa),
        "thresholds": thr.astype(np.float32),
        "temperature": np.array(T, dtype=np.float32),
        "embedding_mean": head.sc.mean.astype(np.float32),
        "embedding_std": head.sc.std.astype(np.float32),
        "format": np.array("thicket-frog-insect-head/1"),
        "pooling": np.array(
            "window logits; recording score = sigmoid(max over windows / temperature)"
        ),
        "stage": np.array(chosen),
        "manifest_sha256": np.array(ds.fingerprint["manifest_sha256"]),
        "created": np.array(date.today().isoformat()),
        "license": np.array("CC BY-NC-SA 4.0"),
    }
    if head.W2 is not None:
        arrays["W2"] = head.W2.astype(np.float32)
        arrays["b2"] = head.b2.astype(np.float32)
    np.savez_compressed(export_path, **arrays)

    res = {
        "meta": {
            "date": date.today().isoformat(),
            "data": str(args.data),
            "config": str(args.config),
            "fingerprint": ds.fingerprint,
            "args": {k: v for k, v in vars(args).items()},
            "c_grid": C_GRID,
            "seconds": None,
        },
        "checks": checks.items,
        "rms": rms_info,
        "labels": {"modeled": ls.labels, "not_modeled": dropped, "untuned_thresholds": untuned},
        "counts": counts,
        "selection": {
            "stage1": sel1,
            "stage2": sel2,
            "mil_top_k": args.top_k,
            "stage2_windows": int((tr_w & keep).sum()),
        },
        "thresholds_val_f1": dict(zip(ls.labels, thr.tolist(), strict=True)),
        "results": results,
        "export": {
            "path": str(export_path),
            "sha256": sha256_file(export_path),
            "arrays": sorted(arrays),
        },
    }
    res["readiness"] = readiness(res, ls, args)
    res["meta"]["seconds"] = round(time.time() - t_start, 1)
    (out / "results.json").write_text(json.dumps(res, indent=1, default=_json_default))
    figures(res, out / "figures", ls)
    write_report(res, out / args.report_name, ls)
    print(f"[frog_insect] done in {res['meta']['seconds']}s; report {out / args.report_name}")
    return res


def readiness(res: dict, ls: LabelSet, args) -> dict:
    """Per-class evaluation bar. A class that fails it must not be enabled for
    users even if its metrics look good: the estimate is too uncertain."""
    out = {
        "min_test_recordings": args.min_test_recordings,
        "min_test_observers": args.min_test_observers,
        "classes": {},
    }
    for lab in ls.labels:
        c = res["counts"][lab]
        ok = (
            c["test"] >= args.min_test_recordings and c["test_observers"] >= args.min_test_observers
        )
        out["classes"][lab] = {
            "test_recordings": c["test"],
            "test_observers": c["test_observers"],
            "meets_bar": bool(ok),
        }
    out["n_meeting_bar"] = sum(v["meets_bar"] for v in out["classes"].values())
    return out


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


# ============================================================ figures + report


def figures(res: dict, figdir: Path, ls: LabelSet) -> None:
    from plotstyle import BLUE, NEUTRAL, ORANGE, plt

    R = res["results"]
    chosen = R["stage_selection"]["chosen"]
    tab = R[f"test_{chosen}"]["per_class"]
    bn = R["birdnet_zero_shot"].get("test", {}).get("per_class", {})
    labs = [lab for lab in ls.labels if lab in tab][::-1]
    if labs:
        fig, ax = plt.subplots(figsize=(7.5, 0.32 * len(labs) + 1.6))
        y = np.arange(len(labs))
        pts = np.array([tab[lab]["ap"] for lab in labs])
        ax.errorbar(
            pts[:, 0],
            y + 0.15,
            xerr=[pts[:, 0] - pts[:, 1], pts[:, 2] - pts[:, 0]],
            fmt="o",
            color=BLUE,
            ms=5,
            capsize=0,
            label="Thicket head",
        )
        have = [i for i, lab in enumerate(labs) if lab in bn]
        if have:
            b = np.array([bn[labs[i]]["ap"] for i in have])
            ax.errorbar(
                b[:, 0],
                np.array(have) - 0.15,
                xerr=[b[:, 0] - b[:, 1], b[:, 2] - b[:, 0]],
                fmt="o",
                color=ORANGE,
                ms=5,
                capsize=0,
                label="BirdNET zero-shot",
            )
        ax.set_yticks(y)
        ax.set_yticklabels(labs, fontsize=8, style="italic")
        ax.set_xlim(0, 1.02)
        ax.set_xlabel("Test average precision (95% CI, observer bootstrap)")
        ax.set_title("Recording-level average precision per species")
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, fontsize=9)
        fig.savefig(figdir / "frog_insect_ap.png")
        plt.close(fig)
    cal = R["calibration_test"]
    fig, ax = plt.subplots(figsize=(5, 4.6))
    ax.plot([0, 1], [0, 1], ls="--", color=NEUTRAL, lw=1.2)
    for key, col, lab in (
        ("raw", ORANGE, "Before temperature"),
        ("calibrated", BLUE, "After temperature"),
    ):
        c = np.array(cal[key]["confidence"], float)
        a = np.array(cal[key]["accuracy"], float)
        ok = np.isfinite(c)
        ax.plot(
            c[ok], a[ok], marker="o", ms=5, color=col, label=f"{lab} (ECE {cal[key]['ece']:.3f})"
        )
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed positive rate")
    ax.set_title("Test reliability, all species x recordings")
    ax.legend(loc="upper left", fontsize=9)
    fig.savefig(figdir / "frog_insect_reliability.png")
    plt.close(fig)


def write_report(res: dict, path: Path, ls: LabelSet) -> None:
    R = res["results"]
    chosen = R["stage_selection"]["chosen"]
    T = R[f"test_{chosen}"]
    L: list[str] = []
    a = L.append
    a("# Frog and insect head v1: evaluation report")
    a("")
    a(
        f"Generated by `ml/train/frog_insect.py` on {res['meta']['date']} from `{res['meta']['data']}`. All numbers below come from `results.json` in the same folder."
    )
    a("")
    a("## Pre-metric checks")
    a("")
    a("| Check | Status | Detail |")
    a("|---|---|---|")
    for c in res["checks"]:
        a(f"| {c['check']} | {c['status']} | {c['detail']} |")
    a("")
    a(
        f"Manifest sha256 `{res['meta']['fingerprint']['manifest_sha256']}`. RMS floor {res['rms']['floor_dbfs']} dBFS kept {res['rms']['windows_after']} of {res['rms']['windows_before']} windows ({res['rms']['recordings_rescued']} recordings kept only their loudest window)."
    )
    a("")
    a("## Data and splits")
    a("")
    a(
        "Splits are grouped by iNaturalist observer (`user_id`) and stratified by label: no observer contributes to two splits. Labels are clip level and weak."
    )
    a("")
    a("| Class | Train rec. | Val rec. | Test rec. | Test observers |")
    a("|---|---|---|---|---|")
    for lab, c in res["counts"].items():
        a(f"| {lab} | {c['train']} | {c['val']} | {c['test']} | {c.get('test_observers', '')} |")
    a("")
    if res["labels"]["not_modeled"]:
        a(f"Not modeled (too few training recordings): {', '.join(res['labels']['not_modeled'])}.")
        a("")
    a("## Model selection (validation only)")
    a("")
    s1, s2 = res["selection"]["stage1"], res["selection"]["stage2"]
    a(
        f"* Stage 1 (all windows, clip labels): C = {s1['C']}, val macro AP by C: "
        + ", ".join(f"{k}: {v:.3f}" for k, v in s1["val_macro_ap_by_C"].items())
        + "."
    )
    a(
        f"* Stage 2 (multiple-instance, top {res['selection']['mil_top_k']} windows per positive recording, {res['selection']['stage2_windows']} windows): C = {s2['C']}, val macro AP by C: "
        + ", ".join(f"{k}: {v:.3f}" for k, v in s2["val_macro_ap_by_C"].items())
        + "."
    )
    a(
        f"* Chosen on validation: **{chosen}** (val macro AP stage 1 {R['stage_selection']['val_macro_ap']['stage1']:.3f}, stage 2 {R['stage_selection']['val_macro_ap']['stage2']:.3f}). Temperature {R['calibration_test']['temperature']:.3f}; per-class thresholds maximize validation F1."
    )
    if res["labels"]["untuned_thresholds"]:
        a(
            f"* No validation positives, threshold set to 1.0 (never fires): {', '.join(res['labels']['untuned_thresholds'])}."
        )
    a("")
    a(f"## Test results ({chosen}, recording level = max over windows)")
    a("")
    a("95% CIs resample observers (cluster bootstrap).")
    a("")
    a("| Species | Test positives | AP | ROC AUC | Precision | Recall | F1 |")
    a("|---|---|---|---|---|---|---|")
    for lab, r in T["per_class"].items():
        a(
            f"| *{lab}* | {r['n_pos']} | {ek.fmt_ci(r['ap'])} | {ek.fmt_ci(r['auc'])} | {ek.fmt_ci(r['precision'])} | {ek.fmt_ci(r['recall'])} | {ek.fmt_ci(r['f1'])} |"
        )
    a("")
    for agg in ("macro", "micro"):
        a(
            f"* {agg.capitalize()}: "
            + ", ".join(f"{k} {ek.fmt_ci(v)}" for k, v in T[agg].items())
            + "."
        )
    other = "stage2" if chosen == "stage1" else "stage1"
    a(
        f"* The other stage ({other}) on test, for reference: macro AP {ek.fmt_ci(R[f'test_{other}']['macro']['ap'])}."
    )
    cal = R["calibration_test"]
    a(
        f"* Calibration on test: ECE {cal['raw']['ece']:.3f} before and {cal['calibrated']['ece']:.3f} after temperature scaling."
    )
    a("")
    a("Open-set false positive rate (share of negative test recordings where any species fires):")
    a("")
    for g, w in R["open_set_false_positive_rate_test"].items():
        a(f"* {g}: {w[0]:.3f} ({w[1]:.3f} to {w[2]:.3f}; {w[3]}/{w[4]})")
    a("")
    a("![Per-species AP](figures/frog_insect_ap.png)")
    a("")
    a("![Reliability](figures/frog_insect_reliability.png)")
    a("")
    bn = R["birdnet_zero_shot"]
    a("## BirdNET zero-shot on the classes it covers")
    a("")
    if bn.get("covered"):
        a(
            f"BirdNET covers {len(bn['covered'])} of the modeled classes. BirdNET score = max over the same windows of its label probability; its threshold is chosen on validation F1, like the head's."
        )
        a("")
        a(
            "| Species | BirdNET AP | Head AP | BirdNET F1 (val thr) | BirdNET F1 at 0.60 | Head F1 |"
        )
        a("|---|---|---|---|---|---|")
        for lab in bn["covered"]:
            b = bn["test"]["per_class"].get(lab)
            h = bn["head_same_classes"]["per_class"].get(lab)
            b6 = bn["test_at_0.6"]["per_class"].get(lab)
            if b and h:
                a(
                    f"| *{lab}* | {ek.fmt_ci(b['ap'])} | {ek.fmt_ci(h['ap'])} | {ek.fmt_ci(b['f1'])} | {ek.fmt_ci(b6['f1'])} | {ek.fmt_ci(h['f1'])} |"
                )
        a("")
        a(
            f"Macro AP difference (head minus BirdNET) on covered classes: {ek.fmt_ci(bn['macro_ap_difference_head_minus_birdnet'])}."
        )
    else:
        a("No modeled class is covered by BirdNET's label set.")
    a("")
    pc = R.get("perch_comparison")
    a("## Perch comparison")
    a("")
    if pc:
        a(
            f"Stage-1 linear head on Perch embeddings ({pc['handle']}), same observer splits, {pc['n_test_recordings']} test recordings with Perch features: macro AP {ek.fmt_ci(pc['test_macro_ap'])}. BirdNET-embedding stage-1 head on the same recordings: {ek.fmt_ci(pc['birdnet_stage1_same_recordings_macro_ap'])}."
        )
    else:
        a("No `perch_part_*.npz` files in the dataset; skipped.")
    a("")
    rd = res["readiness"]
    a("## Release readiness")
    a("")
    a(
        f"Bar per class: at least {rd['min_test_recordings']} test recordings from at least {rd['min_test_observers']} distinct test observers. {rd['n_meeting_bar']} of {len(rd['classes'])} modeled classes meet it. Classes below the bar must stay disabled (or be shown as unvalidated) whatever their point estimates say."
    )
    a("")
    below = [lab for lab, v in rd["classes"].items() if not v["meets_bar"]]
    if below:
        a(
            "Below the bar: "
            + ", ".join(
                f"*{lab}* ({rd['classes'][lab]['test_recordings']} rec., {rd['classes'][lab]['test_observers']} obs.)"
                for lab in below
            )
            + "."
        )
        a("")
    a(
        f"Exported head: `{res['export']['path']}` (sha256 `{res['export']['sha256'][:16]}...`), arrays {', '.join(res['export']['arrays'])}. Window score = sigmoid(logit / temperature); the recording score is the max over windows, so the per-class thresholds also work as window-level floors."
    )
    a("")
    a("## Limits")
    a("")
    a(
        "* iNaturalist recordings are opportunistic, mostly close and loud, and labels are clip level. Field passive recordings are harder; these numbers are not field accuracy."
    )
    a(
        "* The observer split prevents one person's recordings from appearing in both train and test, but sites and regions may still overlap."
    )
    a(
        "* Window-level outputs exist (the head scores every 3 s window), but window-level accuracy cannot be measured without window labels."
    )
    a("")
    path.write_text("\n".join(L))


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--data", required=True, help="dataset folder (manifest.csv + birdnet_part_XX.npz)"
    )
    ap.add_argument(
        "--out", required=True, help="output folder for report, figures, results.json, head"
    )
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument(
        "--export-path",
        default=None,
        help="where to write the head (.npz); default <out>/frog_insect_head_v1.npz",
    )
    ap.add_argument("--report-name", default="frog_insect_v1.md")
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--train-frac", type=float, default=0.70)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--test-frac", type=float, default=0.15)
    ap.add_argument(
        "--rms-floor", type=float, default=-60.0, help="drop windows quieter than this (dBFS)"
    )
    ap.add_argument(
        "--top-k", type=int, default=3, help="stage-2 windows kept per positive recording"
    )
    ap.add_argument("--min-train-recordings", type=int, default=10)
    ap.add_argument("--min-test-recordings", type=int, default=10, help="release bar per class")
    ap.add_argument("--min-test-observers", type=int, default=3, help="release bar per class")
    ap.add_argument("--model", default="linear", choices=["linear", "mlp"])
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--expected-birdnet-sha256", default=None)
    return ap


def main(argv: list[str] | None = None) -> dict:
    return run(build_argparser().parse_args(argv))


if __name__ == "__main__":
    main()

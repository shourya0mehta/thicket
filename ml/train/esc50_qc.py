"""Soundscape QC / contamination head on BirdNET v2.4 embeddings, trained on ESC-50.

Stages (run in order, or ``all``):

  features  download ESC-50 (git sparse clone), decode to 48 kHz mono, cut 3 s
            windows with 1 s hop, run BirdNET v2.4 (logits + 1024-d
            embeddings), cache to ``<data>/features.npz``.
  postcheck Recompute the pooling and operating-point checks from saved fold
            models (``evaluate`` already runs them).
  evaluate  Experiment A (50-class linear probe, official 5-fold CV) and
            Experiment B (Thicket QC categories, multi-label head, 5-fold CV)
            with BirdNET zero-shot baselines, bootstrap CIs, calibration,
            confusion matrix and a long-recording pooling check.
  noise     Mix held-out bird / frog / insect clips with rain, wind and engine
            clips at fixed SNRs, re-embed, and measure flags and BirdNET decay.
  export    Train the final head on all 5 folds and write the pickle-free
            artifact ``backend/thicket/models/data/qc_head_v1.npz`` + ``.json``.
  smoke     Score one real 30 s field soundscape (backend test fixture).
  report    Write ``ml/reports/qc_esc50_v1.md`` and
            ``docs/model-cards/qc-soundscape-v1.md`` from the saved results.

Every number in the reports is read from ``ml/reports/qc_esc50_v1_results.json``,
which also stores the configuration used to produce it.

Usage:
    python ml/train/esc50_qc.py all --data /home/claude/data/esc50
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend"))

import evalkit as ek  # noqa: E402

ESC50_URL = "https://github.com/karolpiczak/ESC-50.git"
RESULTS = REPO / "ml" / "reports" / "qc_esc50_v1_results.json"
FIG_DIR = REPO / "ml" / "reports" / "figures"
ARTIFACT = REPO / "backend" / "thicket" / "models" / "data" / "qc_head_v1.npz"
CARD_JSON = ARTIFACT.with_suffix(".json")

HOP_SECONDS = 1.0
MIN_TAIL_SECONDS = 1.0
SEED = 20260924

# ESC-50 class -> Thicket QC category. Classes not listed are negatives for
# every category ("other"). Rationale is written into the report.
CATEGORY_MAP: dict[str, list[str]] = {
    "rain": ["rain"],
    "wind": ["wind"],
    "thunder": ["thunderstorm"],
    "water": ["sea_waves", "water_drops", "pouring_water", "toilet_flush"],
    "engine_machinery": [
        "engine",
        "train",
        "airplane",
        "helicopter",
        "chainsaw",
        "hand_saw",
        "vacuum_cleaner",
        "washing_machine",
        "siren",
        "car_horn",
    ],
    "human_nonspeech": [
        "crying_baby",
        "sneezing",
        "clapping",
        "breathing",
        "coughing",
        "footsteps",
        "laughing",
        "brushing_teeth",
        "snoring",
        "drinking_sipping",
    ],
    "domestic_animal": ["dog", "cat", "hen", "rooster", "cow", "pig", "sheep"],
    "bird": ["chirping_birds", "crow"],
    "insect": ["insects", "crickets"],
    "frog": ["frog"],
}
CATEGORIES = list(CATEGORY_MAP)
CATEGORY_KIND = {
    "rain": "geophony",
    "wind": "geophony",
    "thunder": "geophony",
    "water": "geophony",
    "engine_machinery": "anthropophony",
    "human_nonspeech": "anthropophony",
    "domestic_animal": "biophony_non_target",
    "bird": "biophony",
    "insect": "biophony",
    "frog": "biophony",
}
OTHER_CLASSES = [
    "crackling_fire",
    "church_bells",
    "fireworks",
    "door_wood_knock",
    "door_wood_creaks",
    "mouse_click",
    "keyboard_typing",
    "can_opening",
    "clock_alarm",
    "clock_tick",
    "glass_breaking",
]


# ============================================================ data + features


def ensure_esc50(data: Path) -> tuple[Path, str]:
    """Return (repo_dir, commit). Clones only meta/ and audio/ if missing."""
    repo = data / "repo"
    audio = repo / "audio"
    if not (audio.is_dir() and len(list(audio.glob("*.wav"))) == 2000):
        data.mkdir(parents=True, exist_ok=True)
        if not (repo / ".git").exists():
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    "--sparse",
                    ESC50_URL,
                    str(repo),
                ],
                check=True,
            )
        subprocess.run(
            ["git", "-C", str(repo), "sparse-checkout", "set", "meta", "audio"], check=True
        )
    n = len(list(audio.glob("*.wav")))
    if n != 2000:
        raise RuntimeError(f"ESC-50 audio incomplete: {n} files")
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, commit


def read_meta(repo: Path) -> list[dict]:
    with open(repo / "meta" / "esc50.csv") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: r["filename"])
    if len(rows) != 2000:
        raise RuntimeError("ESC-50 metadata should have 2000 rows")
    return rows


def window_rms_dbfs(x: np.ndarray, starts: np.ndarray, sr: int = 48000) -> np.ndarray:
    out = []
    for s in starts:
        a = int(round(s * sr))
        seg = x[a : a + 3 * sr].astype(np.float64)
        out.append(20 * np.log10(np.sqrt(np.mean(seg**2)) + 1e-9) if seg.size else -180.0)
    return np.asarray(out, dtype=np.float32)


def embed_audio(rt, x: np.ndarray, hop: float = HOP_SECONDS):
    from thicket.models.birdnet_runtime import frame_windows

    win, st = frame_windows(x, hop_seconds=hop, min_tail_seconds=MIN_TAIL_SECONDS)
    logits, emb = rt.infer(win)
    return emb, logits, st


def cmd_features(args: argparse.Namespace) -> None:
    from thicket.models.birdnet_runtime import BirdNETRuntime
    from thicket.services.audio_io import decode

    data = Path(args.data)
    out = data / "features.npz"
    if out.exists() and not args.force:
        print(f"[features] cached: {out}")
        return
    repo, commit = ensure_esc50(data)
    meta = read_meta(repo)
    rt = BirdNETRuntime(num_threads=args.threads)
    rt.load()
    embs, logits, clip_idx, starts, rms = [], [], [], [], []
    t0 = time.time()
    for i, row in enumerate(meta):
        x, sr = decode(repo / "audio" / row["filename"], target_sr=48000, mono=True)
        assert sr == 48000
        e, lg, st = embed_audio(rt, x)
        embs.append(e.astype(np.float32))
        logits.append(lg.astype(np.float16))
        clip_idx.append(np.full(len(st), i, dtype=np.int32))
        starts.append(st.astype(np.float32))
        rms.append(window_rms_dbfs(x, st))
        if (i + 1) % 200 == 0:
            el = time.time() - t0
            nw = sum(len(c) for c in clip_idx)
            print(
                f"[features] {i + 1}/2000 clips, {nw} windows, {el:.0f}s ({nw / el:.1f} win/s)",
                flush=True,
            )
    np.savez_compressed(
        out,
        embedding=np.concatenate(embs),
        logits=np.concatenate(logits),
        clip_index=np.concatenate(clip_idx),
        start_s=np.concatenate(starts),
        rms_dbfs=np.concatenate(rms),
        filename=np.array([r["filename"] for r in meta]),
        fold=np.array([int(r["fold"]) for r in meta], dtype=np.int16),
        target=np.array([int(r["target"]) for r in meta], dtype=np.int16),
        category=np.array([r["category"] for r in meta]),
        src_file=np.array([r["src_file"] for r in meta]),
        take=np.array([r["take"] for r in meta]),
        birdnet_labels=np.array([lab.raw for lab in rt.labels]),
        birdnet_taxa=np.array([lab.taxon for lab in rt.labels]),
        birdnet_sha256=np.array(rt.model_sha256),
        esc50_commit=np.array(commit),
        hop_seconds=np.array(HOP_SECONDS),
        min_tail_seconds=np.array(MIN_TAIL_SECONDS),
    )
    print(f"[features] wrote {out} in {time.time() - t0:.0f}s")


def load_features(data: Path) -> dict:
    z = np.load(Path(data) / "features.npz", allow_pickle=False)
    return {k: z[k] for k in z.files}


# ============================================================ shared pieces

BASELINE_TAXA = {"bird": "bird", "frog": "amphibian", "insect": "insect"}
BASELINE_LABELS = {
    "engine_machinery": ["Engine_Engine", "Siren_Siren"],
    "human_nonspeech": [
        "Human non-vocal_Human non-vocal",
        "Human vocal_Human vocal",
        "Human whistle_Human whistle",
    ],
    "domestic_animal": ["Dog_Dog"],
    "rain": ["Environmental_Environmental"],
    "wind": ["Environmental_Environmental"],
    "thunder": ["Environmental_Environmental"],
    "water": ["Environmental_Environmental"],
}
C_GRID_A = [0.001, 0.01, 0.1, 1.0]
C_GRID_B = [0.001, 0.003, 0.01, 0.03, 0.1, 0.3]
CONTAMINATION = [
    "rain",
    "wind",
    "thunder",
    "water",
    "engine_machinery",
    "human_nonspeech",
    "domestic_animal",
]


def pool_windows(e: np.ndarray) -> np.ndarray:
    """Clip feature = concat(mean over windows, max over windows): 2 x 1024."""
    e = np.asarray(e, dtype=np.float32)
    return np.concatenate([e.mean(axis=0), e.max(axis=0)])


def clip_bounds(F: dict) -> np.ndarray:
    return np.searchsorted(F["clip_index"], np.arange(len(F["filename"]) + 1))


def clip_features(F: dict, pick=None) -> np.ndarray:
    """Pooled clip features. ``pick(n_windows) -> indices`` selects windows."""
    bounds = clip_bounds(F)
    emb = F["embedding"]
    X = np.zeros((len(bounds) - 1, 2 * emb.shape[1]), np.float32)
    for c in range(len(bounds) - 1):
        e = emb[bounds[c] : bounds[c + 1]]
        if pick is not None:
            e = e[pick(len(e))]
        X[c] = pool_windows(e)
    return X


def check_label_set(esc_classes: np.ndarray) -> None:
    """Evaluation rule: the category map must cover the ESC-50 label set exactly."""
    mapped = [c for v in CATEGORY_MAP.values() for c in v]
    if len(mapped) != len(set(mapped)):
        raise RuntimeError("an ESC-50 class is mapped to two categories")
    if set(mapped) & set(OTHER_CLASSES):
        raise RuntimeError("a class is both mapped and 'other'")
    have = set(np.unique(esc_classes))
    want = set(mapped) | set(OTHER_CLASSES)
    if have != want or len(have) != 50:
        raise RuntimeError(f"label-set mismatch: missing {want - have}, unexpected {have - want}")


def category_targets(esc_classes: np.ndarray) -> np.ndarray:
    Y = np.zeros((len(esc_classes), len(CATEGORIES)), dtype=np.float64)
    for k, cat in enumerate(CATEGORIES):
        Y[:, k] = np.isin(esc_classes, CATEGORY_MAP[cat])
    return Y


def birdnet_clip_probs(F: dict) -> np.ndarray:
    """Per-clip max over windows of BirdNET sigmoid probabilities (n_clips, 6522)."""
    P = ek.sigmoid(F["logits"].astype(np.float32)).astype(np.float32)
    return np.maximum.reduceat(P, clip_bounds(F)[:-1], axis=0)


def birdnet_baseline(F: dict, Pc: np.ndarray) -> np.ndarray:
    labels = list(F["birdnet_labels"])
    taxa = F["birdnet_taxa"]
    S = np.zeros((Pc.shape[0], len(CATEGORIES)))
    for k, cat in enumerate(CATEGORIES):
        if cat in BASELINE_TAXA:
            S[:, k] = Pc[:, taxa == BASELINE_TAXA[cat]].max(axis=1)
        else:
            S[:, k] = Pc[:, [labels.index(lab) for lab in BASELINE_LABELS[cat]]].max(axis=1)
    return S


def macro_ap(Y: np.ndarray, S: np.ndarray) -> float:
    return float(np.nanmean([ek.safe_ap(Y[:, k], S[:, k]) for k in range(Y.shape[1])]))


def predict_logits(m: dict, X: np.ndarray) -> np.ndarray:
    return ((np.asarray(X, np.float64) - m["mean"]) / m["std"]) @ m["W"] + m["b"]


def predict_proba(m: dict, X: np.ndarray) -> np.ndarray:
    return ek.sigmoid(m["platt_a"] * predict_logits(m, X) + m["platt_b"])


def fit_head(
    X: np.ndarray, Y: np.ndarray, folds: np.ndarray, grid: list[float]
) -> tuple[dict, dict]:
    """Nested model selection on the given (training) folds only.

    Leave-one-fold-out over ``folds`` gives out-of-fold logits for each C; the
    C with the best macro AP is kept; Platt scaling and decision thresholds are
    fit on those out-of-fold predictions; the final weights are refit on all
    rows passed in.
    """
    from linear import Standardizer, fit_multilabel

    Z = {C: np.zeros(Y.shape) for C in grid}
    for j in sorted(set(folds.tolist())):
        itr, iva = folds != j, folds == j
        sc = Standardizer.fit(X[itr])
        Xa, Xv = sc(X[itr]), sc(X[iva])
        W = None
        for C in sorted(grid):
            W, b = fit_multilabel(Xa, Y[itr], C, W0=W)
            Z[C][iva] = Xv @ W + b
    scores = {C: macro_ap(Y, Z[C]) for C in grid}
    C = max(grid, key=lambda c: (round(scores[c], 6), -c))
    Zo = Z[C]
    platt = [ek.fit_platt(Zo[:, k], Y[:, k]) for k in range(Y.shape[1])]
    pa = np.array([p[0] for p in platt])
    pb = np.array([p[1] for p in platt])
    Po = ek.sigmoid(pa * Zo + pb)
    thr_f1 = np.array([ek.choose_threshold(Y[:, k], Po[:, k], "f1") for k in range(Y.shape[1])])
    thr_p90 = np.array(
        [ek.choose_threshold(Y[:, k], Po[:, k], "precision", 0.9) for k in range(Y.shape[1])]
    )
    sc = Standardizer.fit(X)
    W, b = fit_multilabel(sc(X), Y, C)
    model = {
        "mean": sc.mean,
        "std": sc.std,
        "W": W,
        "b": b,
        "platt_a": pa,
        "platt_b": pb,
        "thr_f1": thr_f1,
        "thr_p90": thr_p90,
        "C": np.array(C),
    }
    info = {"C": C, "inner_macro_ap": {str(c): v for c, v in scores.items()}, "oof_logits": Zo}
    return model, info


def update_results(section: str, payload: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    res = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    res[section] = payload
    RESULTS.write_text(json.dumps(res, indent=1, default=_json_default))


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def run_meta(F: dict) -> dict:
    import platform

    import scipy
    import sklearn

    return {
        "date": date.today().isoformat(),
        "birdnet_sha256": str(F["birdnet_sha256"]),
        "esc50_commit": str(F["esc50_commit"]),
        "window_seconds": 3.0,
        "hop_seconds": float(F["hop_seconds"]),
        "min_tail_seconds": float(F["min_tail_seconds"]),
        "n_clips": int(len(F["filename"])),
        "n_windows": int(len(F["clip_index"])),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "sklearn": sklearn.__version__,
        "seed": SEED,
    }


# ============================================================ Experiment A


def run_exp_a(X: np.ndarray, y: np.ndarray, folds: np.ndarray, classes: list[str]) -> dict:
    from linear import Standardizer, fit_softmax

    out = {"grid": C_GRID_A, "folds": {}}
    pred_all = np.zeros(len(y), dtype=int)
    for k in range(1, 6):
        t0 = time.time()
        tr, te = folds != k, folds == k
        inner = {C: [] for C in C_GRID_A}
        for j in sorted(set(folds[tr].tolist())):
            itr, iva = tr & (folds != j), folds == j
            sc = Standardizer.fit(X[itr])
            Xa, Xv = sc(X[itr]), sc(X[iva])
            for C in C_GRID_A:
                W, b = fit_softmax(Xa, y[itr], 50, C, max_iter=300)
                inner[C].append(float(np.mean(np.argmax(Xv @ W + b, 1) == y[iva])))
        C = max(C_GRID_A, key=lambda c: (round(float(np.mean(inner[c])), 6), -c))
        sc = Standardizer.fit(X[tr])
        W, b = fit_softmax(sc(X[tr]), y[tr], 50, C, max_iter=300)
        pred = np.argmax(sc(X[te]) @ W + b, 1)
        pred_all[te] = pred
        acc = float(np.mean(pred == y[te]))
        out["folds"][str(k)] = {
            "accuracy": acc,
            "C": C,
            "inner_accuracy": {str(c): float(np.mean(v)) for c, v in inner.items()},
        }
        print(f"[expA] fold {k}: acc={acc:.4f} C={C} ({time.time() - t0:.0f}s)", flush=True)
    accs = np.array([v["accuracy"] for v in out["folds"].values()])
    out["accuracy_mean"] = float(accs.mean())
    out["accuracy_std"] = float(accs.std(ddof=1))
    out["accuracy_std_ddof0"] = float(accs.std(ddof=0))
    per_class = {classes[c]: float(np.mean(pred_all[y == c] == c)) for c in range(50)}
    out["per_class_accuracy"] = per_class
    conf = {}
    for c in range(50):
        wrong = pred_all[(y == c) & (pred_all != c)]
        if len(wrong):
            vals, cnt = np.unique(wrong, return_counts=True)
            j = int(np.argmax(cnt))
            conf[classes[c]] = [classes[int(vals[j])], int(cnt[j])]
    out["most_common_confusion"] = conf
    return out


# ============================================================ Experiment B


def confusion_single_label(Y: np.ndarray, P: np.ndarray, D: np.ndarray) -> np.ndarray:
    K = Y.shape[1]
    t = np.where(Y.any(1), np.argmax(Y, 1), K)
    masked = np.where(D, P, -1.0)
    p = np.where(D.any(1), np.argmax(masked, 1), K)
    cm = np.zeros((K + 1, K + 1), dtype=int)
    np.add.at(cm, (t, p), 1)
    return cm


BACKEND_MIN_PROBABILITY = 0.5  # backend warns only when p > max(0.5, head threshold)


def decision_rules(m: dict) -> dict:
    """Operating points: F1 thresholds, strict (precision >= 0.9) thresholds,
    and the backend's rule p > max(0.5, F1 threshold)."""
    return {
        "f1": lambda p: p >= m["thr_f1"],
        "p90": lambda p: p >= m["thr_p90"],
        "backend": lambda p: p > np.maximum(BACKEND_MIN_PROBABILITY, m["thr_f1"]),
    }


POOLING_MODES = {"whole": None, "segment_max": 0.0, "segment_top25": 0.25, "segment_top50": 0.5}


def recording_scores(m: dict, E: np.ndarray, seg: int = 2) -> dict[str, np.ndarray]:
    """Recording-level probabilities under each pooling mode.

    ``segment_topQ`` is the k-th highest segment probability with
    k = max(1, ceil(Q * n_segments)): a category needs at least that share of
    segments above threshold (persistence). ``segment_max`` is k = 1.
    """
    out = {"whole": predict_proba(m, pool_windows(E)[None])[0]}
    feats = np.stack([pool_windows(E[i : i + seg]) for i in range(0, len(E), seg)])
    ps = -np.sort(-predict_proba(m, feats), axis=0)
    for name, q in POOLING_MODES.items():
        if q is not None:
            k = max(1, int(np.ceil(q * len(ps))))
            out[name] = ps[k - 1]
    return out


def run_pooling_check(F, Y, folds, models, n_per_cat: int = 30) -> dict:
    """Synthetic 'long recording' check without re-embedding.

    A synthetic recording is a sequence of test-fold clips; from each clip we
    take the windows starting at 0 s and 2 s (about a 3 s hop), so 6 clips
    give 12 windows (about 30 s). Contaminated recordings have 6 clips of
    which 1, 3 or 6 are contaminant clips of one category (short burst, half,
    whole recording). Clean recordings have 6 or 12 background clips (30 s or
    60 s). Two backgrounds: ``biophony`` (bird, insect and frog clips only,
    closest to a clean nature recording) and ``mixed`` (those plus ESC-50's
    negative classes such as bells, clocks and door knocks). Pooling modes
    are compared under each decision rule. The windows come from separate
    clips, not one continuous recording, so this is an approximation.
    """
    bounds = clip_bounds(F)
    emb = F["embedding"]
    ci = {c: CATEGORIES.index(c) for c in CONTAMINATION}
    cont_cols = [ci[c] for c in CONTAMINATION]
    bio = Y[:, [CATEGORIES.index(c) for c in ("bird", "insect", "frog")]].sum(1) > 0
    backgrounds = {"biophony": bio, "mixed": Y[:, cont_cols].sum(1) == 0}
    rules = ("f1", "p90", "backend")
    modes = list(POOLING_MODES)
    coverages = (1, 3, 6)
    lengths = (6, 12)

    def windows(clip: int) -> np.ndarray:
        e = emb[bounds[clip] : bounds[clip + 1]]
        return e[[0, min(2, len(e) - 1)]]

    out: dict = {
        "n_per_category_per_fold": n_per_cat,
        "segment_windows": 2,
        "coverages_of_6_clips": list(coverages),
        "clean_lengths_clips": list(lengths),
        "modes": modes,
        "backgrounds": {},
    }
    for bname, bmask in backgrounds.items():
        rng = np.random.default_rng(SEED + 7)
        det = {
            r: {cov: {c: {md: [] for md in modes} for c in CONTAMINATION} for cov in coverages}
            for r in rules
        }
        neg = {r: {ln: {md: [] for md in modes} for ln in lengths} for r in rules}
        for k in range(1, 6):
            m = models[k]
            dr = decision_rules(m)
            te = folds == k
            bg = np.flatnonzero(te & bmask)

            def score(clips, m=m):
                return recording_scores(m, np.concatenate([windows(c) for c in clips]))

            for cov in coverages:
                for c in CONTAMINATION:
                    cand = np.flatnonzero(te & (Y[:, ci[c]] > 0))
                    for _ in range(n_per_cat):
                        conts = list(rng.choice(cand, cov, replace=len(cand) < cov))
                        clips = list(rng.choice(bg, 6 - cov, replace=False))
                        for cc in conts:
                            clips.insert(int(rng.integers(0, len(clips) + 1)), int(cc))
                        sc = score(clips)
                        for r in rules:
                            for md in modes:
                                det[r][cov][c][md].append(bool(dr[r](sc[md])[ci[c]]))
            for ln in lengths:
                for _ in range(2 * n_per_cat):
                    sc = score(list(rng.choice(bg, ln, replace=False)))
                    for r in rules:
                        for md in modes:
                            neg[r][ln][md].append(dr[r](sc[md])[cont_cols])
        res: dict = {"rules": {}}
        for r in rules:
            rr: dict = {"detection_rate": {}, "false_flag_rate": {}}
            for cov in coverages:
                rr["detection_rate"][str(cov)] = {
                    c: {md: float(np.mean(det[r][cov][c][md])) for md in modes}
                    for c in CONTAMINATION
                }
                rr["detection_rate"][str(cov)]["mean_over_categories"] = {
                    md: float(np.mean([np.mean(det[r][cov][c][md]) for c in CONTAMINATION]))
                    for md in modes
                }
            for ln in lengths:
                rr["false_flag_rate"][str(ln)] = {}
                for md in modes:
                    arr = np.array(neg[r][ln][md])
                    d = {c: float(arr[:, j].mean()) for j, c in enumerate(CONTAMINATION)}
                    d["any_contamination"] = float(arr.any(1).mean())
                    rr["false_flag_rate"][str(ln)][md] = d
            res["rules"][r] = rr
        res["n_contaminated_per_category_and_coverage"] = 5 * n_per_cat
        res["n_clean_per_length"] = 5 * 2 * n_per_cat
        out["backgrounds"][bname] = res
    return out


def post_checks(F, Y, folds, groups, models, P, n_boot) -> dict:
    """Checks that only need the fold models and pooled test predictions."""
    D_backend = np.zeros(P.shape, bool)
    for k in range(1, 6):
        te = folds == k
        D_backend[te] = decision_rules(models[k])["backend"](P[te])
    bio_rows = Y[:, [CATEGORIES.index(c) for c in ("bird", "insect", "frog")]].sum(1) > 0
    cont_cols = [CATEGORIES.index(c) for c in CONTAMINATION]
    D_f1 = np.zeros(P.shape, bool)
    for k in range(1, 6):
        te = folds == k
        D_f1[te] = decision_rules(models[k])["f1"](P[te])
    Pc = birdnet_clip_probs(F)
    bird_max = Pc[:, F["birdnet_taxa"] == "bird"].max(1)
    fowl = np.isin(F["category"], ["hen", "rooster"])
    return {
        "birdnet_bird_label_on_hen_rooster": {
            "at_0.5": ek.wilson(int((bird_max[fowl] >= 0.5).sum()), int(fowl.sum())),
            "at_0.1": ek.wilson(int((bird_max[fowl] >= 0.1).sum()), int(fowl.sum())),
        },
        "head_at_backend_rule": ek.per_class_table(
            Y, P, D_backend, CATEGORIES, groups, n_boot, SEED
        ),
        "clean_biophony_clip_flags_by_category_backend": {
            c: int(D_backend[bio_rows][:, CATEGORIES.index(c)].sum()) for c in CONTAMINATION
        },
        "clean_biophony_clip_false_contamination_flag": {
            "f1": ek.wilson(int(D_f1[bio_rows][:, cont_cols].any(1).sum()), int(bio_rows.sum())),
            "backend": ek.wilson(
                int(D_backend[bio_rows][:, cont_cols].any(1).sum()), int(bio_rows.sum())
            ),
        },
        "pooling_check": run_pooling_check(F, Y, folds, models),
    }


def run_exp_b(
    F: dict,
    X: np.ndarray,
    Y: np.ndarray,
    folds: np.ndarray,
    groups: np.ndarray,
    base: np.ndarray,
    n_boot: int,
) -> tuple[dict, dict, dict]:
    n, K = Y.shape
    P = np.zeros((n, K))
    Zraw = np.zeros((n, K))
    D_f1 = np.zeros((n, K), bool)
    D_p90 = np.zeros((n, K), bool)
    D_base = np.zeros((n, K), bool)
    X1 = clip_features(F, pick=lambda nw: [0])
    P1 = np.zeros((n, K))
    D1 = np.zeros((n, K), bool)
    models: dict[int, dict] = {}
    folds_out = {}
    for k in range(1, 6):
        t0 = time.time()
        tr, te = folds != k, folds == k
        m, info = fit_head(X[tr], Y[tr], folds[tr], C_GRID_B)
        models[k] = m
        Zraw[te] = predict_logits(m, X[te])
        P[te] = ek.sigmoid(m["platt_a"] * Zraw[te] + m["platt_b"])
        D_f1[te] = P[te] >= m["thr_f1"]
        D_p90[te] = P[te] >= m["thr_p90"]
        thr_b = np.array([ek.choose_threshold(Y[tr, j], base[tr, j], "f1") for j in range(K)])
        D_base[te] = base[te] >= thr_b
        P1[te] = predict_proba(m, X1[te])
        D1[te] = P1[te] >= m["thr_f1"]
        folds_out[str(k)] = {
            "C": info["C"],
            "inner_macro_ap": info["inner_macro_ap"],
            "thresholds_f1": dict(zip(CATEGORIES, m["thr_f1"].tolist(), strict=True)),
            "thresholds_p90": dict(zip(CATEGORIES, m["thr_p90"].tolist(), strict=True)),
            "baseline_thresholds_f1": dict(zip(CATEGORIES, thr_b.tolist(), strict=True)),
            "test_macro_ap": macro_ap(Y[te], P[te]),
            "test_macro_ap_baseline": macro_ap(Y[te], base[te]),
        }
        print(
            f"[expB] fold {k}: C={info['C']} macroAP={folds_out[str(k)]['test_macro_ap']:.4f} ({time.time() - t0:.0f}s)",
            flush=True,
        )

    t0 = time.time()
    res: dict = {"grid": C_GRID_B, "folds": folds_out}
    res["head_at_f1_thresholds"] = ek.per_class_table(Y, P, D_f1, CATEGORIES, groups, n_boot, SEED)
    res["head_at_p90_thresholds"] = ek.per_class_table(
        Y, P, D_p90, CATEGORIES, groups, n_boot, SEED
    )
    res["birdnet_baseline"] = ek.per_class_table(Y, base, D_base, CATEGORIES, groups, n_boot, SEED)
    res["head_single_window"] = ek.per_class_table(Y, P1, D1, CATEGORIES, groups, n_boot, SEED)
    print(f"[expB] bootstrap tables {time.time() - t0:.0f}s", flush=True)
    res["ap_difference_head_minus_baseline"] = {
        c: ek.cluster_bootstrap(
            lambda i, k=k: ek.safe_ap(Y[i, k], P[i, k]) - ek.safe_ap(Y[i, k], base[i, k]),
            groups,
            n_boot,
            SEED + 500 + k,
        )
        for k, c in enumerate(CATEGORIES)
    }
    fm = np.array([v["test_macro_ap"] for v in folds_out.values()])
    res["per_fold_macro_ap"] = {"mean": float(fm.mean()), "std": float(fm.std(ddof=1))}
    res["reliability_calibrated"] = ek.reliability(Y, P)
    res["reliability_raw"] = ek.reliability(Y, ek.sigmoid(Zraw))
    res["ece_per_category"] = {
        c: {
            "raw": ek.reliability(Y[:, k], ek.sigmoid(Zraw[:, k]))["ece"],
            "calibrated": ek.reliability(Y[:, k], P[:, k])["ece"],
        }
        for k, c in enumerate(CATEGORIES)
    }
    cm = confusion_single_label(Y, P, D_f1)
    res["confusion_single_label"] = {"labels": CATEGORIES + ["other"], "matrix": cm.tolist()}
    res["single_label_accuracy"] = float(np.trace(cm) / cm.sum())
    # Where do false flags come from? (ESC-50 class -> flagged foreign categories)
    esc = F["category"]
    ff = {}
    for cls in np.unique(esc):
        rows = esc == cls
        own = Y[rows][0] > 0
        counts = D_f1[rows][:, ~own].sum(0)
        names = [c for c, o in zip(CATEGORIES, own, strict=True) if not o]
        top = sorted(zip(names, counts.tolist(), strict=True), key=lambda t: -t[1])
        ff[str(cls)] = {
            "n_clips": int(rows.sum()),
            "clips_with_foreign_flag": int(D_f1[rows][:, ~own].any(1).sum()),
            "top": [t for t in top if t[1] > 0][:3],
        }
    res["false_flags_by_esc_class"] = ff
    other = np.isin(esc, OTHER_CLASSES)
    res["other_classes_any_flag_rate"] = float(D_f1[other].any(1).mean())
    t0 = time.time()
    res.update(post_checks(F, Y, folds, groups, models, P, n_boot))
    print(f"[expB] post checks {time.time() - t0:.0f}s", flush=True)
    preds = {"P": P, "Zraw": Zraw, "D_f1": D_f1, "base": base, "D_base": D_base, "Y": Y}
    return res, models, preds


# ============================================================ figures


def fig_ap(res: dict, path: Path) -> None:
    from plotstyle import BLUE, ORANGE, TEXT_2, plt

    head = res["head_at_f1_thresholds"]["per_class"]
    base = res["birdnet_baseline"]["per_class"]
    cats = CATEGORIES[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    y = np.arange(len(cats))
    for off, tab, col, lab in (
        (0.17, head, BLUE, "Thicket QC head (trained)"),
        (-0.17, base, ORANGE, "BirdNET zero-shot label(s)"),
    ):
        pts = np.array([tab[c]["ap"] for c in cats])
        ax.errorbar(
            pts[:, 0],
            y + off,
            xerr=[pts[:, 0] - pts[:, 1], pts[:, 2] - pts[:, 0]],
            fmt="o",
            color=col,
            ms=6,
            elinewidth=1.6,
            capsize=0,
            label=lab,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(
        [c + (" *" if c in ("rain", "wind", "thunder", "water") else "") for c in cats]
    )
    ax.set_xlim(0, 1.02)
    ax.set_xlabel("Average precision (95% CI, cluster bootstrap over source recordings)")
    ax.set_title("ESC-50, 5-fold CV: per-category average precision", pad=30)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9)
    ax.text(
        0,
        -0.16,
        "* BirdNET has no rain, wind, thunder or water label; its generic 'Environmental' label is shown.",
        transform=ax.transAxes,
        fontsize=8,
        color=TEXT_2,
    )
    fig.savefig(path)
    plt.close(fig)


def fig_confusion(res: dict, path: Path) -> None:
    from plotstyle import SEQ_CMAP, TEXT, plt

    cm = np.array(res["confusion_single_label"]["matrix"], dtype=float)
    labels = res["confusion_single_label"]["labels"]
    norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(7.6, 6.6))
    ax.grid(False)
    im = ax.imshow(norm, cmap=SEQ_CMAP, vmin=0, vmax=1)
    for i in range(len(labels)):
        for j in range(len(labels)):
            if cm[i, j] > 0:
                ax.text(
                    j,
                    i,
                    int(cm[i, j]),
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white" if norm[i, j] > 0.55 else TEXT,
                )
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted (highest calibrated score above its threshold; else 'other')")
    ax.set_ylabel("True category")
    ax.set_title("Single-label view, pooled over 5 test folds (counts; color = row share)")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("Share of true row")
    fig.savefig(path)
    plt.close(fig)


def fig_reliability(res: dict, path: Path) -> None:
    from plotstyle import BLUE, NEUTRAL, ORANGE, plt

    fig, (ax, axh) = plt.subplots(2, 1, figsize=(5.6, 6.2), height_ratios=[3, 1], sharex=True)
    ax.plot([0, 1], [0, 1], ls="--", color=NEUTRAL, lw=1.2, label="Perfect calibration")
    for key, col, lab in (
        ("reliability_raw", ORANGE, "Raw logistic output"),
        ("reliability_calibrated", BLUE, "After Platt scaling"),
    ):
        r = res[key]
        c = np.array(r["confidence"], dtype=float)
        a = np.array(r["accuracy"], dtype=float)
        ok = np.isfinite(c)
        ax.plot(c[ok], a[ok], marker="o", ms=5, color=col, label=f"{lab} (ECE {r['ece']:.3f})")
    ax.set_ylabel("Observed positive rate")
    ax.set_title("Reliability, all category-clip pairs (10 bins)")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    r = res["reliability_calibrated"]
    edges = np.array(r["edges"])
    axh.bar((edges[:-1] + edges[1:]) / 2, np.maximum(r["count"], 1), width=0.09, color=BLUE)
    axh.set_yscale("log")
    axh.set_ylabel("Pairs per bin")
    axh.set_xlabel("Predicted probability (calibrated bins)")
    fig.savefig(path)
    plt.close(fig)


def fig_pr(preds: dict, path: Path) -> None:
    from plotstyle import BLUE, ORANGE, plt

    Y, P, B = preds["Y"], preds["P"], preds["base"]
    fig, axes = plt.subplots(2, 5, figsize=(13, 5.6), sharex=True, sharey=True)
    for k, (cat, ax) in enumerate(zip(CATEGORIES, axes.ravel(), strict=True)):
        for S, col, lab in ((P, BLUE, "QC head"), (B, ORANGE, "BirdNET label(s)")):
            order = np.argsort(-S[:, k], kind="stable")
            y = Y[order, k]
            tp = np.cumsum(y)
            prec = tp / np.arange(1, len(y) + 1)
            rec = tp / max(y.sum(), 1)
            ax.plot(rec, prec, color=col, lw=1.8, label=lab)
        ax.set_title(cat, fontsize=10)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
    for ax in axes[1]:
        ax.set_xlabel("Recall")
    for ax in axes[:, 0]:
        ax.set_ylabel("Precision")
    axes[0, 0].legend(loc="lower left", fontsize=8)
    fig.suptitle(
        "Precision-recall curves, ESC-50 5-fold CV (pooled test folds)",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ============================================================ stages


def load_all(args) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    F = load_features(Path(args.data))
    check_label_set(F["category"])
    X = clip_features(F)
    Y = category_targets(F["category"])
    folds = F["fold"].astype(int)
    groups = F["src_file"]
    return F, X, Y, folds, groups


def cmd_evaluate(args: argparse.Namespace) -> None:
    t_start = time.time()
    F, X, Y, folds, groups = load_all(args)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    update_results(
        "meta",
        run_meta(F)
        | {
            "category_map": CATEGORY_MAP,
            "category_kind": CATEGORY_KIND,
            "other_classes": OTHER_CLASSES,
            "baseline_taxa": BASELINE_TAXA,
            "baseline_labels": BASELINE_LABELS,
            "n_boot": args.n_boot,
            "n_source_recordings": int(len(np.unique(groups))),
            "pooling": "concat(mean, max) over 3 s windows, 1 s hop (3 windows per 5 s clip)",
        },
    )
    if not args.skip_a:
        classes = [str(F["category"][F["target"] == c][0]) for c in range(50)]
        t0 = time.time()
        resA = run_exp_a(X, F["target"].astype(int), folds, classes)
        resA["seconds"] = round(time.time() - t0, 1)
        update_results("experiment_a", resA)
        print(f"[expA] accuracy {resA['accuracy_mean']:.4f} +- {resA['accuracy_std']:.4f}")
    Pc = birdnet_clip_probs(F)
    base = birdnet_baseline(F, Pc)
    t0 = time.time()
    resB, models, preds = run_exp_b(F, X, Y, folds, groups, base, args.n_boot)
    resB["seconds"] = round(time.time() - t0, 1)
    update_results("experiment_b", resB)
    np.savez_compressed(
        Path(args.data) / "fold_models.npz",
        **{f"f{k}_{name}": v for k, m in models.items() for name, v in m.items()},
    )
    np.savez_compressed(Path(args.data) / "expB_predictions.npz", **preds)
    fig_ap(resB, FIG_DIR / "qc_ap_by_category.png")
    fig_confusion(resB, FIG_DIR / "qc_confusion.png")
    fig_reliability(resB, FIG_DIR / "qc_reliability.png")
    fig_pr(preds, FIG_DIR / "qc_pr_curves.png")
    print(f"[evaluate] done in {time.time() - t_start:.0f}s")


def cmd_postcheck(args: argparse.Namespace) -> None:
    """Recompute ``post_checks`` from saved fold models and predictions
    (identical to what ``evaluate`` computes at its end)."""
    F, X, Y, folds, groups = load_all(args)
    models = load_fold_models(Path(args.data))
    preds = np.load(Path(args.data) / "expB_predictions.npz", allow_pickle=False)
    if not np.array_equal(preds["Y"], Y):
        raise RuntimeError("saved predictions do not match the current label mapping")
    res = json.loads(RESULTS.read_text())
    B = res["experiment_b"]
    B.update(post_checks(F, Y, folds, groups, models, preds["P"], args.n_boot))
    update_results("experiment_b", B)
    fig_ap(B, FIG_DIR / "qc_ap_by_category.png")
    print("[postcheck] updated experiment_b")


def load_fold_models(data: Path) -> dict[int, dict]:
    z = np.load(data / "fold_models.npz", allow_pickle=False)
    models: dict[int, dict] = {}
    for key in z.files:
        f, name = key.split("_", 1)
        models.setdefault(int(f[1:]), {})[name] = z[key]
    return models


# ============================================================ noise robustness

NOISE_TARGETS = {
    "chirping_birds": "bird",
    "crow": "bird",
    "frog": "frog",
    "insects": "insect",
    "crickets": "insect",
}
NOISE_CONTAMINANTS = {
    "rain": ("rain", "rain"),
    "wind": ("wind", "wind"),
    "engine": ("engine", "engine_machinery"),
}
SNRS = [10.0, 0.0, -10.0]
BIRDNET_REPORT_THRESHOLD = 0.6  # product default decision threshold (spec section 6)


def active_rms(x: np.ndarray, sr: int = 48000, frame_s: float = 0.05) -> float:
    """RMS over 50 ms frames that are not digital silence (ESC-50 pads with zeros)."""
    n = int(sr * frame_s)
    m = len(x) // n
    fr = x[: m * n].astype(np.float64).reshape(m, n)
    e = np.sqrt((fr**2).mean(1))
    act = e > 1e-4
    if not act.any():
        return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)
    return float(np.sqrt((fr[act] ** 2).mean()))


def mix_at_snr(signal: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    noise = np.resize(noise, len(signal))
    g = active_rms(signal) / (active_rms(noise) * 10 ** (snr_db / 20))
    out = signal.astype(np.float64) + g * noise
    peak = np.abs(out).max()
    if peak > 0.99:  # rescale the whole mixture; the SNR is unchanged
        out *= 0.99 / peak
    return out.astype(np.float32)


def cmd_noise(args: argparse.Namespace) -> None:
    from thicket.models.birdnet_runtime import BirdNETRuntime
    from thicket.services.audio_io import decode

    t_start = time.time()
    data = Path(args.data)
    F, X, Y, folds, groups = load_all(args)
    models = load_fold_models(data)
    rt = BirdNETRuntime(num_threads=args.threads)
    rt.load()
    if rt.model_sha256 != str(F["birdnet_sha256"]):
        raise RuntimeError("BirdNET weights differ from the ones used for the cached features")
    taxa = np.array([lab.taxon for lab in rt.labels])
    masks = {"bird": taxa == "bird", "frog": taxa == "amphibian", "insect": taxa == "insect"}
    esc = F["category"]
    Pc = birdnet_clip_probs(F)
    repo = data / "repo"
    cache: dict[int, np.ndarray] = {}

    def dec(i: int) -> np.ndarray:
        if i not in cache:
            cache[i] = decode(repo / "audio" / str(F["filename"][i]), target_sr=48000)[0]
        return cache[i]

    rng = np.random.default_rng(SEED + 11)
    cont_idx = [CATEGORIES.index(c) for c in CONTAMINATION]
    recs: list[dict] = []
    use_folds = [int(f) for f in args.noise_folds.split(",")]
    for k in use_folds:
        m = models[k]
        thr = m["thr_f1"]
        te = folds == k
        for i in [i for i in np.flatnonzero(te) if esc[i] in NOISE_TARGETS]:
            tcat = NOISE_TARGETS[str(esc[i])]
            tk = CATEGORIES.index(tcat)
            P = predict_proba(m, X[i : i + 1])[0]
            recs.append(
                {
                    "fold": k,
                    "clip": int(i),
                    "target": tcat,
                    "contaminant": "none",
                    "snr_db": None,
                    "target_flag": bool(P[tk] >= thr[tk]),
                    "flags": {
                        c: bool(P[CATEGORIES.index(c)] >= thr[CATEGORIES.index(c)])
                        for c in CONTAMINATION
                    },
                    "birdnet_taxon_max": float(Pc[i, masks[tcat]].max()),
                }
            )
            s = dec(i)
            for cname, (cls, ccat) in NOISE_CONTAMINANTS.items():
                j = int(rng.choice(np.flatnonzero(te & (esc == cls))))
                noise = dec(j)
                for snr in SNRS:
                    emb, logits, _ = embed_audio(rt, mix_at_snr(s, noise, snr))
                    P = predict_proba(m, pool_windows(emb)[None])[0]
                    probs = ek.sigmoid(logits)
                    recs.append(
                        {
                            "fold": k,
                            "clip": int(i),
                            "target": tcat,
                            "contaminant": cname,
                            "noise_clip": j,
                            "snr_db": snr,
                            "contaminant_category": ccat,
                            "contaminant_flag": bool(
                                P[CATEGORIES.index(ccat)] >= thr[CATEGORIES.index(ccat)]
                            ),
                            "target_flag": bool(P[tk] >= thr[tk]),
                            "any_contamination_flag": bool((P[cont_idx] >= thr[cont_idx]).any()),
                            "birdnet_taxon_max": float(probs[:, masks[tcat]].max()),
                        }
                    )
        print(
            f"[noise] fold {k} done, {len(recs)} records, {time.time() - t_start:.0f}s", flush=True
        )

    clean = [r for r in recs if r["contaminant"] == "none"]
    out: dict = {
        "config": {
            "folds": use_folds,
            "snr_db": SNRS,
            "targets": NOISE_TARGETS,
            "contaminants": {k: v[0] for k, v in NOISE_CONTAMINANTS.items()},
            "snr_definition": "active RMS (50 ms frames above -80 dBFS) of target vs contaminant, whole 5 s clip",
            "birdnet_threshold": BIRDNET_REPORT_THRESHOLD,
            "head": "fold model trained without the test fold; F1 thresholds from training folds",
        },
        "n_target_clips": len(clean),
        "clean": {
            "target_flag_rate": ek.wilson(sum(r["target_flag"] for r in clean), len(clean)),
            "false_flag_rate": {
                c: ek.wilson(sum(r["flags"][c] for r in clean), len(clean)) for c in CONTAMINATION
            },
            "birdnet_median": {
                t: float(np.median([r["birdnet_taxon_max"] for r in clean if r["target"] == t]))
                for t in ("bird", "frog", "insect")
            },
            "birdnet_rate_at_threshold": {
                t: ek.wilson(
                    sum(
                        r["birdnet_taxon_max"] >= BIRDNET_REPORT_THRESHOLD
                        for r in clean
                        if r["target"] == t
                    ),
                    sum(r["target"] == t for r in clean),
                )
                for t in ("bird", "frog", "insect")
            },
        },
        "mixed": {},
    }
    for cname in NOISE_CONTAMINANTS:
        for snr in SNRS:
            rs = [r for r in recs if r["contaminant"] == cname and r["snr_db"] == snr]
            out["mixed"][f"{cname}@{snr:+.0f}dB"] = {
                "contaminant": cname,
                "snr_db": snr,
                "n": len(rs),
                "contaminant_flag_rate": ek.wilson(sum(r["contaminant_flag"] for r in rs), len(rs)),
                "any_contamination_flag_rate": ek.wilson(
                    sum(r["any_contamination_flag"] for r in rs), len(rs)
                ),
                "target_flag_rate": ek.wilson(sum(r["target_flag"] for r in rs), len(rs)),
                "birdnet_median": {
                    t: float(np.median([r["birdnet_taxon_max"] for r in rs if r["target"] == t]))
                    for t in ("bird", "frog", "insect")
                },
                "birdnet_rate_at_threshold": {
                    t: ek.wilson(
                        sum(
                            r["birdnet_taxon_max"] >= BIRDNET_REPORT_THRESHOLD
                            for r in rs
                            if r["target"] == t
                        ),
                        sum(r["target"] == t for r in rs),
                    )
                    for t in ("bird", "frog", "insect")
                },
            }
    out["seconds"] = round(time.time() - t_start, 1)
    out["n_mixtures"] = len(recs) - len(clean)
    update_results("noise_robustness", out)
    fig_noise(out, FIG_DIR / "qc_noise_robustness.png")
    print(f"[noise] done in {out['seconds']:.0f}s")


def fig_noise(out: dict, path: Path) -> None:
    from plotstyle import AQUA, BLUE, NEUTRAL, ORANGE, plt

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
    cols = {"rain": BLUE, "wind": ORANGE, "engine": AQUA}
    xs = ["clean"] + [f"{s:+.0f} dB" for s in SNRS]
    panels = [
        ("contaminant_flag_rate", "Head flags the added contaminant"),
        ("target_flag_rate", "Head still flags bird / frog / insect"),
        (
            "birdnet_rate_at_threshold",
            f"BirdNET matching-taxon label >= {BIRDNET_REPORT_THRESHOLD} (all taxa)",
        ),
    ]
    for ax, (key, title) in zip(axes, panels, strict=True):
        for cname in NOISE_CONTAMINANTS:
            ccat = NOISE_CONTAMINANTS[cname][1]
            if key == "contaminant_flag_rate":
                first = out["clean"]["false_flag_rate"][ccat]
            elif key == "target_flag_rate":
                first = out["clean"]["target_flag_rate"]
            else:
                first = _pool_wilson(out["clean"]["birdnet_rate_at_threshold"])
            vals = [first]
            for snr in SNRS:
                v = out["mixed"][f"{cname}@{snr:+.0f}dB"][key]
                vals.append(_pool_wilson(v) if key == "birdnet_rate_at_threshold" else v)
            y = np.array([v[0] for v in vals])
            lo = np.array([v[1] for v in vals])
            hi = np.array([v[2] for v in vals])
            x = np.arange(len(xs))
            ax.fill_between(x, lo, hi, color=cols[cname], alpha=0.12, lw=0)
            ax.plot(x, y, marker="o", ms=6, color=cols[cname], label=cname)
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels(xs)
        ax.set_ylim(0, 1.02)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Target-to-contaminant SNR")
        ax.axvline(0.5, color=NEUTRAL, lw=0.8, ls=":")
    axes[0].set_ylabel("Share of target clips (95% Wilson CI)")
    axes[0].legend(title="Added contaminant", fontsize=9, loc="center left")
    fig.suptitle(
        f"Noise stress test: {out['n_target_clips']} held-out ESC-50 bird, frog and insect clips",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _pool_wilson(d: dict) -> list[float]:
    """Pool per-taxon Wilson entries {taxon: [p, lo, hi, k, n]} into one."""
    k = sum(v[3] for v in d.values())
    n = sum(v[4] for v in d.values())
    return ek.wilson(k, n)


# ============================================================ export


# Chosen from the synthetic pooling check (see report): persistence over at
# least a quarter of the segments. This is a design choice made after seeing
# test-fold results, disclosed as such in the report.
RECORDING_POOLING = "segment_quantile"
SEGMENT_WINDOWS = 2
SEGMENT_QUANTILE = 0.25


def cmd_export(args: argparse.Namespace) -> None:
    import hashlib

    F, X, Y, folds, groups = load_all(args)
    m, info = fit_head(X, Y, folds, C_GRID_B)
    Zo = info["oof_logits"]
    Po = ek.sigmoid(m["platt_a"] * Zo + m["platt_b"])
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    f32 = np.float32
    arrays = {
        "format": np.array("thicket-qc-head/1"),
        "version": np.array("qc_head_v1"),
        "categories": np.array(CATEGORIES),
        "category_kind": np.array([CATEGORY_KIND[c] for c in CATEGORIES]),
        "pooling": np.array("mean_max"),
        "recording_pooling": np.array(RECORDING_POOLING),
        "segment_windows": np.array(SEGMENT_WINDOWS, dtype=np.int32),
        "segment_quantile": np.array(SEGMENT_QUANTILE, dtype=f32),
        "embedding_dim": np.array(1024, dtype=np.int32),
        "feature_mean": m["mean"].astype(f32),
        "feature_std": m["std"].astype(f32),
        "W": m["W"].astype(f32),
        "b": m["b"].astype(f32),
        "platt_a": m["platt_a"].astype(f32),
        "platt_b": m["platt_b"].astype(f32),
        "thresholds": m["thr_f1"].astype(f32),
        "thresholds_high_precision": m["thr_p90"].astype(f32),
        "birdnet_model": np.array("BirdNET GLOBAL 6K V2.4 FP32 TFLite"),
        "birdnet_sha256": np.array(str(F["birdnet_sha256"])),
        "window_seconds": np.array(3.0, dtype=f32),
        "train_hop_seconds": np.array(HOP_SECONDS, dtype=f32),
        "created": np.array(date.today().isoformat()),
        "license": np.array("CC BY-NC-SA 4.0"),
    }
    np.savez_compressed(ARTIFACT, **arrays)
    sha = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()

    # Parity check: the backend loader must reproduce the training-side numbers.
    from thicket.models.qc_head import QCHead

    head = QCHead.load(ARTIFACT)
    bounds = clip_bounds(F)
    ref = ek.sigmoid(m["platt_a"] * predict_logits(m, X) + m["platt_b"])
    diffs = []
    for c in range(0, len(bounds) - 1, 7):
        got = head.predict_array(F["embedding"][bounds[c] : bounds[c + 1]], mode="whole")
        diffs.append(float(np.abs(got - ref[c]).max()))
    rng = np.random.default_rng(SEED)
    for _ in range(20):  # recording-level pooling parity on random 12-window stacks
        E = F["embedding"][rng.choice(len(F["embedding"]), 12, replace=False)]
        want = recording_scores(m, E)[f"segment_top{int(SEGMENT_QUANTILE * 100)}"]
        diffs.append(float(np.abs(head.predict_array(E) - want).max()))
    parity = max(diffs)
    if parity > 1e-4:
        raise RuntimeError(f"backend parity check failed: {parity}")

    res = json.loads(RESULTS.read_text())
    export = {
        "created": date.today().isoformat(),
        "artifact": str(ARTIFACT.relative_to(REPO)),
        "artifact_sha256": sha,
        "artifact_bytes": ARTIFACT.stat().st_size,
        "C": info["C"],
        "cv_macro_ap_by_C": info["inner_macro_ap"],
        "oof_macro_ap_all_folds": macro_ap(Y, Po),
        "oof_note": "Out-of-fold predictions of the 5-fold CV used to pick C, Platt parameters and thresholds for the exported model; optimistic because C was selected on them. The unbiased estimate is experiment_b (nested).",
        "thresholds_f1": dict(zip(CATEGORIES, m["thr_f1"].round(4).tolist(), strict=True)),
        "thresholds_p90": dict(zip(CATEGORIES, m["thr_p90"].round(4).tolist(), strict=True)),
        "platt": {
            c: [float(a), float(b)]
            for c, a, b in zip(CATEGORIES, m["platt_a"], m["platt_b"], strict=True)
        },
        "recording_pooling": RECORDING_POOLING,
        "segment_windows": SEGMENT_WINDOWS,
        "segment_quantile": SEGMENT_QUANTILE,
        "backend_parity_max_abs_diff": parity,
    }
    update_results("export", export)
    write_card_json(res | {"export": export})
    print(
        f"[export] wrote {ARTIFACT} ({export['artifact_bytes']} bytes, C={info['C']}, parity {parity:.2e})"
    )


def write_card_json(res: dict) -> None:
    """Machine-readable model card next to the artifact (reads results only)."""
    B = res["experiment_b"]
    head = B["head_at_f1_thresholds"]
    meta = res["meta"]
    pcb = B["pooling_check"]["backgrounds"]["biophony"]["rules"]["backend"]

    def trip(t):
        return [round(float(v), 4) for v in t]

    card = {
        "name": "Thicket soundscape QC head",
        "version": "qc_head_v1",
        "created": res["export"].get("created", meta["date"]),
        "status": "experimental; warnings only; not validated on field recordings",
        "artifact": "qc_head_v1.npz",
        "artifact_sha256": res["export"]["artifact_sha256"],
        "model_card": "docs/model-cards/qc-soundscape-v1.md",
        "report": "ml/reports/qc_esc50_v1.md",
        "intended_use": "Flag likely contamination (rain, wind, thunder, water, engines and machinery, human non-speech sounds, domestic animals) and non-target sound sources in field audio, as warnings next to BirdNET results. Not a species classifier and not a detector of weather events. The bird, insect and frog scores are for internal diagnostics only until validated on field audio.",
        "warning_rule_used_by_backend": "score > max(0.5, thresholds[category]) for categories whose kind is geophony, anthropophony or biophony_non_target",
        "inputs": "BirdNET v2.4 1024-d embeddings of 3 s windows at 48 kHz (thicket.models.birdnet_runtime.BirdNETRuntime.infer).",
        "pooling": "concat(mean, max) over the windows of a segment (2 windows); recording score per category = k-th highest segment probability, k = max(1, ceil(0.25 * n_segments)) (recording_pooling=segment_quantile). predict_segments gives per-segment scores.",
        "categories": {
            c: {"kind": CATEGORY_KIND[c], "esc50_classes": CATEGORY_MAP[c]} for c in CATEGORIES
        },
        "negative_esc50_classes": OTHER_CLASSES,
        "thresholds": res["export"]["thresholds_f1"],
        "thresholds_high_precision": res["export"]["thresholds_p90"],
        "backbone": {
            "name": "BirdNET GLOBAL 6K V2.4 (FP32 TFLite)",
            "sha256": meta["birdnet_sha256"],
            "license": "CC BY-NC-SA 4.0",
        },
        "training_data": {
            "name": "ESC-50",
            "url": "https://github.com/karolpiczak/ESC-50",
            "commit": meta["esc50_commit"],
            "license": "CC BY-NC 3.0 (dataset as a whole)",
            "clips": 2000,
            "notes": "Curated 5 s Freesound clips, not passive field recordings.",
        },
        "evaluation": {
            "protocol": "ESC-50 official 5 folds; hyperparameters, Platt scaling and thresholds chosen on training folds only; metrics pooled over test folds; 95% CIs by cluster bootstrap over source recordings",
            "macro": {k: trip(v) for k, v in head["macro"].items()},
            "micro": {k: trip(v) for k, v in head["micro"].items()},
            "per_category": {
                c: {
                    m: trip(head["per_class"][c][m])
                    for m in ("precision", "recall", "f1", "ap", "auc")
                }
                for c in CATEGORIES
            },
            "ece_calibrated": round(B["reliability_calibrated"]["ece"], 4),
            "macro_at_backend_rule": {
                k: trip(v) for k, v in B["head_at_backend_rule"]["macro"].items()
            },
            "long_recording_check_backend_rule": {
                "detected_contamination_half_of_30s": round(
                    pcb["detection_rate"]["3"]["mean_over_categories"]["segment_top25"], 3
                ),
                "detected_contamination_all_of_30s": round(
                    pcb["detection_rate"]["6"]["mean_over_categories"]["segment_top25"], 3
                ),
                "detected_short_burst_5s_in_30s": round(
                    pcb["detection_rate"]["1"]["mean_over_categories"]["segment_top25"], 3
                ),
                "false_warning_clean_30s": round(
                    pcb["false_flag_rate"]["6"]["segment_top25"]["any_contamination"], 3
                ),
                "false_warning_clean_60s": round(
                    pcb["false_flag_rate"]["12"]["segment_top25"]["any_contamination"], 3
                ),
                "note": "synthetic recordings built from ESC-50 test-fold windows",
            },
            "noise_stress_contaminant_flag_rate": {
                k: round(v["contaminant_flag_rate"][0], 3)
                for k, v in res.get("noise_robustness", {}).get("mixed", {}).items()
            },
            "experiment_a_50_class_accuracy": {
                "mean": round(res["experiment_a"]["accuracy_mean"], 4),
                "std": round(res["experiment_a"]["accuracy_std"], 4),
            }
            if "experiment_a" in res
            else None,
        },
        "limitations": [
            "Trained and evaluated only on ESC-50: short, curated, mostly close-range clips. Field recordings differ (distance, overlap, recorder noise, long durations).",
            "Metrics are ESC-50 cross-validation estimates, not field accuracy. No field validation has been done.",
            "Each ESC-50 clip has one label, so co-occurring sources were never seen together in training; contamination mixed under a louder target is often missed (see noise_stress_contaminant_flag_rate).",
            "Short contamination bursts are not flagged at the recording level by design (segment_quantile pooling); use predict_segments to localize them.",
            "The bird, insect and frog categories come from few ESC-50 classes and are not species or region specific; on one real dawn-chorus recording the bird score stayed low.",
        ],
        "license": "CC BY-NC-SA 4.0 (derived from BirdNET v2.4 embeddings, CC BY-NC-SA 4.0, and ESC-50, CC BY-NC 3.0). Non-commercial use only.",
    }
    CARD_JSON.write_text(json.dumps(card, indent=1) + "\n")


FIXTURE = REPO / "backend" / "tests" / "fixtures" / "soundscape_30s.flac"


def cmd_smoke(args: argparse.Namespace) -> None:
    """Run the exported head on one real field soundscape (the backend test
    fixture, 30 s dawn chorus from the BirdNET-Analyzer example). Anecdote."""
    from thicket.models.birdnet_runtime import BirdNETRuntime, frame_windows
    from thicket.models.qc_head import QCHead
    from thicket.services.audio_io import decode

    head = QCHead.load(ARTIFACT)
    rt = BirdNETRuntime(num_threads=args.threads)
    x, _ = decode(FIXTURE, target_sr=48000)
    win, st = frame_windows(x)  # product setting: 3 s hop
    logits, emb = rt.infer(win)
    p = rt.sigmoid(logits).max(0)
    top = np.argsort(-p)[:5]
    out = {
        "file": str(FIXTURE.relative_to(REPO)),
        "n_windows": int(len(st)),
        "birdnet_top5": [[rt.labels[i].common_name, round(float(p[i]), 3)] for i in top],
        "probabilities": {
            mode: {c: round(v, 4) for c, v in head.predict(emb, mode=mode).items()}
            for mode in ("segment_quantile", "segment_max", "whole")
        },
        "per_segment": np.round(head.predict_segments(emb), 4).tolist(),
        "flags_default": head.flags(emb),
        "contamination_flags_default": head.contamination_flags(emb),
        "backend_warnings": [
            c
            for c, v in head.predict(emb).items()
            if head.category_kind[c] != "biophony"
            and v > max(BACKEND_MIN_PROBABILITY, head.threshold(c))
        ],
    }
    update_results("fixture_smoke", out)
    print(json.dumps(out["probabilities"], indent=1))


# ============================================================ CLI


def cmd_report(args: argparse.Namespace) -> None:
    import esc50_qc_report

    res = json.loads(RESULTS.read_text())
    if "export" in res:
        write_card_json(res)
    # Figures that need only the results file are re-rendered here.
    fig_ap(res["experiment_b"], FIG_DIR / "qc_ap_by_category.png")
    fig_confusion(res["experiment_b"], FIG_DIR / "qc_confusion.png")
    fig_reliability(res["experiment_b"], FIG_DIR / "qc_reliability.png")
    if "noise_robustness" in res:
        fig_noise(res["noise_robustness"], FIG_DIR / "qc_noise_robustness.png")
    esc50_qc_report.write_all(res)


def cmd_all(args: argparse.Namespace) -> None:
    for fn in (cmd_features, cmd_evaluate, cmd_noise, cmd_export, cmd_smoke, cmd_report):
        fn(args)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "stage",
        choices=["features", "evaluate", "postcheck", "noise", "export", "smoke", "report", "all"],
    )
    ap.add_argument(
        "--data", default="/home/claude/data/esc50", help="cache dir for ESC-50 audio and features"
    )
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="recompute cached features")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--skip-a", action="store_true", help="skip experiment A in evaluate")
    ap.add_argument("--noise-folds", default="1,2,3,4,5")
    args = ap.parse_args()
    {
        "features": cmd_features,
        "evaluate": cmd_evaluate,
        "postcheck": cmd_postcheck,
        "noise": cmd_noise,
        "export": cmd_export,
        "smoke": cmd_smoke,
        "report": cmd_report,
        "all": cmd_all,
    }[args.stage](args)


if __name__ == "__main__":
    main()

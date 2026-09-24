"""Soundscape QC head v2: v1's recipe plus synthetic mixture augmentation.

v1 (``esc50_qc.py``) learned from single-label ESC-50 clips and often missed a
contaminant mixed under a bird, frog or insect call. v2 adds mixtures made
inside each ESC-50 fold, so no source recording is shared between training and
test mixtures:

  mixfeatures  For every official fold f, using fold-f clips only:
               * a training pool of mixtures (base clip + contaminant clip at
                 a random SNR in [-10, +15] dB, labels = union of categories),
               * an evaluation set: every bird / insect / frog clip mixed with
                 3 contaminant categories (rotating over 6) at +10, 0 and -10 dB.
               Mixtures are re-embedded with BirdNETRuntime exactly like v1
               (3 s windows, 1 s hop, mean+max pooling) and cached.
  evaluate     Outer test fold k: v2 trains on clean clips + training-pool
               mixtures of the other 4 folds (all choices made on those folds
               only), and is tested on fold k's clean clips, fold k's
               training-pool mixtures and fold k's evaluation mixtures. v1 is
               the saved v1 fold models, scored on the same data.
               --variant v2a: union labels, one shared C (first attempt).
               --variant v2b: audibility-gated labels, per-category choice of
               mixture weight and C under a clean-AP constraint.
  diagnose     Training-folds-only comparison of recipes used to design v2b.
  export       Only if the pre-registered ship criteria below pass (or --force):
               train on all folds and write qc_head_v2.npz + .json (v1 format).
  smoke        Score the 30 s backend test soundscape with the v2 head.
  report       Write ml/reports/qc_esc50_v2.md and the v2 model card.

The mixtures are synthetic (two curated ESC-50 clips added together), not
field recordings.

    python ml/train/esc50_qc_mix.py all --data /home/claude/data/esc50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import esc50_qc as q  # noqa: E402
import evalkit as ek  # noqa: E402

REPO = q.REPO
RESULTS_V2 = (
    REPO / "ml" / "reports" / "qc_esc50_v2_results.json"
)  # v2b (the candidate for shipping)
RESULTS_V2A = (
    REPO / "ml" / "reports" / "qc_esc50_v2a_results.json"
)  # first recipe, kept as a record
ARTIFACT_V2 = REPO / "backend" / "thicket" / "models" / "data" / "qc_head_v2.npz"
CARD_JSON_V2 = ARTIFACT_V2.with_suffix(".json")
SEED = q.SEED + 2

MIX_CONTAMINANTS = ["rain", "wind", "thunder", "water", "engine_machinery", "human_nonspeech"]
# Base ("target") category for training-pool mixtures, with sampling weights.
MIX_BASES = {
    "bird": 0.25,
    "insect": 0.25,
    "frog": 0.20,
    "domestic_animal": 0.15,
    "human_nonspeech": 0.15,
}
EVAL_BASES = ["bird", "insect", "frog"]
N_TRAIN_MIX_PER_FOLD = 400
TRAIN_SNR_RANGE = (-10.0, 15.0)
EVAL_SNRS = [10.0, 0.0, -10.0]
EVAL_CONTAMINANTS_PER_CLIP = 3
C_GRID_V2 = [0.01, 0.03, 0.1, 0.3]

# Ship criteria, written down before any v2 result was computed.
SHIP_CRITERIA = {
    "clean_macro_ap_diff_ci_low_min": -0.02,
    "clean_macro_ap_diff_point_min": -0.01,
    "clean_macro_f1_diff_point_min": -0.02,
    "mixture_detection_gain_ci_low_min_at_0dB_and_minus10dB": 0.0,
    "clean_bio_false_flag_increase_max_backend_rule": 0.05,
}


# ============================================================ helpers


def update_results(section: str, payload: dict, path: Path | None = None) -> None:
    path = path or RESULTS_V2
    res = json.loads(path.read_text()) if path.exists() else {}
    res[section] = payload
    path.write_text(json.dumps(res, indent=1, default=q._json_default))


def pigeonhole_bootstrap(fn, g1, g2, n_boot: int = 1000, seed: int = 0) -> list[float]:
    """Two-way cluster ('pigeonhole') bootstrap for items crossed by two
    groupings, here the base clip's source recording and the contaminant
    clip's source recording. Each replicate resamples both groupings
    independently; an item's weight is the product of its two multiplicities.
    ``fn(weights) -> float``. Returns [point, lo, hi]."""
    u1, i1 = np.unique(g1, return_inverse=True)
    u2, i2 = np.unique(g2, return_inverse=True)
    point = fn(np.ones(len(i1)))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        w1 = np.bincount(rng.integers(0, len(u1), len(u1)), minlength=len(u1))
        w2 = np.bincount(rng.integers(0, len(u2), len(u2)), minlength=len(u2))
        w = (w1[i1] * w2[i2]).astype(np.float64)
        if w.sum() > 0:
            v = fn(w)
            if np.isfinite(v):
                vals.append(v)
    lo, hi = np.percentile(vals, [2.5, 97.5]) if vals else (np.nan, np.nan)
    return [float(point), float(lo), float(hi)]


def wmean(y: np.ndarray):
    y = np.asarray(y, dtype=np.float64)
    return lambda w: float((w * y).sum() / w.sum()) if w.sum() > 0 else float("nan")


# ============================================================ mixtures


def plan_mixtures(F: dict) -> list[dict]:
    """Deterministic list of mixtures; both parts always come from one fold."""
    rng = np.random.default_rng(SEED)
    esc = F["category"]
    Y = q.category_targets(esc)
    folds = F["fold"].astype(int)
    cat_of = {c: Y[:, q.CATEGORIES.index(c)] > 0 for c in q.CATEGORIES}
    plan: list[dict] = []
    for f in range(1, 6):
        inf = folds == f
        # Training pool: random base category, random different contaminant category, random SNR.
        names = list(MIX_BASES)
        probs = np.array([MIX_BASES[n] for n in names])
        probs = probs / probs.sum()
        for _ in range(N_TRAIN_MIX_PER_FOLD):
            bcat = str(rng.choice(names, p=probs))
            ccat = str(rng.choice([c for c in MIX_CONTAMINANTS if c != bcat]))
            b = int(rng.choice(np.flatnonzero(inf & cat_of[bcat])))
            c = int(rng.choice(np.flatnonzero(inf & cat_of[ccat])))
            snr = float(np.round(rng.uniform(*TRAIN_SNR_RANGE), 2))
            plan.append(
                {
                    "set": "train",
                    "fold": f,
                    "base": b,
                    "cont": c,
                    "base_cat": bcat,
                    "cont_cat": ccat,
                    "snr_db": snr,
                }
            )
        # Evaluation set: every bio clip x 3 contaminant categories x 3 SNRs.
        bio = [i for i in np.flatnonzero(inf) if any(cat_of[c][i] for c in EVAL_BASES)]
        for si, snr in enumerate(EVAL_SNRS):
            for j, b in enumerate(bio):
                bcat = next(c for c in EVAL_BASES if cat_of[c][b])
                start = (EVAL_CONTAMINANTS_PER_CLIP * (j + si)) % len(MIX_CONTAMINANTS)
                for t in range(EVAL_CONTAMINANTS_PER_CLIP):
                    ccat = MIX_CONTAMINANTS[(start + t) % len(MIX_CONTAMINANTS)]
                    c = int(rng.choice(np.flatnonzero(inf & cat_of[ccat])))
                    plan.append(
                        {
                            "set": "eval",
                            "fold": f,
                            "base": int(b),
                            "cont": c,
                            "base_cat": bcat,
                            "cont_cat": ccat,
                            "snr_db": snr,
                        }
                    )
    return plan


def cmd_mixfeatures(args: argparse.Namespace) -> None:
    from thicket.models.birdnet_runtime import BirdNETRuntime
    from thicket.services.audio_io import decode

    data = Path(args.data)
    out = data / "mix_features.npz"
    if out.exists() and not args.force:
        print(f"[mix] cached: {out}")
        return
    F = q.load_features(data)
    plan = plan_mixtures(F)
    rt = BirdNETRuntime(num_threads=args.threads)
    rt.load()
    if rt.model_sha256 != str(F["birdnet_sha256"]):
        raise RuntimeError("BirdNET weights differ from the ones used for the clean features")
    taxa = np.array([lab.taxon for lab in rt.labels])
    tmask = {"bird": taxa == "bird", "amphibian": taxa == "amphibian", "insect": taxa == "insect"}
    repo = data / "repo"
    embs, widx, bn = [], [], []
    t0 = time.time()
    nw = 0
    for f in range(1, 6):
        cache: dict[int, np.ndarray] = {}

        def dec(i: int, cache: dict = cache) -> np.ndarray:
            if i not in cache:
                cache[i] = decode(repo / "audio" / str(F["filename"][i]), target_sr=48000)[0]
            return cache[i]

        for m_i, m in enumerate(plan):
            if m["fold"] != f:
                continue
            x = q.mix_at_snr(dec(m["base"]), dec(m["cont"]), m["snr_db"])
            emb, logits, st = q.embed_audio(rt, x)
            p = ek.sigmoid(logits)
            embs.append(emb.astype(np.float32))
            widx.append(np.full(len(st), m_i, dtype=np.int32))
            bn.append([float(p[:, tmask[t]].max()) for t in ("bird", "amphibian", "insect")])
            nw += len(st)
        el = time.time() - t0
        print(f"[mix] fold {f} done: {nw} windows, {el:.0f}s ({nw / el:.1f} win/s)", flush=True)
    keys = ("set", "fold", "base", "cont", "base_cat", "cont_cat", "snr_db")
    np.savez_compressed(
        out,
        embedding=np.concatenate(embs),
        mix_index=np.concatenate(widx),
        birdnet_taxon_max=np.array(bn, dtype=np.float32),
        birdnet_taxon_names=np.array(["bird", "amphibian", "insect"]),
        birdnet_sha256=np.array(rt.model_sha256),
        seconds=np.array(time.time() - t0),
        **{f"plan_{k}": np.array([m[k] for m in plan]) for k in keys},
    )
    print(f"[mix] wrote {out}: {len(plan)} mixtures, {nw} windows in {time.time() - t0:.0f}s")


def load_mix(data: Path) -> dict:
    z = np.load(Path(data) / "mix_features.npz", allow_pickle=False)
    M = {k: z[k] for k in z.files}
    n = len(M["plan_set"])
    bounds = np.searchsorted(M["mix_index"], np.arange(n + 1))
    X = np.zeros((n, 2 * M["embedding"].shape[1]), np.float32)
    for i in range(n):
        X[i] = q.pool_windows(M["embedding"][bounds[i] : bounds[i + 1]])
    M["X"] = X
    M["bounds"] = bounds
    Y = np.zeros((n, len(q.CATEGORIES)))
    for i in range(n):
        Y[i, q.CATEGORIES.index(str(M["plan_base_cat"][i]))] = 1
        Y[i, q.CATEGORIES.index(str(M["plan_cont_cat"][i]))] = 1
    M["Y"] = Y
    return M


# ============================================================ v2b: per-category recipe selection

V2B_RECIPES = [("clean_only", 0.0), ("gated_w0.1", 0.1), ("gated_w0.25", 0.25), ("gated_w0.5", 0.5)]
V2B_C_GRID = [0.003, 0.01, 0.03, 0.1]
V2B_CLEAN_TOLERANCE = 0.01  # a recipe may cost at most this much clean AP per category (inner CV)


def fit_head_v2b(Xc, Yc, fc, Xm, Ym, fm, recipes=None, grid=None) -> tuple[dict, dict]:
    """v2b: for each category pick (recipe, C) on training folds only.

    Recipes differ in how much the (audibility-gated) mixtures weigh. For each
    category, a (recipe, C) pair is allowed if its inner-CV clean AP is within
    V2B_CLEAN_TOLERANCE of the best clean-only AP for that category; among
    allowed pairs the one with the best inner-CV AP on clean clips and
    mixtures together is kept. Platt scaling and thresholds are then fit on
    those out-of-fold predictions (clean + mixtures). The per-category linear
    models are refit on all training rows and re-expressed with one shared
    standardization, so the result has exactly v1's format.
    """
    from linear import Standardizer, fit_multilabel

    recipes = recipes or V2B_RECIPES
    grid = grid or V2B_C_GRID
    K = Yc.shape[1]
    Zc = {(r, C): np.zeros(Yc.shape) for r, _ in recipes for C in grid}
    Zm = {(r, C): np.zeros(Ym.shape) for r, _ in recipes for C in grid}
    for j in sorted(set(fc.tolist())):
        ctr, cva = fc != j, fc == j
        mtr, mva = fm != j, fm == j
        for r, w in recipes:
            Xa = np.vstack([Xc[ctr], Xm[mtr]]) if w > 0 else Xc[ctr]
            Ya = np.vstack([Yc[ctr], Ym[mtr]]) if w > 0 else Yc[ctr]
            sw = np.r_[np.ones(ctr.sum()), np.full(mtr.sum(), w)] if w > 0 else None
            sc = Standardizer.fit(Xa)
            Xs = sc(Xa)
            W = None
            for C in sorted(grid):
                W, b = fit_multilabel(Xs, Ya, C, sample_weight=sw, W0=W)
                Zc[(r, C)][cva] = sc(Xc[cva]) @ W + b
                Zm[(r, C)][mva] = sc(Xm[mva]) @ W + b
    Yall = np.vstack([Yc, Ym])
    choice, table = [], {}
    for k in range(K):
        clean_ap = {key: ek.safe_ap(Yc[:, k], Zc[key][:, k]) for key in Zc}
        all_ap = {key: ek.safe_ap(Yall[:, k], np.r_[Zc[key][:, k], Zm[key][:, k]]) for key in Zc}
        ref = max(clean_ap[("clean_only", C)] for C in grid)
        feasible = [key for key in Zc if clean_ap[key] >= ref - V2B_CLEAN_TOLERANCE]
        order = {r: i for i, (r, _) in enumerate(recipes)}
        best = max(feasible, key=lambda key: (round(all_ap[key], 6), -order[key[0]], -key[1]))
        choice.append(best)
        table[q.CATEGORIES[k]] = {
            "recipe": best[0],
            "C": best[1],
            "clean_ap_ref": ref,
            "clean_ap_chosen": clean_ap[best],
            "combined_ap_chosen": all_ap[best],
            "combined_ap_clean_only_best": max(all_ap[("clean_only", C)] for C in grid),
        }
    Zo = np.vstack(
        [
            np.stack([Zc[choice[k]][:, k] for k in range(K)], 1),
            np.stack([Zm[choice[k]][:, k] for k in range(K)], 1),
        ]
    )
    platt = [ek.fit_platt(Zo[:, k], Yall[:, k]) for k in range(K)]
    pa = np.array([p[0] for p in platt])
    pb = np.array([p[1] for p in platt])
    Po = ek.sigmoid(pa * Zo + pb)
    thr_f1 = np.array([ek.choose_threshold(Yall[:, k], Po[:, k], "f1") for k in range(K)])
    thr_p90 = np.array(
        [ek.choose_threshold(Yall[:, k], Po[:, k], "precision", 0.9) for k in range(K)]
    )
    # Final per-(recipe, C) fits on all training rows, re-expressed on the clean standardizer.
    common = Standardizer.fit(Xc)
    Wf = np.zeros((Xc.shape[1], K))
    bf = np.zeros(K)
    wmap = dict(recipes)
    for key in sorted(set(choice)):
        r, C = key
        w = wmap[r]
        Xa = np.vstack([Xc, Xm]) if w > 0 else Xc
        Ya = np.vstack([Yc, Ym]) if w > 0 else Yc
        sw = np.r_[np.ones(len(Xc)), np.full(len(Xm), w)] if w > 0 else None
        sc = Standardizer.fit(Xa)
        W, b = fit_multilabel(sc(Xa), Ya, C, sample_weight=sw)
        for k in [k for k in range(K) if choice[k] == key]:
            w_raw = W[:, k] / sc.std
            b_raw = b[k] - sc.mean @ w_raw
            Wf[:, k] = w_raw * common.std
            bf[k] = b_raw + common.mean @ w_raw
    model = {
        "mean": common.mean,
        "std": common.std,
        "W": Wf,
        "b": bf,
        "platt_a": pa,
        "platt_b": pb,
        "thr_f1": thr_f1,
        "thr_p90": thr_p90,
        "C": np.array([c for _, c in choice]),
    }
    info = {"per_category": table, "oof_logits": Zo, "oof_labels": Yall}
    return model, info


# ============================================================ evaluation


def rates_table(
    D: np.ndarray, M: dict, rows: np.ndarray, src: np.ndarray, n_boot: int, seed: int
) -> dict:
    """Detection / retention / extra-flag rates per contaminant and SNR on the
    evaluation mixtures ``rows`` for decisions ``D`` (n_mix, n_categories)."""
    out: dict = {}
    base_src = src[M["plan_base"][rows]]
    cont_src = src[M["plan_cont"][rows]]
    cont_cols = [q.CATEGORIES.index(c) for c in q.CONTAMINATION]
    for snr in EVAL_SNRS:
        for c in MIX_CONTAMINANTS + ["all"]:
            sel = M["plan_snr_db"][rows] == snr
            if c != "all":
                sel &= M["plan_cont_cat"][rows] == c
            idx = np.flatnonzero(sel)
            r = rows[idx]
            ci = np.array([q.CATEGORIES.index(str(x)) for x in M["plan_cont_cat"][r]])
            bi = np.array([q.CATEGORIES.index(str(x)) for x in M["plan_base_cat"][r]])
            det = D[r, ci]
            keep = D[r, bi]
            other = np.array(
                [D[i, [k for k in cont_cols if k != j]].any() for i, j in zip(r, ci, strict=True)]
            )
            g1, g2 = base_src[idx], cont_src[idx]
            out[f"{c}@{snr:+.0f}"] = {
                "n": int(len(r)),
                "detected": pigeonhole_bootstrap(wmean(det), g1, g2, n_boot, seed),
                "base_still_flagged": pigeonhole_bootstrap(wmean(keep), g1, g2, n_boot, seed + 1),
                "other_contamination_flag": pigeonhole_bootstrap(
                    wmean(other), g1, g2, n_boot, seed + 2
                ),
            }
    return out


def detection_gain(D2, D1, M, rows, src, n_boot, seed) -> dict:
    """Paired difference (v2 minus v1) of contaminant detection per SNR, mean
    over the evaluation mixtures of that SNR (all contaminants pooled; each
    contaminant has the same number of mixtures), plus per contaminant."""
    out = {}
    base_src = src[M["plan_base"][rows]]
    cont_src = src[M["plan_cont"][rows]]
    ci = np.array([q.CATEGORIES.index(str(x)) for x in M["plan_cont_cat"][rows]])
    diff = D2[rows, ci].astype(float) - D1[rows, ci].astype(float)
    for snr in EVAL_SNRS:
        for c in MIX_CONTAMINANTS + ["all"]:
            sel = M["plan_snr_db"][rows] == snr
            if c != "all":
                sel &= M["plan_cont_cat"][rows] == c
            idx = np.flatnonzero(sel)
            out[f"{c}@{snr:+.0f}"] = pigeonhole_bootstrap(
                wmean(diff[idx]), base_src[idx], cont_src[idx], n_boot, seed
            )
    return out


def cmd_evaluate(args: argparse.Namespace) -> None:
    t_start = time.time()
    data = Path(args.data)
    F, X, Y, folds, groups = q.load_all(args)
    M = load_mix(data)
    if str(M["birdnet_sha256"]) != str(F["birdnet_sha256"]):
        raise RuntimeError("mixture features come from different BirdNET weights")
    src = F["src_file"]
    mfold = M["plan_fold"].astype(int)
    is_train_mix = M["plan_set"] == "train"
    is_eval_mix = M["plan_set"] == "eval"
    # Fold-disjointness check: both parts of every mixture come from its fold.
    if not (np.all(folds[M["plan_base"]] == mfold) and np.all(folds[M["plan_cont"]] == mfold)):
        raise RuntimeError("a mixture uses clips from two folds")
    Ygated = mixture_labels(M, "gated")
    out_path = RESULTS_V2A if args.variant == "v2a" else RESULTS_V2
    models_v1 = q.load_fold_models(data)
    preds_v1 = np.load(data / "expB_predictions.npz", allow_pickle=False)
    if not np.array_equal(preds_v1["Y"], Y):
        raise RuntimeError("saved v1 predictions do not match the label mapping")
    K = len(q.CATEGORIES)
    n_mix = len(mfold)
    P2 = np.zeros((len(Y), K))
    Pm1, Pm2 = np.zeros((n_mix, K)), np.zeros((n_mix, K))
    D2 = {r: np.zeros((len(Y), K), bool) for r in ("f1", "backend")}
    Dm1 = {r: np.zeros((n_mix, K), bool) for r in ("f1", "backend")}
    Dm2 = {r: np.zeros((n_mix, K), bool) for r in ("f1", "backend")}
    D1 = {"f1": preds_v1["D_f1"].astype(bool), "backend": np.zeros((len(Y), K), bool)}
    models_v2: dict[int, dict] = {}
    folds_out = {}
    for k in range(1, 6):
        t0 = time.time()
        tr_c, te_c = folds != k, folds == k
        tr_m = is_train_mix & (mfold != k)
        te_m = mfold == k
        if args.variant == "v2a":
            Xtr = np.vstack([X[tr_c], M["X"][tr_m]])
            Ytr = np.vstack([Y[tr_c], M["Y"][tr_m]])
            ftr = np.concatenate([folds[tr_c], mfold[tr_m]])
            m2, info = q.fit_head(Xtr, Ytr, ftr, C_GRID_V2)
        else:
            Ytr = np.vstack([Y[tr_c], Ygated[tr_m]])
            m2, info = fit_head_v2b(
                X[tr_c], Y[tr_c], folds[tr_c], M["X"][tr_m], Ygated[tr_m], mfold[tr_m]
            )
            info["C"] = {c: v["recipe"] + f" C={v['C']}" for c, v in info["per_category"].items()}
            info["inner_macro_ap"] = info["per_category"]
        models_v2[k] = m2
        m1 = models_v1[k]
        P2[te_c] = q.predict_proba(m2, X[te_c])
        Pm2[te_m] = q.predict_proba(m2, M["X"][te_m])
        Pm1[te_m] = q.predict_proba(m1, M["X"][te_m])
        r1, r2 = q.decision_rules(m1), q.decision_rules(m2)
        for r in ("f1", "backend"):
            D2[r][te_c] = r2[r](P2[te_c])
            Dm2[r][te_m] = r2[r](Pm2[te_m])
            Dm1[r][te_m] = r1[r](Pm1[te_m])
        D1["backend"][te_c] = r1["backend"](preds_v1["P"][te_c])
        folds_out[str(k)] = {
            "C": info["C"],
            "inner_macro_ap": info["inner_macro_ap"],
            "n_train_rows": int(len(Ytr)),
            "thresholds_f1": dict(zip(q.CATEGORIES, m2["thr_f1"].tolist(), strict=True)),
        }
        print(
            f"[v2] fold {k}: C={info['C']} clean macroAP v2 {q.macro_ap(Y[te_c], P2[te_c]):.4f} v1 {q.macro_ap(Y[te_c], preds_v1['P'][te_c]):.4f} ({time.time() - t0:.0f}s)",
            flush=True,
        )

    P1 = preds_v1["P"]
    nb = args.n_boot
    res: dict = {
        "config": {
            "mix_contaminants": MIX_CONTAMINANTS,
            "mix_bases": MIX_BASES,
            "eval_bases": EVAL_BASES,
            "n_train_mix_per_fold": N_TRAIN_MIX_PER_FOLD,
            "train_snr_range_db": TRAIN_SNR_RANGE,
            "eval_snrs_db": EVAL_SNRS,
            "eval_contaminants_per_clip_and_snr": EVAL_CONTAMINANTS_PER_CLIP,
            "variant": args.variant,
            "c_grid": C_GRID_V2 if args.variant == "v2a" else V2B_C_GRID,
            "v2b_recipes": V2B_RECIPES,
            "v2b_clean_tolerance": V2B_CLEAN_TOLERANCE,
            "gate_db": [GATE_CONT_DB, GATE_BASE_DB],
            "snr_definition": "active RMS (50 ms frames above -80 dBFS, which skips ESC-50's digital-silence padding) of the base clip vs the contaminant clip over the 5 s clip",
            "labels": "v2a: union of both clips' categories whatever the SNR. v2b training: audibility-gated (contaminant counted only if SNR <= +10 dB, base only if SNR >= -5 dB). Evaluation tables always use the evaluation-set design (the added contaminant is present at +10, 0 and -10 dB).",
            "seed": SEED,
            "n_boot": nb,
            "ship_criteria": SHIP_CRITERIA,
            "birdnet_sha256": str(F["birdnet_sha256"]),
            "n_mixtures": {"train_pool": int(is_train_mix.sum()), "eval": int(is_eval_mix.sum())},
            "mixfeature_seconds": float(M["seconds"]),
        },
        "folds": folds_out,
    }
    # (a) clean ESC-50 test folds.
    res["clean"] = {
        "v1_f1": ek.per_class_table(Y, P1, D1["f1"], q.CATEGORIES, groups, nb, SEED),
        "v2_f1": ek.per_class_table(Y, P2, D2["f1"], q.CATEGORIES, groups, nb, SEED),
        "v1_backend": ek.per_class_table(Y, P1, D1["backend"], q.CATEGORIES, groups, nb, SEED),
        "v2_backend": ek.per_class_table(Y, P2, D2["backend"], q.CATEGORIES, groups, nb, SEED),
    }

    def macro_f1(Yi, Di):
        v = [ek.prf(Yi[:, j], Di[:, j])[2] for j in range(K) if Yi[:, j].any()]
        return float(np.mean(v))

    res["clean"]["diff_v2_minus_v1"] = {
        "macro_ap": ek.cluster_bootstrap(
            lambda i: q.macro_ap(Y[i], P2[i]) - q.macro_ap(Y[i], P1[i]), groups, nb, SEED + 1
        ),
        "macro_f1": ek.cluster_bootstrap(
            lambda i: macro_f1(Y[i], D2["f1"][i]) - macro_f1(Y[i], D1["f1"][i]),
            groups,
            nb,
            SEED + 2,
        ),
        "ap_per_category": {
            c: ek.cluster_bootstrap(
                lambda i, j=j: ek.safe_ap(Y[i, j], P2[i, j]) - ek.safe_ap(Y[i, j], P1[i, j]),
                groups,
                nb,
                SEED + 10 + j,
            )
            for j, c in enumerate(q.CATEGORIES)
        },
    }
    res["clean"]["ece"] = {"v1": ek.reliability(Y, P1)["ece"], "v2": ek.reliability(Y, P2)["ece"]}
    bio = Y[:, [q.CATEGORIES.index(c) for c in EVAL_BASES]].sum(1) > 0
    cont_cols = [q.CATEGORIES.index(c) for c in q.CONTAMINATION]
    ffl = {}
    for r in ("f1", "backend"):
        a1 = D1[r][:, cont_cols].any(1).astype(float)
        a2 = D2[r][:, cont_cols].any(1).astype(float)
        bi = np.flatnonzero(bio)
        b1, b2 = a1[bi], a2[bi]
        ffl[r] = {
            "v1": ek.cluster_bootstrap(
                lambda i, a=b1: float(a[i].mean()), groups[bi], nb, SEED + 20
            ),
            "v2": ek.cluster_bootstrap(
                lambda i, a=b2: float(a[i].mean()), groups[bi], nb, SEED + 21
            ),
            "diff": ek.cluster_bootstrap(
                lambda i, a=b1, b=b2: float((b[i] - a[i]).mean()), groups[bi], nb, SEED + 22
            ),
            "n": int(bio.sum()),
        }
    res["clean_bio_false_contamination_flag"] = ffl
    print(f"[v2] clean tables done ({time.time() - t_start:.0f}s)", flush=True)

    # (b) evaluation mixtures at fixed SNRs.
    ev = np.flatnonzero(is_eval_mix)
    res["mixtures_eval"] = {}
    for r in ("f1", "backend"):
        res["mixtures_eval"][r] = {
            "v1": rates_table(Dm1[r], M, ev, src, nb, SEED + 30),
            "v2": rates_table(Dm2[r], M, ev, src, nb, SEED + 30),
            "gain_v2_minus_v1": detection_gain(Dm2[r], Dm1[r], M, ev, src, nb, SEED + 40),
        }
    # (c) training-pool mixtures of the test fold (random SNR, multi-label AP).
    tp = np.flatnonzero(is_train_mix)
    g_tp = src[M["plan_base"][tp]]
    res["mixtures_random_snr_ap"] = {
        "n": int(len(tp)),
        "v1_macro_ap": ek.cluster_bootstrap(
            lambda i: q.macro_ap(M["Y"][tp][i], Pm1[tp][i]), g_tp, nb, SEED + 50
        ),
        "v2_macro_ap": ek.cluster_bootstrap(
            lambda i: q.macro_ap(M["Y"][tp][i], Pm2[tp][i]), g_tp, nb, SEED + 50
        ),
        "per_category_ap": {
            c: {
                "v1": ek.safe_ap(M["Y"][tp][:, j], Pm1[tp][:, j]),
                "v2": ek.safe_ap(M["Y"][tp][:, j], Pm2[tp][:, j]),
                "n_pos": int(M["Y"][tp][:, j].sum()),
            }
            for j, c in enumerate(q.CATEGORIES)
        },
        "bootstrap_groups": "base clip source recording",
        "labels": "union of both clips' categories",
    }
    Yg_tp = Ygated[tp]
    res["mixtures_random_snr_ap_gated_labels"] = {
        "n": int(len(tp)),
        "v1_macro_ap": ek.cluster_bootstrap(
            lambda i: q.macro_ap(Yg_tp[i], Pm1[tp][i]), g_tp, nb, SEED + 51
        ),
        "v2_macro_ap": ek.cluster_bootstrap(
            lambda i: q.macro_ap(Yg_tp[i], Pm2[tp][i]), g_tp, nb, SEED + 51
        ),
        "labels": "audibility-gated (contaminant only if SNR <= +10 dB, base only if SNR >= -5 dB)",
    }
    # BirdNET on the evaluation mixtures (context).
    tax = {"bird": 0, "frog": 1, "insect": 2}
    bnr = {}
    for snr in EVAL_SNRS:
        sel = ev[M["plan_snr_db"][ev] == snr]
        bnr[f"{snr:+.0f}"] = {
            t: float(
                np.mean(
                    M["birdnet_taxon_max"][sel[M["plan_base_cat"][sel] == t], tax[t]]
                    >= q.BIRDNET_REPORT_THRESHOLD
                )
            )
            for t in EVAL_BASES
        }
    res["birdnet_taxon_rate_at_0.6_eval_mixtures"] = bnr
    print(f"[v2] mixture tables done ({time.time() - t_start:.0f}s)", flush=True)

    # (d) long-recording synthetic check (clean windows), v2 fold models.
    res["pooling_check_v2"] = q.run_pooling_check(F, Y, folds, models_v2)
    v1res = json.loads(q.RESULTS.read_text())
    res["pooling_check_v1"] = v1res["experiment_b"]["pooling_check"]
    res["decision"] = decide(res)
    res["seconds"] = round(time.time() - t_start, 1)
    for key, val in res.items():
        update_results(key, val, out_path)
    np.savez_compressed(
        data / f"fold_models_{args.variant}.npz",
        **{f"f{k}_{n}": v for k, m in models_v2.items() for n, v in m.items()},
    )
    if args.variant != "v2a":
        figures(res)
    print(json.dumps(res["decision"], indent=1))
    print(f"[v2] evaluate done in {res['seconds']:.0f}s")


def decide(res: dict) -> dict:
    """Apply the pre-registered ship criteria."""
    c = SHIP_CRITERIA
    d_ap = res["clean"]["diff_v2_minus_v1"]["macro_ap"]
    d_f1 = res["clean"]["diff_v2_minus_v1"]["macro_f1"]
    gain = res["mixtures_eval"]["backend"]["gain_v2_minus_v1"]
    ff = res["clean_bio_false_contamination_flag"]["backend"]["diff"]
    checks = {
        "clean_macro_ap_diff_ci_low": [d_ap[1], d_ap[1] >= c["clean_macro_ap_diff_ci_low_min"]],
        "clean_macro_ap_diff_point": [d_ap[0], d_ap[0] >= c["clean_macro_ap_diff_point_min"]],
        "clean_macro_f1_diff_point": [d_f1[0], d_f1[0] >= c["clean_macro_f1_diff_point_min"]],
        "mixture_gain_0dB_ci_low": [
            gain["all@+0"][1],
            gain["all@+0"][1] > c["mixture_detection_gain_ci_low_min_at_0dB_and_minus10dB"],
        ],
        "mixture_gain_minus10dB_ci_low": [
            gain["all@-10"][1],
            gain["all@-10"][1] > c["mixture_detection_gain_ci_low_min_at_0dB_and_minus10dB"],
        ],
        "clean_bio_false_flag_increase": [
            ff[0],
            ff[0] <= c["clean_bio_false_flag_increase_max_backend_rule"],
        ],
    }
    return {
        "checks": {k: {"value": float(v[0]), "pass": bool(v[1])} for k, v in checks.items()},
        "ship": all(v[1] for v in checks.values()),
    }


# ============================================================ design diagnostic (v2b)

# Audibility gate for mixture labels: the contaminant counts as present only
# if it is at most GATE_CONT_DB below the base, and the base only if it is at
# most -GATE_BASE_DB below the contaminant.
GATE_CONT_DB = 10.0
GATE_BASE_DB = -5.0


def mixture_labels(M: dict, policy: str) -> np.ndarray:
    Y = M["Y"].copy()
    if policy == "union":
        return Y
    if policy != "gated":
        raise ValueError(policy)
    snr = M["plan_snr_db"].astype(float)
    for i in range(len(Y)):
        if snr[i] > GATE_CONT_DB:
            Y[i, q.CATEGORIES.index(str(M["plan_cont_cat"][i]))] = 0
        if snr[i] < GATE_BASE_DB:
            Y[i, q.CATEGORIES.index(str(M["plan_base_cat"][i]))] = 0
    return Y


def cmd_diagnose(args: argparse.Namespace) -> None:
    """Pick v2b's candidate recipes using outer fold 1's training folds only.

    Fold 1 is not touched. Folds 2 and 3 serve in turn as validation folds
    (trained on the other three of folds 2 to 5). Written after v2a failed the
    clean-set criterion; see the report.
    """
    from linear import Standardizer, fit_multilabel

    data = Path(args.data)
    F, X, Y, folds, groups = q.load_all(args)
    M = load_mix(data)
    mf = M["plan_fold"].astype(int)
    tp = M["plan_set"] == "train"
    snr = M["plan_snr_db"].astype(float)
    recipes = [
        ("clean_only", "union", 0.0),
        ("union_w1", "union", 1.0),
        ("union_w0.25", "union", 0.25),
        ("gated_w1", "gated", 1.0),
        ("gated_w0.25", "gated", 0.25),
    ]
    out: dict = {
        "note": "outer fold 1 excluded; validation folds 2 and 3; union labels used to score mixtures with SNR <= +10 dB",
        "gate_db": [GATE_CONT_DB, GATE_BASE_DB],
        "rows": [],
    }
    for val in (2, 3):
        trf = [f for f in (2, 3, 4, 5) if f != val]
        ctr, cva = np.isin(folds, trf), folds == val
        mtr = tp & np.isin(mf, trf)
        mva = tp & (mf == val) & (snr <= GATE_CONT_DB)
        for name, policy, w in recipes:
            Ym = mixture_labels(M, policy)
            Xa = np.vstack([X[ctr], M["X"][mtr]]) if w > 0 else X[ctr]
            Ya = np.vstack([Y[ctr], Ym[mtr]]) if w > 0 else Y[ctr]
            sw = np.r_[np.ones(ctr.sum()), np.full(mtr.sum(), w)] if w > 0 else None
            sc = Standardizer.fit(Xa)
            for C in (0.01, 0.1):
                W, b = fit_multilabel(sc(Xa), Ya, C, sample_weight=sw)
                zc = sc(X[cva]) @ W + b
                zm = sc(M["X"][mva]) @ W + b
                row = {
                    "val_fold": val,
                    "recipe": name,
                    "C": C,
                    "clean_macro_ap": q.macro_ap(Y[cva], zc),
                    "mixture_macro_ap": q.macro_ap(M["Y"][mva], zm),
                    "clean_ap_per_category": {
                        c: ek.safe_ap(Y[cva][:, j], zc[:, j]) for j, c in enumerate(q.CATEGORIES)
                    },
                }
                out["rows"].append(row)
                print(
                    f"[diag] val {val} {name:12s} C={C}: clean {row['clean_macro_ap']:.4f} mix {row['mixture_macro_ap']:.4f}",
                    flush=True,
                )
    update_results("design_diagnostic_v2b", out)


# ============================================================ figures


def figures(res: dict) -> None:
    from plotstyle import BLUE, ORANGE, plt

    fig_dir = q.FIG_DIR
    # Detection vs SNR per contaminant, v1 vs v2 (backend rule).
    E = res["mixtures_eval"]["backend"]
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 6.6), sharex=True, sharey=True)
    xs = np.arange(len(EVAL_SNRS))
    for ax, c in zip(axes.ravel(), MIX_CONTAMINANTS, strict=True):
        for ver, col, lab in (
            ("v1", ORANGE, "v1 (clean training)"),
            ("v2", BLUE, "v2 (with mixtures)"),
        ):
            v = np.array([E[ver][f"{c}@{s:+.0f}"]["detected"] for s in EVAL_SNRS])
            ax.fill_between(xs, v[:, 1], v[:, 2], color=col, alpha=0.14, lw=0)
            ax.plot(xs, v[:, 0], marker="o", ms=6, color=col, label=lab)
        ax.set_title(c, fontsize=10)
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{s:+.0f} dB" if s else "0 dB" for s in EVAL_SNRS])
        ax.set_ylim(0, 1.02)
    for ax in axes[1]:
        ax.set_xlabel("Bio-to-contaminant SNR")
    for ax in axes[:, 0]:
        ax.set_ylabel("Contaminant flagged")
    axes[0, 0].legend(loc="upper left", fontsize=8)
    fig.suptitle(
        "Held-out synthetic mixtures (bird, frog or insect clip + contaminant), backend warning rule, 95% CI",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(fig_dir / "qc_v2_mixture_detection.png")
    plt.close(fig)

    # Clean per-category AP v1 vs v2.
    C1, C2 = res["clean"]["v1_f1"]["per_class"], res["clean"]["v2_f1"]["per_class"]
    cats = q.CATEGORIES[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    y = np.arange(len(cats))
    for off, tab, col, lab in (
        (0.17, C2, BLUE, "v2 (with mixtures)"),
        (-0.17, C1, ORANGE, "v1 (clean training)"),
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
    ax.set_yticklabels(cats)
    ax.set_xlim(0, 1.02)
    ax.set_xlabel("Average precision on clean ESC-50 test folds (95% CI)")
    ax.set_title("Clean ESC-50, 5-fold CV: v1 vs v2", pad=30)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9)
    fig.savefig(fig_dir / "qc_v2_clean_ap.png")
    plt.close(fig)

    # Mean detection over contaminants and bio retention vs SNR.
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9), sharey=True)
    panels = [
        ("detected", "Added contaminant flagged"),
        ("base_still_flagged", "Bird / frog / insect still flagged"),
        ("other_contamination_flag", "Another contamination category flagged"),
    ]
    for ax, (key, title) in zip(axes, panels, strict=True):
        for ver, col, lab in (("v1", ORANGE, "v1"), ("v2", BLUE, "v2")):
            v = np.array([E[ver][f"all@{s:+.0f}"][key] for s in EVAL_SNRS])
            ax.fill_between(xs, v[:, 1], v[:, 2], color=col, alpha=0.14, lw=0)
            ax.plot(xs, v[:, 0], marker="o", ms=6, color=col, label=lab)
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{s:+.0f} dB" if s else "0 dB" for s in EVAL_SNRS])
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Bio-to-contaminant SNR")
    axes[0].set_ylabel("Share of mixtures (95% CI)")
    axes[0].legend(loc="upper left", fontsize=9)
    fig.suptitle(
        "All six contaminants pooled, backend warning rule", x=0.01, ha="left", fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(fig_dir / "qc_v2_mixture_summary.png")
    plt.close(fig)


# ============================================================ export + smoke


def cmd_export(args: argparse.Namespace) -> None:
    res = json.loads(RESULTS_V2.read_text())
    if not res["decision"]["ship"] and not args.force:
        print("[v2] ship criteria not met; not exporting (use --force to override)")
        return
    data = Path(args.data)
    F, X, Y, folds, groups = q.load_all(args)
    M = load_mix(data)
    tr = M["plan_set"] == "train"
    Ygated = mixture_labels(M, "gated")
    Xa = np.vstack([X, M["X"][tr]])
    m, info = fit_head_v2b(X, Y, folds, M["X"][tr], Ygated[tr], M["plan_fold"][tr].astype(int))
    f32 = np.float32
    arrays = {
        "format": np.array("thicket-qc-head/1"),
        "version": np.array("qc_head_v2"),
        "categories": np.array(q.CATEGORIES),
        "category_kind": np.array([q.CATEGORY_KIND[c] for c in q.CATEGORIES]),
        "pooling": np.array("mean_max"),
        "recording_pooling": np.array(q.RECORDING_POOLING),
        "segment_windows": np.array(q.SEGMENT_WINDOWS, dtype=np.int32),
        "segment_quantile": np.array(q.SEGMENT_QUANTILE, dtype=f32),
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
        "train_hop_seconds": np.array(q.HOP_SECONDS, dtype=f32),
        "created": np.array(date.today().isoformat()),
        "license": np.array("CC BY-NC-SA 4.0"),
    }
    np.savez_compressed(ARTIFACT_V2, **arrays)
    sha = hashlib.sha256(ARTIFACT_V2.read_bytes()).hexdigest()
    from thicket.models.qc_head import QCHead

    head = QCHead.load(ARTIFACT_V2)
    ref = q.predict_proba(m, Xa)
    bounds = q.clip_bounds(F)
    diffs = [
        float(
            np.abs(
                head.predict_array(F["embedding"][bounds[c] : bounds[c + 1]], mode="whole") - ref[c]
            ).max()
        )
        for c in range(0, 2000, 7)
    ]
    rng = np.random.default_rng(SEED)
    for _ in range(20):
        E = F["embedding"][rng.choice(len(F["embedding"]), 12, replace=False)]
        want = q.recording_scores(m, E)[f"segment_top{int(q.SEGMENT_QUANTILE * 100)}"]
        diffs.append(float(np.abs(head.predict_array(E) - want).max()))
    parity = max(diffs)
    if parity > 1e-4:
        raise RuntimeError(f"backend parity check failed: {parity}")
    Po = ek.sigmoid(m["platt_a"] * info["oof_logits"] + m["platt_b"])
    export = {
        "created": date.today().isoformat(),
        "artifact": str(ARTIFACT_V2.relative_to(REPO))
        if ARTIFACT_V2.is_relative_to(REPO)
        else str(ARTIFACT_V2),
        "artifact_sha256": sha,
        "artifact_bytes": ARTIFACT_V2.stat().st_size,
        "per_category_choice": info["per_category"],
        "oof_macro_ap_all_folds": q.macro_ap(info["oof_labels"], Po),
        "n_training_rows": {"clean": int(len(Y)), "mixtures": int(tr.sum())},
        "thresholds_f1": dict(zip(q.CATEGORIES, m["thr_f1"].round(4).tolist(), strict=True)),
        "thresholds_p90": dict(zip(q.CATEGORIES, m["thr_p90"].round(4).tolist(), strict=True)),
        "recording_pooling": q.RECORDING_POOLING,
        "segment_windows": q.SEGMENT_WINDOWS,
        "segment_quantile": q.SEGMENT_QUANTILE,
        "backend_parity_max_abs_diff": parity,
        "forced": bool(args.force and not res["decision"]["ship"]),
    }
    update_results("export", export)
    write_card_json(json.loads(RESULTS_V2.read_text()))
    print(f"[v2] wrote {ARTIFACT_V2} ({export['artifact_bytes']} bytes, parity {parity:.1e})")


def write_card_json(res: dict) -> None:
    exp = res["export"]
    C2 = res["clean"]["v2_f1"]
    Eb = res["mixtures_eval"]["backend"]["v2"]
    pcb = res["pooling_check_v2"]["backgrounds"]["biophony"]["rules"]["backend"]

    def trip(t):
        return [round(float(v), 4) for v in t]

    card = {
        "name": "Thicket soundscape QC head",
        "version": "qc_head_v2",
        "created": exp["created"],
        "status": "experimental; warnings only; not validated on field recordings",
        "supersedes": "qc_head_v1",
        "artifact": "qc_head_v2.npz",
        "artifact_sha256": exp["artifact_sha256"],
        "model_card": "docs/model-cards/qc-soundscape-v2.md",
        "report": "ml/reports/qc_esc50_v2.md",
        "intended_use": "Flag likely contamination (rain, wind, thunder, water, engines and machinery, human non-speech sounds, domestic animals) in field audio, as warnings next to BirdNET results. Not a species classifier and not a detector of weather events. The bird, insect and frog scores are for internal diagnostics only until validated on field audio.",
        "warning_rule_used_by_backend": "score > max(0.5, thresholds[category]) for categories whose kind is geophony, anthropophony or biophony_non_target",
        "inputs": "BirdNET v2.4 1024-d embeddings of 3 s windows at 48 kHz (thicket.models.birdnet_runtime.BirdNETRuntime.infer).",
        "pooling": "concat(mean, max) over the windows of a segment (2 windows); recording score per category = k-th highest segment probability, k = max(1, ceil(0.25 * n_segments)).",
        "categories": {
            c: {"kind": q.CATEGORY_KIND[c], "esc50_classes": q.CATEGORY_MAP[c]}
            for c in q.CATEGORIES
        },
        "thresholds": exp["thresholds_f1"],
        "thresholds_high_precision": exp["thresholds_p90"],
        "backbone": {
            "name": "BirdNET GLOBAL 6K V2.4 (FP32 TFLite)",
            "sha256": res["config"]["birdnet_sha256"],
            "license": "CC BY-NC-SA 4.0",
        },
        "training_data": {
            "name": "ESC-50 clips plus synthetic mixtures of ESC-50 clips",
            "url": "https://github.com/karolpiczak/ESC-50",
            "license": "CC BY-NC 3.0 (dataset as a whole)",
            "clean_clips": exp["n_training_rows"]["clean"],
            "synthetic_mixtures": exp["n_training_rows"]["mixtures"],
            "notes": "Mixtures add two curated 5 s clips from the same ESC-50 fold at a random SNR in [-10, 15] dB. They are synthetic, not field recordings.",
        },
        "evaluation": {
            "protocol": "ESC-50 official 5 folds; mixtures built within each fold; hyperparameters, Platt scaling and thresholds chosen on training folds only; 95% CIs by cluster bootstrap over source recordings (two-way over base and contaminant sources for mixtures)",
            "clean_macro": {k: trip(v) for k, v in C2["macro"].items()},
            "clean_per_category": {
                c: {
                    m: trip(C2["per_class"][c][m])
                    for m in ("precision", "recall", "f1", "ap", "auc")
                }
                for c in q.CATEGORIES
            },
            "mixture_detection_backend_rule": {
                k: trip(v["detected"]) for k, v in Eb.items() if k.startswith("all@")
            },
            "clean_bio_false_contamination_flag_backend_rule": trip(
                res["clean_bio_false_contamination_flag"]["backend"]["v2"]
            ),
            "long_recording_check_backend_rule": {
                "detected_contamination_half_of_30s": round(
                    pcb["detection_rate"]["3"]["mean_over_categories"]["segment_top25"], 3
                ),
                "detected_contamination_all_of_30s": round(
                    pcb["detection_rate"]["6"]["mean_over_categories"]["segment_top25"], 3
                ),
                "false_warning_clean_30s": round(
                    pcb["false_flag_rate"]["6"]["segment_top25"]["any_contamination"], 3
                ),
                "false_warning_clean_60s": round(
                    pcb["false_flag_rate"]["12"]["segment_top25"]["any_contamination"], 3
                ),
            },
        },
        "limitations": [
            "Trained and evaluated on ESC-50 clips and synthetic mixtures of them; no field validation.",
            "Mixtures add two close-range clips digitally; real overlap (distance, reverberation, recorder noise) is different.",
            "Short contamination bursts are not flagged at the recording level by design; use predict_segments.",
            "The bird, insect and frog categories come from few ESC-50 classes and are not species or region specific.",
        ],
        "license": "CC BY-NC-SA 4.0 (derived from BirdNET v2.4 embeddings, CC BY-NC-SA 4.0, and ESC-50, CC BY-NC 3.0). Non-commercial use only.",
    }
    CARD_JSON_V2.write_text(json.dumps(card, indent=1) + "\n")


def cmd_smoke(args: argparse.Namespace) -> None:
    from thicket.models.birdnet_runtime import BirdNETRuntime, frame_windows
    from thicket.models.qc_head import QCHead
    from thicket.services.audio_io import decode

    if not ARTIFACT_V2.exists():
        print("[v2] no v2 artifact; skipping smoke")
        return
    rt = BirdNETRuntime(num_threads=args.threads)
    x, _ = decode(q.FIXTURE, target_sr=48000)
    win, _ = frame_windows(x)
    _, emb = rt.infer(win)
    out = {"file": str(q.FIXTURE.relative_to(REPO)), "n_windows": int(len(win))}
    for name, path in (("v1", q.ARTIFACT), ("v2", ARTIFACT_V2)):
        h = QCHead.load(path)
        pr = h.predict(emb)
        out[name] = {
            "probabilities": {c: round(v, 4) for c, v in pr.items()},
            "backend_warnings": [
                c
                for c, v in pr.items()
                if h.category_kind[c] != "biophony"
                and v > max(q.BACKEND_MIN_PROBABILITY, h.threshold(c))
            ],
        }
    update_results("fixture_smoke", out)
    print(json.dumps(out, indent=1))


def cmd_report(args: argparse.Namespace) -> None:
    import esc50_qc_mix_report

    res = json.loads(RESULTS_V2.read_text())
    figures(res)
    if "export" in res:
        write_card_json(res)
    esc50_qc_mix_report.write_all(res)


def cmd_all(args: argparse.Namespace) -> None:
    cmd_mixfeatures(args)
    for variant, fn in (("v2a", cmd_evaluate), ("v2b", cmd_diagnose), ("v2b", cmd_evaluate)):
        args.variant = variant
        fn(args)
    for fn in (cmd_export, cmd_smoke, cmd_report):
        fn(args)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "stage", choices=["mixfeatures", "evaluate", "diagnose", "export", "smoke", "report", "all"]
    )
    ap.add_argument("--data", default="/home/claude/data/esc50")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument(
        "--force",
        action="store_true",
        help="recompute cached mixtures / export even if criteria fail",
    )
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument(
        "--variant",
        default="v2b",
        choices=["v2a", "v2b"],
        help="v2a: first recipe (kept as a record); v2b: shipped candidate",
    )
    args = ap.parse_args()
    {
        "mixfeatures": cmd_mixfeatures,
        "evaluate": cmd_evaluate,
        "diagnose": cmd_diagnose,
        "export": cmd_export,
        "smoke": cmd_smoke,
        "report": cmd_report,
        "all": cmd_all,
    }[args.stage](args)


if __name__ == "__main__":
    main()

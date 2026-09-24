"""Shared evaluation helpers for Thicket ML scripts.

Everything here is plain NumPy (plus scikit-learn for AP / ROC AUC, which are
training-side dependencies only). Used by ``esc50_qc.py`` and
``frog_insect.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p) - np.log1p(-p)


# ---------------------------------------------------------------- basic metrics


def _tie_groups(y: np.ndarray, s: np.ndarray):
    order = np.argsort(-s, kind="stable")
    ss, yy = s[order], y[order]
    tp = np.cumsum(yy)
    fp = np.cumsum(1 - yy)
    last = np.r_[ss[1:] != ss[:-1], True]
    return tp[last], fp[last], ss[last]


def safe_ap(y: np.ndarray, s: np.ndarray) -> float:
    """Average precision (step-wise, same definition as scikit-learn)."""
    y = np.asarray(y).astype(np.int64)
    npos = int(y.sum())
    if npos == 0:
        return float("nan")
    tp, fp, _ = _tie_groups(y, np.asarray(s, dtype=np.float64))
    prec = tp / (tp + fp)
    rec = tp / npos
    return float(np.sum(np.diff(np.r_[0.0, rec]) * prec))


def safe_auc(y: np.ndarray, s: np.ndarray) -> float:
    """ROC AUC via the Mann-Whitney statistic with average ranks for ties."""
    from scipy.stats import rankdata

    y = np.asarray(y).astype(bool)
    npos, nneg = int(y.sum()), int((~y).sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    r = rankdata(np.asarray(s, dtype=np.float64))
    return float((r[y].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def sk_ap(y, s) -> float:  # reference implementation, used in tests
    return float(average_precision_score(y, s))


def sk_auc(y, s) -> float:  # reference implementation, used in tests
    return float(roc_auc_score(y, s))


def prf(y: np.ndarray, pred: np.ndarray) -> tuple[float, float, float]:
    """Precision, recall, F1 for binary arrays. Undefined precision -> 0."""
    y = np.asarray(y).astype(bool)
    pred = np.asarray(pred).astype(bool)
    tp = float(np.sum(y & pred))
    fp = float(np.sum(~y & pred))
    fn = float(np.sum(y & ~pred))
    p = tp / (tp + fp) if tp + fp > 0 else 0.0
    r = tp / (tp + fn) if tp + fn > 0 else 0.0
    f = 2 * p * r / (p + r) if p + r > 0 else 0.0
    return p, r, f


def choose_threshold(
    y: np.ndarray,
    s: np.ndarray,
    mode: str = "f1",
    target_precision: float = 0.9,
    min_threshold: float = 0.05,
) -> float:
    """Pick a decision threshold on *training / validation* scores only.

    mode="f1": the score cut that maximizes F1 (ties -> higher threshold).
    mode="precision": the lowest cut whose precision >= target_precision
    (maximizes recall under the precision constraint). If the target is never
    reached, return the cut with the highest precision among cuts that keep at
    least one positive prediction.
    """
    y = np.asarray(y).astype(bool)
    s = np.asarray(s, dtype=np.float64)
    if y.sum() == 0:
        return 1.0
    order = np.argsort(-s, kind="stable")
    ss = s[order]
    yy = y[order]
    tp = np.cumsum(yy)
    fp = np.cumsum(~yy)
    # Only evaluate at the last index of each run of tied scores.
    last = np.r_[ss[1:] != ss[:-1], True]
    tp, fp, cut = tp[last], fp[last], ss[last]
    prec = tp / np.maximum(tp + fp, 1)
    rec = tp / y.sum()
    keep = cut >= min_threshold
    if not keep.any():
        return float(min_threshold)
    tp, fp, cut, prec, rec = tp[keep], fp[keep], cut[keep], prec[keep], rec[keep]
    if mode == "f1":
        f1 = np.where(prec + rec > 0, 2 * prec * rec / np.maximum(prec + rec, 1e-12), 0.0)
        best = np.flatnonzero(f1 >= f1.max() - 1e-12)
        return float(cut[best].max())
    if mode == "precision":
        ok = np.flatnonzero(prec >= target_precision)
        if ok.size:
            return float(cut[ok].min())
        return float(cut[int(np.argmax(prec))])
    raise ValueError(mode)


# ---------------------------------------------------------------- bootstrap


def cluster_bootstrap(
    fn: Callable[[np.ndarray], float],
    groups: np.ndarray,
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Point estimate and percentile CI for ``fn(indices)``.

    Resamples whole groups (e.g. source recordings or observers) with
    replacement so correlated items stay together. Replicates where ``fn``
    returns NaN (for example no positives drawn) are dropped.
    """
    groups = np.asarray(groups)
    uniq, inv = np.unique(groups, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    counts = np.bincount(inv, minlength=len(uniq))
    starts = np.r_[0, np.cumsum(counts)[:-1]]
    point = fn(np.arange(len(groups)))
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        sizes = counts[pick]
        offs = np.arange(sizes.sum()) - np.repeat(np.cumsum(sizes) - sizes, sizes)
        idx = order[np.repeat(starts[pick], sizes) + offs]
        v = fn(idx)
        if np.isfinite(v):
            vals.append(v)
    if not vals:
        return float(point), float("nan"), float("nan")
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(point), float(lo), float(hi)


# ---------------------------------------------------------------- calibration


def reliability(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> dict:
    """Equal-width reliability table and expected calibration error (ECE)."""
    y = np.asarray(y, dtype=np.float64).ravel()
    p = np.asarray(p, dtype=np.float64).ravel()
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    conf, acc, count = [], [], []
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        n = int(m.sum())
        count.append(n)
        if n == 0:
            conf.append(float("nan"))
            acc.append(float("nan"))
            continue
        c, a = float(p[m].mean()), float(y[m].mean())
        conf.append(c)
        acc.append(a)
        ece += n / len(p) * abs(a - c)
    return {
        "edges": edges.tolist(),
        "confidence": conf,
        "accuracy": acc,
        "count": count,
        "ece": float(ece),
    }


def fit_platt(z: np.ndarray, y: np.ndarray, l2: float = 1e-3) -> tuple[float, float]:
    """Fit p = sigmoid(a * z + b) on (z, y) by L-BFGS. Returns (a, b).

    Uses Platt's smoothed targets so separable data does not push the slope to
    infinity, plus a tiny ridge pulling ``a`` toward 1.
    """
    from scipy.optimize import minimize

    z = np.asarray(z, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n_pos, n_neg = y.sum(), len(y) - y.sum()
    t = np.where(y > 0.5, (n_pos + 1) / (n_pos + 2), 1 / (n_neg + 2))

    def fg(w: np.ndarray) -> tuple[float, np.ndarray]:
        u = w[0] * z + w[1]
        loss = float(np.sum(np.logaddexp(0.0, u) - t * u)) + 0.5 * l2 * (w[0] - 1.0) ** 2
        g = sigmoid(u) - t
        return loss, np.array([float(g @ z) + l2 * (w[0] - 1.0), float(g.sum())])

    res = minimize(fg, np.array([1.0, 0.0]), jac=True, method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])


def fit_temperature(z: np.ndarray, y: np.ndarray) -> float:
    """Single temperature T for multi-label logits: p = sigmoid(z / T)."""
    from scipy.optimize import minimize_scalar

    z = np.asarray(z, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()

    def nll(log_t: float) -> float:
        p = np.clip(sigmoid(z / np.exp(log_t)), 1e-7, 1 - 1e-7)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    res = minimize_scalar(nll, bounds=(np.log(0.05), np.log(20.0)), method="bounded")
    return float(np.exp(res.x))


# ---------------------------------------------------------------- helpers


def per_class_table(
    Y: np.ndarray,
    S: np.ndarray,
    D: np.ndarray,
    names: Sequence[str],
    groups: np.ndarray,
    n_boot: int = 1000,
    seed: int = 0,
) -> dict:
    """Per-class precision / recall / F1 of binary decisions ``D`` plus AP and
    ROC AUC of scores ``S``, each with a cluster-bootstrap 95% CI, and macro /
    micro aggregates. ``Y``, ``S``, ``D`` are (n_items, n_classes)."""
    Y = np.asarray(Y).astype(bool)
    D = np.asarray(D).astype(bool)
    S = np.asarray(S, dtype=np.float64)
    out: dict = {"per_class": {}, "n_boot": n_boot, "ci": "95% percentile, cluster bootstrap"}

    def pos_only(fn):
        return lambda y, s, d: fn(y, s, d) if y.sum() else np.nan

    metrics = {
        "precision": lambda y, s, d: prf(y, d)[0] if d.sum() else np.nan,
        "recall": pos_only(lambda y, s, d: prf(y, d)[1]),
        "f1": pos_only(lambda y, s, d: prf(y, d)[2]),
        "ap": lambda y, s, d: safe_ap(y, s),
        "auc": lambda y, s, d: safe_auc(y, s),
    }
    for k, name in enumerate(names):
        row = {"n_pos": int(Y[:, k].sum()), "n_flagged": int(D[:, k].sum())}
        for j, (m, fn) in enumerate(metrics.items()):
            row[m] = cluster_bootstrap(
                lambda i, k=k, fn=fn: fn(Y[i, k], S[i, k], D[i, k]),
                groups,
                n_boot=n_boot,
                seed=seed + 10 * k + j,
            )
        out["per_class"][name] = row

    def macro(fn):
        def f(i):
            vals = [fn(Y[i, k], S[i, k], D[i, k]) for k in range(len(names))]
            vals = [v for v in vals if np.isfinite(v)]
            return float(np.mean(vals)) if vals else float("nan")

        return f

    out["macro"] = {
        m: cluster_bootstrap(macro(fn), groups, n_boot, seed + 1000 + j)
        for j, (m, fn) in enumerate(metrics.items())
    }
    out["micro"] = {
        "precision": cluster_bootstrap(
            lambda i: prf(Y[i].ravel(), D[i].ravel())[0], groups, n_boot, seed + 2000
        ),
        "recall": cluster_bootstrap(
            lambda i: prf(Y[i].ravel(), D[i].ravel())[1], groups, n_boot, seed + 2001
        ),
        "f1": cluster_bootstrap(
            lambda i: prf(Y[i].ravel(), D[i].ravel())[2], groups, n_boot, seed + 2002
        ),
        "ap": cluster_bootstrap(
            lambda i: safe_ap(Y[i].ravel(), S[i].ravel()), groups, n_boot, seed + 2003
        ),
    }
    return out


def fmt_ci(t: Sequence[float], digits: int = 3) -> str:
    """Format (point, lo, hi) as '0.912 (0.881 to 0.940)'."""
    p, lo, hi = t
    if not np.isfinite(p):
        return "n/a"
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return f"{p:.{digits}f}"
    return f"{p:.{digits}f} ({lo:.{digits}f} to {hi:.{digits}f})"


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    """Proportion k/n with a 95% Wilson score interval: [p, lo, hi, k, n]."""
    if n == 0:
        return [float("nan"), float("nan"), float("nan"), 0, 0]
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [
        float(p),
        float(max(0.0, centre - half)),
        float(min(1.0, centre + half)),
        int(k),
        int(n),
    ]

"""Small, deterministic linear models in NumPy + SciPy L-BFGS.

Objectives match scikit-learn's LogisticRegression convention:
    C * sum_i loss_i + 0.5 * ||W||^2      (bias not penalized)
so C values are comparable with sklearn. Full-batch and deterministic. The
data products run in float32 (3x faster BLAS on CPU); parameters, losses and
gradients are accumulated in float64. L-BFGS stops at a relative objective
change of 1e-7 (``FTOL``); on ESC-50 this matched full convergence to 4
decimals of held-out accuracy / macro AP.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

FTOL = 1e-7


def _mm(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    return (A @ B.astype(np.float32, copy=False)).astype(np.float64)


@dataclass
class Standardizer:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, X: np.ndarray, eps: float = 1e-6) -> Standardizer:
        X = np.asarray(X, dtype=np.float64)
        return cls(X.mean(axis=0), np.maximum(X.std(axis=0), eps))

    def __call__(self, X: np.ndarray) -> np.ndarray:
        return (np.asarray(X, dtype=np.float64) - self.mean) / self.std


def _log1pexp(z: np.ndarray) -> np.ndarray:
    return np.logaddexp(0.0, z)


def fit_multilabel(
    X: np.ndarray,
    Y: np.ndarray,
    C: float,
    sample_weight: np.ndarray | None = None,
    max_iter: int = 500,
    W0: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Independent logistic regressions for each column of Y (multi-label).

    X: (n, d) standardized features. Y: (n, k) in {0, 1} (soft targets allowed).
    Returns W (d, k), b (k,).
    """
    X = np.ascontiguousarray(X, dtype=np.float32)
    XT = np.ascontiguousarray(X.T)
    Y = np.asarray(Y, dtype=np.float64)
    n, d = X.shape
    k = Y.shape[1]
    sw = np.ones(n) if sample_weight is None else np.asarray(sample_weight, dtype=np.float64)

    def fg(theta: np.ndarray) -> tuple[float, np.ndarray]:
        W = theta[: d * k].reshape(d, k)
        b = theta[d * k :]
        Z = _mm(X, W) + b
        # BCE with logits: log(1 + e^z) - y z
        loss = float(np.sum(sw[:, None] * (_log1pexp(Z) - Y * Z)))
        G = sw[:, None] * (1.0 / (1.0 + np.exp(-Z)) - Y)
        gW = C * _mm(XT, G) + W
        gb = C * G.sum(axis=0)
        return C * loss + 0.5 * float(np.sum(W * W)), np.concatenate([gW.ravel(), gb])

    theta0 = np.zeros(d * k + k)
    if W0 is not None:
        theta0[: d * k] = W0.ravel()
    res = minimize(
        fg, theta0, jac=True, method="L-BFGS-B", options={"maxiter": max_iter, "ftol": FTOL}
    )
    W = res.x[: d * k].reshape(d, k)
    b = res.x[d * k :]
    return W, b


def fit_softmax(
    X: np.ndarray, y: np.ndarray, n_classes: int, C: float, max_iter: int = 500
) -> tuple[np.ndarray, np.ndarray]:
    """Multinomial logistic regression. Returns W (d, n_classes), b (n_classes,)."""
    X = np.ascontiguousarray(X, dtype=np.float32)
    XT = np.ascontiguousarray(X.T)
    n, d = X.shape
    k = n_classes
    Yoh = np.zeros((n, k))
    Yoh[np.arange(n), y] = 1.0

    def fg(theta: np.ndarray) -> tuple[float, np.ndarray]:
        W = theta[: d * k].reshape(d, k)
        b = theta[d * k :]
        Z = _mm(X, W) + b
        Z = Z - Z.max(axis=1, keepdims=True)
        lse = np.log(np.exp(Z).sum(axis=1))
        loss = float(np.sum(lse - np.sum(Yoh * Z, axis=1)))
        P = np.exp(Z - lse[:, None])
        G = P - Yoh
        gW = C * _mm(XT, G) + W
        gb = C * G.sum(axis=0)
        return C * loss + 0.5 * float(np.sum(W * W)), np.concatenate([gW.ravel(), gb])

    res = minimize(
        fg,
        np.zeros(d * k + k),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": max_iter, "ftol": FTOL},
    )
    return res.x[: d * k].reshape(d, k), res.x[d * k :]


def fit_mlp(
    X: np.ndarray,
    Y: np.ndarray,
    hidden: int,
    C: float,
    seed: int = 0,
    max_iter: int = 400,
    sample_weight: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One hidden ReLU layer, multi-label sigmoid outputs, full-batch L-BFGS.

    Returns W1 (d, h), b1 (h,), W2 (h, k), b2 (k,). Seeded init.
    """
    X = np.ascontiguousarray(X, dtype=np.float32)
    XT = np.ascontiguousarray(X.T)
    Y = np.asarray(Y, dtype=np.float64)
    n, d = X.shape
    k = Y.shape[1]
    h = hidden
    sw = np.ones(n) if sample_weight is None else np.asarray(sample_weight, dtype=np.float64)
    rng = np.random.default_rng(seed)
    W1 = rng.normal(0, np.sqrt(2.0 / d), (d, h))
    W2 = rng.normal(0, np.sqrt(1.0 / h), (h, k))
    sizes = [d * h, h, h * k, k]

    def unpack(t):
        o = np.cumsum([0, *sizes])
        return (
            t[o[0] : o[1]].reshape(d, h),
            t[o[1] : o[2]],
            t[o[2] : o[3]].reshape(h, k),
            t[o[3] : o[4]],
        )

    def fg(t):
        A, a, B, bb = unpack(t)
        H = _mm(X, A) + a
        R = np.maximum(H, 0.0)
        Z = R @ B + bb
        loss = float(np.sum(sw[:, None] * (_log1pexp(Z) - Y * Z)))
        G = sw[:, None] * (1.0 / (1.0 + np.exp(-Z)) - Y)
        gB = C * (R.T @ G) + B
        gbb = C * G.sum(axis=0)
        GH = (G @ B.T) * (H > 0)
        gA = C * _mm(XT, GH) + A
        ga = C * GH.sum(axis=0)
        reg = 0.5 * float(np.sum(A * A) + np.sum(B * B))
        return C * loss + reg, np.concatenate([gA.ravel(), ga, gB.ravel(), gbb])

    t0 = np.concatenate([W1.ravel(), np.zeros(h), W2.ravel(), np.zeros(k)])
    res = minimize(fg, t0, jac=True, method="L-BFGS-B", options={"maxiter": max_iter, "ftol": FTOL})
    return unpack(res.x)

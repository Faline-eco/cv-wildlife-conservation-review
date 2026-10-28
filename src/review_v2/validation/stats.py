"""Small statistics helpers for the validation package."""
import math

import numpy as np


def wilson(k, n, z=1.96):
    """Share k/n with a Wilson 95% interval."""
    if n == 0:
        return {"k": k, "n": n, "p": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": int(k), "n": int(n), "p": p, "lo": c - h, "hi": c + h}


def kappa(a, b):
    """Cohen's kappa of two equal-length label sequences."""
    a, b = list(a), list(b)
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def binary(pred, gold):
    """Sensitivity, specificity, precision, F1 and kappa for boolean arrays."""
    pred, gold = np.asarray(pred, bool), np.asarray(gold, bool)
    tp, fp = int((pred & gold).sum()), int((pred & ~gold).sum())
    fn, tn = int((~pred & gold).sum()), int((~pred & ~gold).sum())
    sens, spec, prec = wilson(tp, tp + fn), wilson(tn, tn + fp), wilson(tp, tp + fp)
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "sensitivity": sens, "specificity": spec,
            "precision": prec, "f1": f1, "kappa": kappa(pred, gold)}


def bootstrap_prf(per_paper, n=2000, seed=0):
    """Micro precision / recall / F1 with paper-level bootstrap intervals.
    per_paper: list of (tp, fp, fn) tuples, one per paper."""
    a = np.asarray(per_paper, float).reshape(-1, 3)
    rng = np.random.default_rng(seed)

    def prf(x):
        tp, fp, fn = x.sum(0)
        p = tp / (tp + fp) if tp + fp else np.nan
        r = tp / (tp + fn) if tp + fn else np.nan
        return p, r, (2 * p * r / (p + r) if p + r else np.nan)
    point = prf(a)
    boots = np.array([prf(a[rng.integers(0, len(a), len(a))]) for _ in range(n)])
    lo, hi = np.nanpercentile(boots, 2.5, axis=0), np.nanpercentile(boots, 97.5, axis=0)
    return {k: {"p": point[i], "lo": lo[i], "hi": hi[i]} for i, k in enumerate(("precision", "recall", "f1"))} | \
        {"papers": len(a), "tp": int(a[:, 0].sum()), "fp": int(a[:, 1].sum()), "fn": int(a[:, 2].sum())}

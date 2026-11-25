"""Small statistics helpers (standard library + numpy only, no scipy)."""
from __future__ import annotations

import math

import numpy as np


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def wilson_interval(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n. Behaves well for small n and k near 0 (typical for CTR)."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def two_proportion_ztest(k1: float, n1: float, k2: float, n2: float) -> tuple[float, float]:
    """Two-sided z-test for H0: p1 == p2 with a pooled variance. Returns (z, p_value).

    Treats every impression as an independent Bernoulli trial, which is optimistic: impressions from the same
    users and sessions are correlated, so p-values are best used as a screening tool (see references/pitfalls.md).
    """
    if n1 <= 0 or n2 <= 0:
        return (float("nan"), float("nan"))
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return (0.0, 1.0)
    z = (p1 - p2) / se
    return (z, 2 * (1 - normal_cdf(abs(z))))


def benjamini_hochberg(pvalues: list[float] | np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values (q-values). NaNs stay NaN and are ignored in the ranking.

    Testing hundreds of pages at alpha=0.05 produces dozens of false 'significant' changes by chance alone;
    controlling the false discovery rate is the minimum honest treatment.
    """
    p = np.asarray(pvalues, dtype=float)
    q = np.full_like(p, np.nan)
    ok = ~np.isnan(p)
    m = ok.sum()
    if m == 0:
        return q
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx])]
    ranked = p[order] * m / (np.arange(m) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q[order] = np.clip(ranked, 0, 1)
    return q


def mad_scale(x: np.ndarray) -> float:
    """Robust standard-deviation estimate: 1.4826 * median absolute deviation."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if x.size == 0:
        return float("nan")
    return 1.4826 * float(np.median(np.abs(x - np.median(x))))

"""Period-over-period comparison with statistical tests instead of raw deltas."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import benjamini_hochberg, two_proportion_ztest, wilson_interval


def aggregate(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """One row per `key` with clicks, impressions and impression-weighted average position."""
    g = df.copy()
    g["_w"] = g["position"] * g["impressions"] if "position" in g.columns else 0.0
    out = g.groupby(key, as_index=False).agg(clicks=("clicks", "sum"), impressions=("impressions", "sum"), _w=("_w", "sum"))
    out["position"] = (out["_w"] / out["impressions"].where(out["impressions"] > 0)) if "position" in df.columns else np.nan
    return out.drop(columns="_w")


def compare_periods(current: pd.DataFrame, previous: pd.DataFrame, key: str = "page", min_impressions: int = 100,
                    alpha: float = 0.05) -> dict:
    """Compare two periods per page/query and for the whole site.

    For rows with >= min_impressions in BOTH periods, tests whether CTR really changed (two-proportion z-test) and
    corrects the p-values across all tested rows (Benjamini-Hochberg). Each row also gets a clicks decomposition:
      impressions_effect = (impr_now - impr_before) * ctr_before        (more/less visibility)
      ctr_effect         = impr_now * (ctr_now - ctr_before)            (better/worse snippet or rank)
    which add up to the clicks delta, so you can tell WHY a page moved.
    Verdicts: up / down (significant after correction), inconclusive, low_volume, new, lost.
    """
    cur, prev = aggregate(current, key), aggregate(previous, key)
    m = cur.merge(prev, on=key, how="outer", suffixes=("", "_prev"))
    for c in ("clicks", "impressions", "clicks_prev", "impressions_prev"):
        m[c] = m[c].fillna(0)
    m["ctr"] = m["clicks"] / m["impressions"].where(m["impressions"] > 0)
    m["ctr_prev"] = m["clicks_prev"] / m["impressions_prev"].where(m["impressions_prev"] > 0)
    m["clicks_delta"] = m["clicks"] - m["clicks_prev"]
    m["impressions_effect"] = (m["impressions"] - m["impressions_prev"]) * m["ctr_prev"].fillna(0)
    m["ctr_effect"] = m["impressions"] * (m["ctr"].fillna(0) - m["ctr_prev"].fillna(0)).where(m["impressions_prev"] > 0, 0)
    m.loc[m["impressions_prev"] == 0, "impressions_effect"] = m["clicks_delta"]  # brand-new rows: all visibility
    m["position_delta"] = m["position"] - m["position_prev"]  # > 0 means worse

    testable = (m["impressions"] >= min_impressions) & (m["impressions_prev"] >= min_impressions)
    z, p = np.full(len(m), np.nan), np.full(len(m), np.nan)
    ci_lo, ci_hi = np.full(len(m), np.nan), np.full(len(m), np.nan)
    for i in np.where(testable)[0]:
        r = m.iloc[i]
        z[i], p[i] = two_proportion_ztest(r["clicks"], r["impressions"], r["clicks_prev"], r["impressions_prev"])
        ci_lo[i], ci_hi[i] = wilson_interval(r["clicks"], r["impressions"])
    m["z"], m["p_value"] = z, p
    m["q_value"] = benjamini_hochberg(p)
    m["ctr_ci_low"], m["ctr_ci_high"] = ci_lo, ci_hi

    def verdict(r) -> str:
        if r["impressions_prev"] == 0 and r["impressions"] > 0:
            return "new"
        if r["impressions"] == 0 and r["impressions_prev"] > 0:
            return "lost"
        if np.isnan(r["q_value"]):
            return "low_volume"
        if r["q_value"] < alpha:
            return "up" if r["ctr"] > r["ctr_prev"] else "down"
        return "inconclusive"

    m["verdict"] = m.apply(verdict, axis=1)
    m = m.sort_values("clicks_delta", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)

    tc, ti, pc, pi = current["clicks"].sum(), current["impressions"].sum(), previous["clicks"].sum(), previous["impressions"].sum()
    zt, pt = two_proportion_ztest(tc, ti, pc, pi)
    overall = {
        "clicks": int(tc), "clicks_prev": int(pc), "clicks_delta": int(tc - pc),
        "impressions": int(ti), "impressions_prev": int(pi),
        "ctr": float(tc / ti) if ti else None, "ctr_prev": float(pc / pi) if pi else None,
        "ctr_p_value": None if np.isnan(pt) else float(pt),
        "impressions_effect": float((ti - pi) * (pc / pi)) if pi else None,
        "ctr_effect": float(ti * (tc / ti - pc / pi)) if ti and pi else None,
    }
    tested = int(testable.sum())
    return {"overall": overall, "rows": m, "tested_rows": tested, "alpha": alpha, "min_impressions": min_impressions,
            "expected_false_positives_without_correction": round(tested * alpha, 1)}

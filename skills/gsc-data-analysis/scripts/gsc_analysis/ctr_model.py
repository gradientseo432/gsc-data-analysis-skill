"""CTR-by-position benchmark built from the site's own data, and statistically underperforming queries."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .stats import wilson_interval


def is_brand(queries: pd.Series, brand_terms: list[str]) -> pd.Series:
    terms = [t.strip().lower() for t in brand_terms if t and t.strip()]
    if not terms:
        return pd.Series(False, index=queries.index)
    pattern = "|".join(pd.Series(terms).map(re.escape))
    return queries.fillna("").str.lower().str.contains(pattern, regex=True)


def build_benchmark(df: pd.DataFrame, brand_terms: list[str] | None = None, max_pos: int = 10, min_rows: int = 5) -> pd.DataFrame:
    """Pooled CTR per rounded average position (1..max_pos) using NON-brand queries only.

    Brand queries have a very high CTR at any position and would inflate the benchmark. A position bucket needs at
    least `min_rows` queries, otherwise its benchmark is left empty (no guessing).
    """
    d = df.copy()
    if brand_terms and "query" in d.columns:
        d = d[~is_brand(d["query"], brand_terms)]
    d["pos_bin"] = d["position"].round().clip(lower=1).astype(int)
    d = d[d["pos_bin"] <= max_pos]
    g = d.groupby("pos_bin").agg(rows=("clicks", "size"), clicks=("clicks", "sum"), impressions=("impressions", "sum")).reindex(range(1, max_pos + 1))
    g["rows"] = g["rows"].fillna(0).astype(int)
    g["benchmark_ctr"] = (g["clicks"] / g["impressions"]).where((g["rows"] >= min_rows) & (g["impressions"] > 0))
    lo_hi = [wilson_interval(c, i) if i and not np.isnan(i) else (np.nan, np.nan) for c, i in zip(g["clicks"], g["impressions"])]
    g["ci_low"], g["ci_high"] = [x[0] for x in lo_hi], [x[1] for x in lo_hi]
    return g.reset_index()


def underperformers(df: pd.DataFrame, bench: pd.DataFrame, brand_terms: list[str] | None = None,
                    min_impressions: int = 200, z: float = 1.96) -> pd.DataFrame:
    """Queries whose CTR is statistically BELOW the benchmark for their position.

    'Statistically below' = the upper Wilson bound of the query's own CTR is under the benchmark. A query with 40
    impressions and 0 clicks is NOT flagged (it could just be unlucky); one with 3,000 impressions at half the benchmark is.
    est_extra_clicks = impressions * (benchmark - observed CTR): the clicks at stake over the period, an upper-bound estimate.
    """
    d = df.copy()
    if brand_terms and "query" in d.columns:
        d = d[~is_brand(d["query"], brand_terms)]
    d["pos_bin"] = d["position"].round().clip(lower=1).astype(int)
    d = d.merge(bench[["pos_bin", "benchmark_ctr"]], on="pos_bin", how="inner").dropna(subset=["benchmark_ctr"])
    d = d[d["impressions"] >= min_impressions].copy()
    d["ctr"] = d["clicks"] / d["impressions"]
    d["ctr_ci_high"] = [wilson_interval(c, i, z)[1] for c, i in zip(d["clicks"], d["impressions"])]
    out = d[d["ctr_ci_high"] < d["benchmark_ctr"]].copy()
    out["est_extra_clicks"] = out["impressions"] * (out["benchmark_ctr"] - out["ctr"])
    cols = [c for c in ("query", "page", "position", "impressions", "clicks", "ctr", "benchmark_ctr", "est_extra_clicks") if c in out.columns]
    return out[cols].sort_values("est_extra_clicks", ascending=False).reset_index(drop=True)

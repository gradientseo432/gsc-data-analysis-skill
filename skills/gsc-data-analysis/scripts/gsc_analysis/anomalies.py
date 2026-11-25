"""Is that drop real or just noise? Robust anomaly detection on a daily series, adjusted for day-of-week."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import mad_scale


def daily_series(df: pd.DataFrame, metric: str = "clicks") -> pd.Series:
    """Sum `metric` per day over a continuous daily index (missing days become NaN, not zero: say so explicitly).

    metric: clicks | impressions | ctr | position (ctr = sum clicks / sum impressions; position is impression-weighted).
    """
    g = df.dropna(subset=["date"]).copy()
    g["date"] = g["date"].dt.normalize()
    if metric in ("clicks", "impressions"):
        s = g.groupby("date")[metric].sum()
    elif metric == "ctr":
        agg = g.groupby("date")[["clicks", "impressions"]].sum()
        s = agg["clicks"] / agg["impressions"].where(agg["impressions"] > 0)
    elif metric == "position":
        g["w"] = g["position"] * g["impressions"]
        agg = g.groupby("date")[["w", "impressions"]].sum()
        s = agg["w"] / agg["impressions"].where(agg["impressions"] > 0)
    else:
        raise ValueError("metric must be clicks, impressions, ctr or position")
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))


def weekday_factors(s: pd.Series) -> pd.Series:
    """Multiplicative day-of-week factors: median of each weekday / overall median (robust to spikes)."""
    overall = float(np.nanmedian(s.values))
    if not overall or np.isnan(overall):
        return pd.Series(1.0, index=range(7))
    f = s.groupby(s.index.day_of_week).median() / overall
    return f.reindex(range(7)).fillna(1.0).replace(0, 1.0)


def detect(s: pd.Series, window: int = 28, threshold: float = 3.5, min_history: int = 14) -> pd.DataFrame:
    """Flag days that deviate from the recent past by `threshold` robust standard deviations.

    1. Remove the weekday pattern (a normal Saturday dip is not an anomaly).
    2. For each day compare with the median of the previous `window` adjusted days.
    3. Scale by 1.4826 * MAD of that window (robust to earlier anomalies), floored at 5 % of the level so that a
       very flat series does not flag every tiny wiggle.
    Returns one row per flagged day: date, value, expected, z, direction, pct_vs_expected.
    """
    factors = weekday_factors(s)
    adj = s / s.index.day_of_week.map(factors).values
    rows = []
    vals = adj.values
    for i in range(len(s)):
        hist = vals[max(0, i - window):i]
        hist = hist[~np.isnan(hist)]
        if hist.size < min_history or np.isnan(vals[i]):
            continue
        base = float(np.median(hist))
        scale = max(mad_scale(hist), 0.05 * abs(base), 1e-9)
        z = (vals[i] - base) / scale
        if abs(z) >= threshold:
            expected = base * factors[s.index[i].day_of_week]
            rows.append({"date": s.index[i].date().isoformat(), "value": float(s.iloc[i]), "expected": round(expected, 2),
                         "z": round(float(z), 2), "direction": "up" if z > 0 else "down",
                         "pct_vs_expected": round((s.iloc[i] / expected - 1) * 100, 1) if expected else None})
    return pd.DataFrame(rows, columns=["date", "value", "expected", "z", "direction", "pct_vs_expected"])


def level_shift(s: pd.Series, recent: int = 7, baseline: int = 28) -> dict:
    """Has the level changed over the last `recent` days? Judged against the series' OWN history.

    ratio = mean of the last `recent` weekday-adjusted days / mean of the `baseline` days before them. The same
    ratio is computed at earlier points (excluding the current baseline window so an ongoing drop does not mask
    itself); the verdict is the percentile of today's ratio in that history, so 'unusual' means unusual FOR
    THIS SITE, not versus an arbitrary +/-10 % rule. Needs ~3 months of data.
    """
    factors = weekday_factors(s)
    adj = s / s.index.day_of_week.map(factors).values
    need = recent + baseline
    min_days = need + baseline + 20
    r = adj.rolling(recent, min_periods=recent).mean()
    b = adj.shift(recent).rolling(baseline, min_periods=baseline).mean()
    ratio = (r / b).dropna()
    if len(ratio) < baseline + 20:
        return {"verdict": "insufficient_history", "needed_days": min_days, "have_days": int(adj.notna().sum())}
    latest, hist = float(ratio.iloc[-1]), ratio.iloc[:-baseline].values
    pct = float((hist < latest).mean() * 100)
    verdict = "unusually_low" if pct <= 5 else "unusually_high" if pct >= 95 else "within_normal_range"
    return {"ratio": round(latest, 3), "change_pct": round((latest - 1) * 100, 1), "percentile_in_own_history": round(pct, 1),
            "verdict": verdict, "recent_days": recent, "baseline_days": baseline}

"""Data-quality checks. Run these BEFORE any analysis: most 'insights' from Search Console exports that turn out
wrong come from truncated exports, incomplete recent days or duplicated rows, not from the analysis itself."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

LEVELS = ("error", "warn", "info")
ROW_CAPS = {1000, 5000, 10000, 25000, 50000}  # typical export / API row limits
DIMENSIONS = ["date", "query", "page", "country", "device"]


def _f(level: str, code: str, message: str) -> dict:
    return {"level": level, "code": code, "message": message}


def check(df: pd.DataFrame, today: date | None = None, lag_days: int = 3, min_impressions: int = 10,
          label: str = "data") -> dict:
    """Return {'ok': bool, 'summary': {...}, 'findings': [{level, code, message}]}. ok is False when there are errors."""
    today = today or date.today()
    findings: list[dict] = []
    summary: dict = {"label": label, "rows": int(len(df))}

    missing = [c for c in ("clicks", "impressions") if c not in df.columns]
    if missing:
        findings.append(_f("error", "missing_columns", f"Missing required columns: {missing}. Found: {list(df.columns)}"))
        return {"ok": False, "summary": summary, "findings": findings}
    if df.empty:
        findings.append(_f("error", "empty", "The table has no rows."))
        return {"ok": False, "summary": summary, "findings": findings}

    summary.update(clicks=int(df["clicks"].sum()), impressions=int(df["impressions"].sum()))

    if (df["clicks"] < 0).any() or (df["impressions"] < 0).any():
        findings.append(_f("error", "negative_values", "Negative clicks or impressions found."))
    n_bad = int((df["clicks"] > df["impressions"]).sum())
    if n_bad:
        findings.append(_f("error", "clicks_gt_impressions", f"{n_bad} rows have more clicks than impressions."))

    dims = [c for c in DIMENSIONS if c in df.columns]
    if dims:
        dup = int(df.duplicated(subset=dims).sum())
        if dup:
            findings.append(_f("warn", "duplicate_rows", f"{dup} duplicated rows on {dims}: totals are inflated. "
                                                         "Drop or aggregate them before analysing."))

    if "ctr" in df.columns:
        calc = df["clicks"] / df["impressions"].where(df["impressions"] > 0)
        mismatch = int(((calc - df["ctr"]).abs() > 0.005).sum())
        if mismatch:
            findings.append(_f("warn", "ctr_mismatch", f"{mismatch} rows where exported CTR differs from clicks/impressions "
                                                       "by more than 0.5 points. The analysis recomputes CTR from clicks and impressions."))
    if "position" in df.columns and (df["position"] < 1).any():
        findings.append(_f("warn", "position_below_1", f"{int((df['position'] < 1).sum())} rows with position < 1."))

    if len(df) in ROW_CAPS:
        findings.append(_f("warn", "possible_truncation", f"Exactly {len(df)} rows: this looks like a row-limit cap. "
                                                         "The export is probably truncated (long tail missing), so totals and "
                                                         "shares are understated. Re-export with a higher limit or via the API."))

    low = float((df["impressions"] < min_impressions).mean())
    summary["share_rows_under_min_impressions"] = round(low, 3)
    if low > 0.5:
        findings.append(_f("info", "mostly_tiny_rows", f"{low:.0%} of rows have fewer than {min_impressions} impressions: "
                                                      "CTR and position for those rows are noise."))

    if "query" in df.columns:
        findings.append(_f("info", "anonymized_queries", "Search Console hides anonymized queries: query-level rows sum to "
                                                         "less than the property totals. Do not compare them with page-level or UI totals."))

    if "date" in df.columns and df["date"].notna().any():
        d = df["date"].dropna()
        first, last = d.min().date(), d.max().date()
        summary.update(date_from=first.isoformat(), date_to=last.isoformat())
        days = (last - first).days + 1
        present = d.dt.normalize().nunique()
        if present < days:
            findings.append(_f("warn", "date_gaps", f"{days - present} of {days} days have no rows between {first} and {last}. "
                                                    "Gaps break rolling statistics; zero-click days must be present as zeros."))
        if last > today - timedelta(days=lag_days):
            findings.append(_f("warn", "recent_days_incomplete", f"Data runs to {last}; the last {lag_days} days before today are "
                                                                 "still being finalized by Google. Exclude them or expect a fake drop."))
    summary["ok"] = not any(f["level"] == "error" for f in findings)
    return {"ok": summary["ok"], "summary": summary, "findings": findings}

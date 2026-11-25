"""Markdown report and (optional) charts. matplotlib is optional: without it the report simply has no images."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _pct(x, d=1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.{d}f}%"


def _table(df: pd.DataFrame, cols: list[str], fmt: dict | None = None, n: int = 10) -> str:
    if df is None or df.empty:
        return "_none_\n"
    fmt = fmt or {}
    d = df.head(n)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in d.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in fmt:
                cells.append(fmt[c](v))
            elif isinstance(v, (float, np.floating)):
                cells.append("n/a" if np.isnan(v) else f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def build_report(res: dict, title: str = "Search Console data analysis") -> str:
    out = [f"# {title}\n"]
    out.append("## 1. Data quality\n")
    for q in res.get("quality", []):
        s = q["summary"]
        out.append(f"**{s['label']}**: {s['rows']:,} rows" + (f", {s.get('date_from')} to {s.get('date_to')}" if s.get("date_from") else "") + "\n")
        if not q["findings"]:
            out.append("- No issues found.")
        for f in q["findings"]:
            icon = {"error": "[ERROR]", "warn": "[WARN]", "info": "[info]"}[f["level"]]
            out.append(f"- {icon} {f['message']}")
        out.append("")

    if "anomalies" in res:
        a = res["anomalies"]
        out.append(f"## 2. Anomalies in daily {a['metric']}\n")
        ls = a["level_shift"]
        if ls.get("verdict") == "insufficient_history":
            out.append(f"Level shift: not evaluated, needs about {ls['needed_days']} days of history (have {ls['have_days']}).\n")
        else:
            out.append(f"Last {ls['recent_days']} days vs the {ls['baseline_days']} before: **{ls['change_pct']:+.1f}%** "
                       f"(weekday-adjusted), percentile {ls['percentile_in_own_history']:.0f} in this site's own history: "
                       f"**{ls['verdict'].replace('_', ' ')}**.\n")
        d = a["days"]
        out.append(f"{len(d)} day(s) flagged at |z| >= {a['threshold']}.\n")
        out.append(_table(d, ["date", "value", "expected", "pct_vs_expected", "z", "direction"], n=15))

    if "compare" in res:
        c = res["compare"]
        o = c["overall"]
        out.append(f"## 3. Period comparison by {c['key']}\n")
        out.append(f"Clicks {o['clicks_prev']:,} -> {o['clicks']:,} (**{o['clicks_delta']:+,}**). Impressions "
                   f"{o['impressions_prev']:,} -> {o['impressions']:,}. CTR {_pct(o['ctr_prev'], 2)} -> {_pct(o['ctr'], 2)} "
                   f"(p = {o['ctr_p_value']:.3g}).\n")
        if o["impressions_effect"] is not None:
            out.append(f"Of the clicks change, **{o['impressions_effect']:+,.0f}** come from visibility (impressions) and "
                       f"**{o['ctr_effect']:+,.0f}** from CTR.\n")
        rows = c["rows"]
        counts = rows["verdict"].value_counts().to_dict()
        out.append(f"{c['tested_rows']} {c['key']}s had enough volume to test (>= {c['min_impressions']} impressions in both periods). "
                   f"Verdicts after false-discovery correction: {counts}. Without the correction about "
                   f"{c['expected_false_positives_without_correction']} would look 'significant' by chance alone.\n")
        cols = [c["key"], "clicks_prev", "clicks", "clicks_delta", "impressions_effect", "ctr_effect", "position_delta", "verdict"]
        f = {"clicks_prev": lambda v: f"{v:,.0f}", "clicks": lambda v: f"{v:,.0f}", "clicks_delta": lambda v: f"{v:+,.0f}",
             "impressions_effect": lambda v: f"{v:+,.0f}", "ctr_effect": lambda v: f"{v:+,.0f}",
             "position_delta": lambda v: "n/a" if pd.isna(v) else f"{v:+.1f}"}
        out.append("Biggest movers (by absolute clicks change):\n")
        out.append(_table(rows, cols, f, 12))
        sig = rows[rows["verdict"].isin(["up", "down"])]
        out.append(f"Statistically significant CTR changes: {len(sig)}.\n")

    if "ctr_model" in res:
        m = res["ctr_model"]
        out.append("## 4. CTR vs position (the site's own benchmark)\n")
        out.append(_table(m["benchmark"], ["pos_bin", "rows", "impressions", "benchmark_ctr"],
                          {"impressions": lambda v: f"{v:,.0f}", "benchmark_ctr": lambda v: _pct(v, 2)}, 10))
        u = m["underperformers"]
        out.append(f"{len(u)} non-brand queries have a CTR statistically below the benchmark for their position "
                   f"(>= {m['min_impressions']} impressions). Estimated clicks at stake over the period: "
                   f"**{u['est_extra_clicks'].sum():,.0f}** (upper bound).\n" if len(u) else "No query is statistically below the benchmark.\n")
        cols = [c for c in ("query", "position", "impressions", "clicks", "ctr", "benchmark_ctr", "est_extra_clicks") if c in u.columns]
        out.append(_table(u, cols, {"ctr": lambda v: _pct(v, 2), "benchmark_ctr": lambda v: _pct(v, 2),
                                    "impressions": lambda v: f"{v:,.0f}", "est_extra_clicks": lambda v: f"{v:,.0f}"}, 15))

    out.append("## How to read this\n")
    out.append("- **Significant is not the same as important.** With millions of impressions tiny CTR changes are 'significant'; "
               "look at the clicks effect, not only the verdict.\n"
               "- **P-values are a screening tool.** Impressions are not independent trials, so real uncertainty is larger than shown.\n"
               "- **Correlation, not cause.** A drop that coincides with a Google update or a deploy is a lead to check, not proof.\n"
               "- **Average position is an average.** Moving from 6.0 to 5.0 can be one query improving and another collapsing; "
               "segment before concluding.\n"
               "- **Recent days are incomplete** and anonymized queries are missing. See `references/pitfalls.md`.\n")
    return "\n".join(out)


def save_charts(res: dict, outdir: Path) -> list[str]:
    """Write PNG charts if matplotlib is available. Returns the file names written."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    if "anomalies" in res:
        a = res["anomalies"]
        s = a["series"]
        fig, ax = plt.subplots(figsize=(9, 3.4))
        ax.plot(s.index, s.values, color="#3b6ea5", lw=1.4, label=a["metric"])
        d = a["days"]
        if len(d):
            idx = pd.to_datetime(d["date"])
            ax.scatter(idx, d["value"], color="#c0392b", zorder=3, label="flagged")
        ax.set_title(f"Daily {a['metric']} and flagged days")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(outdir / "anomalies.png", dpi=130)
        plt.close(fig)
        written.append("anomalies.png")
    if "ctr_model" in res:
        b = res["ctr_model"]["benchmark"].dropna(subset=["benchmark_ctr"])
        if len(b):
            fig, ax = plt.subplots(figsize=(6, 3.6))
            ax.plot(b["pos_bin"], b["benchmark_ctr"] * 100, marker="o", color="#3b6ea5")
            ax.fill_between(b["pos_bin"], b["ci_low"] * 100, b["ci_high"] * 100, alpha=0.15, color="#3b6ea5")
            ax.set_xlabel("Average position")
            ax.set_ylabel("CTR (%)")
            ax.set_title("Own CTR curve (non-brand, 95% interval)")
            ax.spines[["top", "right"]].set_visible(False)
            fig.tight_layout()
            fig.savefig(outdir / "ctr_curve.png", dpi=130)
            plt.close(fig)
            written.append("ctr_curve.png")
    return written

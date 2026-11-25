#!/usr/bin/env python3
"""Run the Search Console analyses on CSV files and write a report.

Examples
  # anomalies on a daily export (Dates.csv from the Performance report)
  python run_analysis.py --daily Dates.csv --out report/

  # compare two periods by page, and benchmark CTR from the current period's queries
  python run_analysis.py --current pages_now.csv --previous pages_before.csv --key page \
                         --queries queries_now.csv --brand "acme,acme inc" --out report/

Every input goes through the data-quality checks first. Nothing here touches the network.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gsc_analysis import anomalies, compare, ctr_model, load, quality, report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--daily", help="CSV with one row per day (or per day+dimension): date, clicks, impressions")
    p.add_argument("--metric", default="clicks", choices=["clicks", "impressions", "ctr", "position"])
    p.add_argument("--current", help="CSV of the current period (page or query level)")
    p.add_argument("--previous", help="CSV of the previous period of the same length")
    p.add_argument("--key", default="page", choices=["page", "query"])
    p.add_argument("--queries", help="CSV with query-level rows (query, clicks, impressions, position) for the CTR benchmark")
    p.add_argument("--brand", default="", help="comma-separated brand terms, excluded from the CTR benchmark")
    p.add_argument("--min-impressions", type=int, default=100)
    p.add_argument("--threshold", type=float, default=3.5, help="anomaly threshold in robust standard deviations")
    p.add_argument("--out", default="report", help="output directory")
    p.add_argument("--title", default="Search Console data analysis")
    a = p.parse_args(argv)

    if not any([a.daily, a.current and a.previous, a.queries]):
        p.error("Give at least one of: --daily, --current with --previous, --queries")
    if bool(a.current) != bool(a.previous):
        p.error("--current and --previous go together")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"quality": []}
    brand = [b for b in a.brand.split(",") if b.strip()]

    def read(path: str, label: str):
        df = load.load_csv(path)
        q = quality.check(df, label=label)
        res["quality"].append(q)
        return df, q["ok"]

    if a.daily:
        df, ok = read(a.daily, "daily data")
        if ok and "date" in df.columns:
            s = anomalies.daily_series(df, a.metric)
            res["anomalies"] = {"metric": a.metric, "series": s, "threshold": a.threshold,
                                "days": anomalies.detect(s, threshold=a.threshold), "level_shift": anomalies.level_shift(s)}
            res["anomalies"]["days"].to_csv(out / "anomalies.csv", index=False)
    if a.current and a.previous:
        cur, ok1 = read(a.current, "current period")
        prev, ok2 = read(a.previous, "previous period")
        if ok1 and ok2 and a.key in cur.columns and a.key in prev.columns:
            c = compare.compare_periods(cur, prev, a.key, a.min_impressions)
            c["key"] = a.key
            res["compare"] = c
            c["rows"].to_csv(out / "compare_rows.csv", index=False)
    if a.queries:
        qdf, ok = read(a.queries, "queries")
        if ok and "query" in qdf.columns and "position" in qdf.columns:
            bench = ctr_model.build_benchmark(qdf, brand)
            under = ctr_model.underperformers(qdf, bench, brand, min_impressions=max(a.min_impressions, 200))
            res["ctr_model"] = {"benchmark": bench, "underperformers": under, "min_impressions": max(a.min_impressions, 200)}
            bench.to_csv(out / "ctr_benchmark.csv", index=False)
            under.to_csv(out / "ctr_underperformers.csv", index=False)

    charts = report.save_charts(res, out)
    md = report.build_report(res, a.title)
    (out / "report.md").write_text(md, encoding="utf-8")
    blocked = [q["summary"]["label"] for q in res["quality"] if not q["ok"]]
    print(md)
    print(f"\nWritten to {out}/: report.md" + (f", {', '.join(charts)}" if charts else "") + " + CSVs")
    if blocked:
        print(f"WARNING: analyses skipped because of data-quality errors in: {blocked}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

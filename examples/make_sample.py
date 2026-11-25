"""Generates a FICTIONAL Search Console dataset with known planted effects, to demo and test the skill.

    python examples/make_sample.py

Planted on purpose (so you can check the analysis finds them):
  * daily.csv      weekday pattern (weekends lower), one isolated spike on 2026-08-12, and a real level drop of about
                   30 % over the last 10 days (2026-09-19 onward).
  * queries_now    ~340 queries; brand queries have very high CTR; 12 NON-brand queries get about 40 % of the CTR their
                   position should earn (snippet problem).
  * pages_*        two 28-day periods; 6 pages lose CTR for real, many others only move by chance.
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
OUT = Path(__file__).resolve().parent / "sample_data"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- daily
days = pd.date_range("2026-06-01", "2026-09-28", freq="D")
weekday = np.array([1.0, 1.05, 1.05, 1.0, 0.95, 0.6, 0.55])  # Mon..Sun
trend = np.linspace(1.0, 1.15, len(days))
base = 420 * weekday[days.day_of_week] * trend
clicks = rng.poisson(base).astype(float)
clicks[days.get_loc(pd.Timestamp("2026-08-12"))] *= 2.4                      # isolated spike
clicks[days >= pd.Timestamp("2026-09-19")] *= 0.70                           # real drop
impr = rng.poisson(clicks * rng.uniform(26, 30, len(days)))
daily = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "Clicks": clicks.astype(int), "Impressions": impr,
                      "CTR": (clicks / impr * 100).round(2).astype(str) + "%", "Position": rng.normal(8.4, 0.25, len(days)).round(1)})
daily.to_csv(OUT / "daily.csv", index=False)

# ---------------------------------------------------------------- queries
CTR_CURVE = {1: 0.27, 2: 0.15, 3: 0.10, 4: 0.075, 5: 0.058, 6: 0.045, 7: 0.036, 8: 0.029, 9: 0.024, 10: 0.020}
words = ["analytics", "dashboard", "report", "metrics", "churn", "funnel", "cohort", "retention", "pricing", "template",
         "tutorial", "alternative", "benchmark", "forecast", "kpi", "export", "api", "integration", "sql", "visualization"]
rows = []
for i in range(320):
    q = f"{rng.choice(words)} {rng.choice(words)} {rng.choice(['guide', 'tool', 'software', 'examples', 'how to', 'for startups', ''])}".strip()
    pos = float(np.clip(rng.gamma(2.2, 3.2) + 1, 1, 40))
    impr = int(rng.pareto(1.4) * 60 + 30)
    exp = CTR_CURVE.get(round(pos), 0.012 if pos < 20 else 0.004)
    rows.append([f"{q} {i}", impr, round(pos, 1), exp])
for i in range(20):  # brand queries
    pos = float(rng.uniform(1.0, 1.6))
    impr = int(rng.integers(300, 4000))
    rows.append([f"northwind analytics {rng.choice(['login', 'pricing', 'reviews', 'docs', ''])} {i}".strip(), impr, round(pos, 1), 0.55])
q = pd.DataFrame(rows, columns=["Top queries", "Impressions", "Position", "exp"])
bad = q[(q["Position"].between(2.5, 9.5)) & (q["Impressions"] > 400) & (~q["Top queries"].str.startswith("northwind"))].head(12).index
q["true_ctr"] = np.where(q.index.isin(bad), q["exp"] * 0.4, q["exp"])
q["Clicks"] = rng.binomial(q["Impressions"], q["true_ctr"].clip(0, 1))
q["CTR"] = (q["Clicks"] / q["Impressions"] * 100).round(2).astype(str) + "%"
q[["Top queries", "Clicks", "Impressions", "CTR", "Position"]].to_csv(OUT / "queries_now.csv", index=False)

# ---------------------------------------------------------------- pages (two periods)
pages = [f"https://northwind-analytics.example/blog/post-{i}" for i in range(40)]
pos = rng.uniform(2, 14, len(pages))
impr_prev = rng.integers(800, 20000, len(pages))
ctr_prev = np.array([CTR_CURVE.get(round(p), 0.015) for p in pos]) * rng.uniform(0.9, 1.1, len(pages))
declining = rng.choice(len(pages), 6, replace=False)
impr_now = (impr_prev * rng.uniform(0.9, 1.1, len(pages))).astype(int)
ctr_now = ctr_prev * rng.uniform(0.95, 1.05, len(pages))
ctr_now[declining] *= 0.6
def mk(impr, ctr, shift):
    clicks = rng.binomial(impr, np.clip(ctr, 0, 1))
    return pd.DataFrame({"page": pages, "clicks": clicks, "impressions": impr, "ctr": clicks / impr, "position": (pos + shift).round(2)})
prev, now = mk(impr_prev, ctr_prev, 0.0), mk(impr_now, ctr_now, 0.0)
now = pd.concat([now, pd.DataFrame({"page": ["https://northwind-analytics.example/blog/new-post"], "clicks": [210], "impressions": [5200], "ctr": [210 / 5200], "position": [6.1]})])
prev.to_csv(OUT / "pages_prev.csv", index=False)
now.to_csv(OUT / "pages_now.csv", index=False)
print("declining pages (planted):", sorted(pages[i].rsplit("/", 1)[1] for i in declining))
print("wrote", sorted(p.name for p in OUT.iterdir()))

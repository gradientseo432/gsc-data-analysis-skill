---
name: gsc-data-analysis
description: Statistical data-science analysis for Google Search Console exports (CSV or API/MCP rows). Checks data quality first, separates real anomalies and level shifts from weekday noise, tests period-over-period CTR changes with Benjamini-Hochberg FDR control and clicks decomposition, and builds a non-brand CTR-by-position benchmark to find underperforming queries.
---

# Google Search Console Data Analysis

Never eyeball Search Console tables or compute CTR deltas in your head. Always run the Python scripts in `scripts/` so every number, interval, p-value, and decomposition is calculated deterministically.

## 1. Inputs you accept

- **UI CSV exports** (English or Spanish headers, decimal commas or `%` strings are normalized automatically by `gsc_analysis.load.load_csv`):
  - Daily trend (`Dates.csv`): `date`, `clicks`, `impressions` (plus optional `ctr`, `position`)
  - Period comparison (`Pages.csv` or `Queries.csv` for two equal-length periods): `page` or `query`, `clicks`, `impressions`, `position`
  - Query table for CTR modeling: `query`, `clicks`, `impressions`, `position` (plus optional `page`)
- **API / `gsc-mcp-server` rows**: pass raw `{"keys": [...], "clicks": ..., "impressions": ..., "ctr": ..., "position": ...}` lists to `gsc_analysis.load.from_api_rows(rows, dimensions)`.

## 2. Run the analysis script

From the repository or skill root, run:

```bash
python skills/gsc-data-analysis/scripts/run_analysis.py \
  --daily daily.csv \
  --current pages_now.csv \
  --previous pages_prev.csv \
  --key page \
  --queries queries_now.csv \
  --brand "brandname,brand domain" \
  --out report/
```

Any subset of `--daily`, `--current` + `--previous`, and `--queries` is valid.

### Options worth tuning
- `--metric`: `clicks` (default), `impressions`, `ctr`, or `position` for daily anomaly detection.
- `--brand`: comma-separated brand terms to exclude when fitting the site's CTR-by-position curve. **Always ask for or infer brand terms** before trusting CTR underperformers, because branded rank-1 queries inflate the benchmark.
- `--min-impressions`: minimum impressions per period to test a row (default `100`; CTR underperformers uses `max(min_impressions, 200)`).
- `--threshold`: robust z-score threshold for daily flags (default `3.5`).

## 3. Mandatory workflow and guardrails

1. **Data quality gates first (`quality.check`).**
   - If `run_analysis.py` exits with code `2` (errors such as `clicks > impressions`, negative counts, empty file, or missing required columns), **stop**. Report the errors and do not interpret downstream numbers.
   - Surface all warnings prominently in your summary:
     - `possible_truncation` (exact row cap `1000`, `5000`, `10000`, `25000`, `50000`) -> totals and long-tail shares are understated.
     - `recent_days_incomplete` -> last ~3 days are still shifting in GSC; exclude them before declaring a drop.
     - `date_gaps` -> missing zero-click days distort rolling averages.
     - `duplicate_rows` -> totals are inflated until deduplicated.
     - `anonymized_queries` -> query-level sums are always lower than page/site totals.
2. **Anomalies (`anomalies.detect` & `anomalies.level_shift`).**
   - Daily values are adjusted by multiplicative weekday factors (`weekday_factors`) so normal weekend dips are not flagged.
   - Isolated single-day spikes/drops are separated from sustained shifts (`level_shift` compares the last 7 weekday-adjusted days against the prior 28 days, judged against the site's own historical percentiles rather than a hard-coded +/-10% threshold).
3. **Period comparison (`compare.compare_periods`).**
   - Always report the **clicks decomposition** (`impressions_effect + ctr_effect = clicks_delta`) so the user sees whether a change came from visibility/impressions or from CTR/rank.
   - Only mark CTR changes as `up` or `down` when the Benjamini-Hochberg `q_value < 0.05` and both periods meet `--min-impressions`. Treat `inconclusive` and `low_volume` honestly—do not invent a story for noise.
4. **CTR benchmark (`ctr_model.build_benchmark` & `ctr_model.underperformers`).**
   - Compares each non-brand query against the **site's own** non-brand CTR at the same rounded position, and flags a query only when its upper 95% Wilson bound sits strictly below the benchmark.
   - Present `est_extra_clicks` explicitly as an **upper-bound estimate**, not a guarantee.

## 4. Before writing your final interpretation

Read `references/pitfalls.md` and check every finding against it. In particular, warn the user about:
- Statistical significance vs. practical importance (large impression counts make tiny CTR shifts "significant").
- Regression to the mean and Simpson's paradox when mixing devices, countries, or query mixes.
- Correlation vs. causation (an anomaly aligning with an algorithm update or deploy is a hypothesis to verify, not proof).

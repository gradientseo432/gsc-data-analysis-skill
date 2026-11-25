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

## 5. Mapping statistical outputs to SEO actions

Never stop at raw p-values or z-scores. Translate every verified finding into an explicit SEO diagnosis and next action:

| Output / Signal | What it diagnoses | Concrete SEO action |
|---|---|---|
| `anomalies.detect` flags 1–2 isolated days (`level_shift = within_normal_range`) | Viral spike, 24h tracking glitch, or temporary crawl/server hiccup | Log the date as an incident; **do not** edit titles, content, or technical setup |
| `level_shift = unusually_low` (with exact start date from `anomalies.csv`) | Sustained structural drop (deploy regression, `noindex`/canonical error, Google update, or real demand shift) | Start root-cause triage from that exact date: inspect templates, indexation (`inspect_url`), server logs, and SERP changes |
| `compare`: `verdict = down` with large negative **`impressions_effect`** (CTR stable) | **Visibility / ranking loss** (lost rankings, cannibalization, deindexing, or seasonal demand drop) | Check query/page rank history, URL indexation, internal links, content freshness, and search intent alignment |
| `compare`: `verdict = down` with large negative **`ctr_effect`** (impressions stable) | **SERP / snippet loss** (new AI Overview, more ads/SERP features, stronger competitor titles, lost rich snippets) | Inspect the live SERP for top queries; rewrite `title`/`meta` and restore or add structured data |
| `compare`: `verdict = new` | Newly indexed or newly ranking URLs gaining traction | Strengthen with internal links from high-authority pages and expand coverage around winning queries |
| `compare`: `verdict = lost` | URLs that disappeared from impressions | Check HTTP status (`404`/`410`/`301`), canonical tags, `noindex`, or keyword cannibalization |
| `compare`: `verdict = inconclusive` or `low_volume` | Chance fluctuation or insufficient impressions | Put on the **"Do Not Touch" list** so team hours are not wasted chasing noise |
| `ctr_model`: `underperformers` ranked by `est_extra_clicks` | Non-brand top-10 queries with sufficient volume whose CTR sits statistically below the site's own curve | Prioritize a **Title / Meta / Search Intent Optimization Backlog** starting from highest `est_extra_clicks` (stating it as an upper bound) |

## 6. Standard SEO deliverable format

When presenting results to the user, organize the response in these five sections:
1. **Data Reliability & Caveats** — pass/warn status from `quality.check` (truncation, incomplete last 3 days, date gaps, anonymized query caveat).
2. **Incident & Trend Triage** — whether a daily drop is noise, a single-day spike, or a sustained `level_shift`, with exact dates.
3. **Visibility vs. Snippet Audit Queue** — pages/queries separated by driver (`impressions_effect` vs. `ctr_effect`), plus `new` and `lost` URLs.
4. **Title / Meta & Intent Backlog** — top non-brand underperforming queries ranked by `est_extra_clicks`, with concrete snippet or intent hypotheses.
5. **Do-Not-Touch List** — `inconclusive` / `low_volume` movers explicitly held back so no changes are made on statistical noise.


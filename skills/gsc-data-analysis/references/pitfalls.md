# Statistical & Search Console Pitfalls

Read this checklist before turning any `gsc-data-analysis` output into recommendations. Most bad SEO conclusions come from misreading how Search Console aggregates data, not from wrong arithmetic.

## 1. Incomplete recent days (data lag)
Search Console typically takes **2 to 3 days** to finalize counts (sometimes longer during reporting delays). Comparing up to "yesterday" almost always creates a fake cliff at the end of the daily chart.
- **What the toolkit does:** `quality.check` warns with `recent_days_incomplete` when the newest date is within `lag_days` (default `3`) of today.
- **What you should do:** Trim the last 3 days before running `level_shift` or period comparisons.

## 2. Export row caps (silent truncation)
The Search Console web UI caps CSV exports at **1,000 rows**, and API queries cap at **1,000–50,000 rows** depending on parameters. When a file has an exact round row count (`1000`, `5000`, `10000`, `25000`, `50000`), the long tail is missing.
- **Risk:** Summed clicks/impressions understate reality, and the missing tail is disproportionately low-CTR / informational queries, which biases site-wide averages upward.
- **What you should do:** Note `possible_truncation` clearly and recommend pulling by day/filter or using the API (`gsc-mcp-server`).

## 3. Anonymized queries and total mismatches
Google suppresses rare/anonymized queries from query-level reports for privacy, while keeping them in property-level and page-level totals.
- **Rule:** Never subtract `sum(queries)` from `site_total` and call the difference an error, and never mix query-level totals with page-level totals in the same ratio.

## 4. Average position is an average, not a rank
"Average position" is weighted by impressions across queries, devices, countries, and SERP layouts.
- **Mix shift / Simpson's paradox:** A page's average position can *improve* from `6.0` to `4.0` solely because it **lost** impressions on rank-10 queries—looking like a win while losing traffic. Conversely, gaining impressions on new long-tail terms on page 2 worsens average position even as clicks grow.
- **What you should do:** Check `impressions_effect` alongside `position_delta`, and segment by device or country before blaming snippet or rank.

## 5. Regression to the mean
If you pick the top 20 winners or losers from last month and check them this month, the extreme outliers naturally drift back toward their typical performance—even if nothing happened on the site or in Google.
- **What you should do:** Judge changes across all rows with enough volume (`--min-impressions`) using `compare.compare_periods`, not by cherry-picking last period's extremes.

## 6. Multiple comparisons (why Benjamini-Hochberg FDR matters)
If you test 500 pages at `p < 0.05`, roughly **25 pages** will look "statistically significant" purely by coin-flip variance.
- **What the toolkit does:** `compare_periods` adjusts all p-values with Benjamini-Hochberg (`q_value`) and explicitly prints `expected_false_positives_without_correction`.
- **What you should do:** Only act on `verdict` in `{"up", "down"}` (where `q_value < alpha`), not raw `p_value < 0.05`.

## 7. Correlated impressions & significance vs. importance
A two-proportion z-test treats every impression as an independent Bernoulli trial. In reality, the same users and search sessions repeat impressions, so true variance is larger than the nominal formula assumes.
- **Use p-values as a filter, not a verdict on business value.**
- With 500,000 impressions, a CTR shift from `3.00%` to `2.92%` can have `q < 0.001` while barely moving clicks. Always rank actions by `ctr_effect` or `est_extra_clicks`, and check the Wilson confidence interval width.

## 8. Brand queries corrupt CTR benchmarks
Branded searches (`"brand login"`, `"brand pricing"`) routinely hit `30%–70%` CTR regardless of minor position differences. Leaving them in a site-wide CTR curve pulls the benchmark artificially high at positions 1–3 and flags healthy non-brand queries as "underperforming".
- **What you should do:** Always pass `--brand` (brand name, domain, common misspellings).

## 9. Missing days and `NaN` vs. `0`
In `anomalies.daily_series`, missing calendar days remain `NaN` rather than being silently zero-filled, unless the export genuinely recorded `0`. Silent zeros distort medians and weekday factors.
- **What you should do:** Investigate `date_gaps` before smoothing or running rolling anomaly checks.

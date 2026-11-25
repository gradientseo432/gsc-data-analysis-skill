# gsc-data-analysis

An **Agent Skill** and Python toolkit for **rigorous data-science analysis on Google Search Console data**. It separates real traffic anomalies and CTR shifts from weekday seasonality, sampling noise, and multiple-testing false positives.

Instead of asking an LLM to eyeball a CSV, the agent runs deterministic Python scripts (`scripts/run_analysis.py`) backed by statistical guardrails (`references/pitfalls.md`).

> **Status:** v0.1. Core statistical helpers, data-quality gates, anomaly detection, period comparison, CTR benchmarking, and CLI end-to-end flow are covered by **21 offline tests** (including planted-effect verification on synthetic data). Nothing touches the network.

## Modules

| Module | What it answers | Statistical technique |
|---|---|---|
| `quality.py` | Can I trust this export? | Row-cap truncation (`1k–50k`), date gaps, 3-day GSC data lag, duplicate rows, `clicks > impressions`, anonymized query warning |
| `anomalies.py` | Is this drop real or noise? | Multiplicative weekday adjustment, rolling median + `1.4826 × MAD` robust z-scores, self-history percentile `level_shift` |
| `compare.py` | Did CTR actually change? | Clicks decomposition (`impressions_effect + ctr_effect`), two-proportion z-test, **Benjamini-Hochberg FDR** (`q_value`), Wilson intervals |
| `ctr_model.py` | Where am I losing clicks vs. my own site? | Non-brand CTR curve by rounded position (Wilson 95% CI), flagging only queries whose upper Wilson bound is below benchmark |

## Statistical guardrails

Every report automatically surfaces warnings from `references/pitfalls.md`:
- **No external CTR curves:** benchmarks against your own non-brand queries at the same position.
- **Multiple-testing control:** reports how many false positives a naive `p < 0.05` scan would invent and filters via Benjamini-Hochberg FDR.
- **Small-sample protection:** Wilson score bounds prevent flagging a query with 40 impressions and 0 clicks.
- **Bilingual UI support:** normalizes English and Spanish Search Console CSV headers, `%` strings, and comma decimals (`load.py`), plus API / [`gsc-mcp-server`](https://github.com/gradientseo432/gsc-mcp-server) JSON rows (`from_api_rows`).

## Quickstart

### Run on the included fictional dataset

The repository includes `examples/make_sample.py`, which generates a fictional Search Console dataset (`examples/sample_data/`) with planted effects (an isolated spike on `2026-08-12`, a sustained drop from `2026-09-19`, 6 declining pages, and 12 low-CTR non-brand queries):

```bash
pip install -r requirements.txt

python skills/gsc-data-analysis/scripts/run_analysis.py \
  --daily examples/sample_data/daily.csv \
  --current examples/sample_data/pages_now.csv \
  --previous examples/sample_data/pages_prev.csv \
  --key page \
  --queries examples/sample_data/queries_now.csv \
  --brand northwind \
  --out report/
```

Outputs written to `report/`:
- `report.md` — structured findings, statistical verdicts, and caveats
- `anomalies.csv`, `compare_rows.csv`, `ctr_benchmark.csv`, `ctr_underperformers.csv`
- `anomalies.png`, `ctr_curve.png` (generated when `matplotlib` is installed)

### Install as an Agent Skill

Copy `skills/gsc-data-analysis/` into your agent's skills directory:
- **Claude Code:** `.claude/skills/gsc-data-analysis/` (or `~/.claude/skills/gsc-data-analysis/`)
- **Antigravity / `.agents`:** `.agents/skills/gsc-data-analysis/`

Pairs directly with [`gsc-mcp-server`](https://github.com/gradientseo432/gsc-mcp-server): pull live Search Console rows via MCP and pass them through `gsc_analysis` for anomaly, FDR comparison, and CTR-curve checks.

## Tests

```bash
pip install pytest
pytest -v tests
```

All 21 tests run offline without credentials and verify both known statistical values and end-to-end detection of the planted effects in `examples/sample_data/`.

## License

MIT. See [LICENSE](LICENSE).

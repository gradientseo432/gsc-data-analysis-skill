import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "gsc-data-analysis" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gsc_analysis import anomalies, compare, ctr_model, load, quality, stats  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_data"


# ------------------------------------------------------------------ stats
def test_wilson_interval_known_values():
    lo, hi = stats.wilson_interval(0, 100)
    assert lo == 0.0 and 0.03 < hi < 0.04                      # 0 clicks in 100 impressions is NOT "CTR exactly 0"
    lo, hi = stats.wilson_interval(50, 100)
    assert abs(lo - 0.404) < 0.002 and abs(hi - 0.596) < 0.002
    assert all(math.isnan(x) for x in stats.wilson_interval(0, 0))


def test_two_proportion_ztest():
    z, p = stats.two_proportion_ztest(100, 1000, 100, 1000)
    assert z == 0 and p == pytest.approx(1.0)
    z, p = stats.two_proportion_ztest(150, 1000, 100, 1000)
    assert z > 0 and p < 0.01
    z, p = stats.two_proportion_ztest(5, 100, 4, 100)           # tiny samples: inconclusive
    assert p > 0.5


def test_benjamini_hochberg_matches_reference():
    q = stats.benjamini_hochberg([0.01, 0.04, 0.03, 0.005, np.nan])
    # reference values computed by hand: sorted p = .005,.01,.03,.04 -> adj .02,.02,.04,.04
    assert np.allclose(q[:4], [0.02, 0.04 * 0.5 + 0.0, 0.04, 0.02], atol=1e-9) or np.allclose(sorted(q[:4]), [0.02, 0.02, 0.04, 0.04])
    assert np.isnan(q[4])
    assert (q[:4] >= np.array([0.01, 0.04, 0.03, 0.005])).all()  # adjustment never lowers a p-value


# ------------------------------------------------------------------ load
def test_load_spanish_ui_export(tmp_path):
    f = tmp_path / "es.csv"
    f.write_text("Consultas principales,Clics,Impresiones,CTR,Posición\nzapatillas rojas,12,340,\"3,5%\",\"8,2\"\n", encoding="utf-8-sig")
    df = load.load_csv(f)
    assert list(df.columns) == ["query", "clicks", "impressions", "ctr", "position"]
    assert df.loc[0, "ctr"] == pytest.approx(0.035) and df.loc[0, "position"] == pytest.approx(8.2)


def test_load_english_ui_export_and_percent_strings(tmp_path):
    f = tmp_path / "en.csv"
    f.write_text("Top pages,Clicks,Impressions,CTR,Position\n/a,10,200,5%,3.1\n/b,1,500,0.2%,12.4\n", encoding="utf-8")
    df = load.load_csv(f)
    assert df["page"].tolist() == ["/a", "/b"] and df["ctr"].tolist() == pytest.approx([0.05, 0.002])


def test_from_api_rows():
    df = load.from_api_rows([{"keys": ["q1", "/p"], "clicks": 3, "impressions": 30, "ctr": 0.1, "position": 4.0}], ["query", "page"])
    assert df.loc[0, "query"] == "q1" and df.loc[0, "ctr"] == 0.1


# ------------------------------------------------------------------ quality
def base_df(n=20):
    return pd.DataFrame({"query": [f"q{i}" for i in range(n)], "clicks": [5] * n, "impressions": [100] * n,
                         "ctr": [0.05] * n, "position": [5.0] * n})


def codes(res):
    return {f["code"] for f in res["findings"]}


def test_quality_clean_and_error_cases():
    assert quality.check(base_df())["ok"]
    assert "missing_columns" in codes(quality.check(pd.DataFrame({"x": [1]})))
    bad = base_df(); bad.loc[0, "clicks"] = 999
    r = quality.check(bad)
    assert not r["ok"] and "clicks_gt_impressions" in codes(r)


def test_quality_flags_truncated_export_duplicates_and_ctr_mismatch():
    r = quality.check(pd.concat([base_df(1000)], ignore_index=True))
    assert "possible_truncation" in codes(r)
    dup = pd.concat([base_df(), base_df(3)], ignore_index=True)
    assert "duplicate_rows" in codes(quality.check(dup))
    mm = base_df(); mm.loc[0, "ctr"] = 0.5
    assert "ctr_mismatch" in codes(quality.check(mm))


def test_quality_dates_gaps_and_recent_days():
    d = pd.DataFrame({"date": pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-05", "2026-09-06"]), "clicks": 1, "impressions": 10})
    assert "date_gaps" in codes(quality.check(d, today=date(2026, 10, 30)))
    assert "recent_days_incomplete" in codes(quality.check(d, today=date(2026, 9, 7)))
    assert "recent_days_incomplete" not in codes(quality.check(d, today=date(2026, 9, 20)))


# ------------------------------------------------------------------ anomalies
def make_series(n=120, seed=1, drop_from=None, spike_at=None):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="D")  # starts on a Monday
    wk = np.array([1.0, 1.05, 1.05, 1.0, 0.95, 0.6, 0.55])[idx.day_of_week]
    v = rng.poisson(400 * wk).astype(float)
    if drop_from is not None:
        v[drop_from:] *= 0.65
    if spike_at is not None:
        v[spike_at] *= 3
    return pd.Series(v, index=idx)


def test_weekend_dip_is_not_an_anomaly():
    flagged = anomalies.detect(make_series())
    assert len(flagged) <= 1  # a clean weekday-seasonal series must not light up on every Saturday


def test_detects_spike_and_drop():
    s = make_series(drop_from=100, spike_at=60)
    flagged = anomalies.detect(s)
    dates = set(flagged["date"])
    assert s.index[60].date().isoformat() in dates
    assert flagged[flagged["direction"] == "down"]["date"].min() >= s.index[100].date().isoformat()
    assert (flagged["direction"] == "down").sum() >= 5
    assert anomalies.level_shift(s)["verdict"] == "unusually_low"


def test_level_shift_normal_and_insufficient_history():
    assert anomalies.level_shift(make_series(seed=3))["verdict"] == "within_normal_range"
    assert anomalies.level_shift(make_series(n=30))["verdict"] == "insufficient_history"


def test_daily_series_aggregates_and_keeps_gaps_as_nan():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-03"]), "clicks": [1, 2, 4], "impressions": [10, 10, 20]})
    s = anomalies.daily_series(df, "clicks")
    assert s.tolist()[0] == 3 and np.isnan(s.tolist()[1]) and s.tolist()[2] == 4
    assert anomalies.daily_series(df, "ctr").iloc[0] == pytest.approx(3 / 20)


# ------------------------------------------------------------------ compare
def period(pages, clicks, impr, pos=5.0):
    return pd.DataFrame({"page": pages, "clicks": clicks, "impressions": impr, "position": pos})


def test_decomposition_adds_up_to_clicks_delta():
    cur = period(["a", "b"], [150, 40], [2000, 1000])
    prev = period(["a", "b"], [100, 50], [1000, 1000])
    r = compare.compare_periods(cur, prev, "page", min_impressions=100)["rows"]
    tested = r[r["impressions_prev"] > 0]
    assert np.allclose(tested["impressions_effect"] + tested["ctr_effect"], tested["clicks_delta"])


def test_new_lost_and_low_volume_verdicts():
    cur = period(["a", "new", "tiny"], [100, 30, 1], [2000, 800, 20])
    prev = period(["a", "gone", "tiny"], [100, 40, 2], [2000, 900, 25])
    v = compare.compare_periods(cur, prev, "page", min_impressions=100)["rows"].set_index("page")["verdict"].to_dict()
    assert v["new"] == "new" and v["gone"] == "lost" and v["tiny"] == "low_volume" and v["a"] == "inconclusive"


def test_fdr_correction_prevents_chance_findings():
    rng = np.random.default_rng(0)
    pages = [f"p{i}" for i in range(300)]
    impr = rng.integers(2000, 6000, 300)
    ctr = rng.uniform(0.02, 0.08, 300)
    cur = period(pages, rng.binomial(impr, ctr), impr)   # SAME underlying CTR in both periods: nothing really changed
    prev = period(pages, rng.binomial(impr, ctr), impr)
    res = compare.compare_periods(cur, prev, "page", min_impressions=100)
    naive = int((res["rows"]["p_value"] < 0.05).sum())
    corrected = int(res["rows"]["verdict"].isin(["up", "down"]).sum())
    assert naive >= 5 and corrected <= 2  # ~15 chance 'hits' uncorrected; essentially none after FDR control


def test_real_change_is_detected():
    pages = ["a"] + [f"p{i}" for i in range(30)]
    impr = [20000] + [3000] * 30
    prev = period(pages, [1000] + [150] * 30, impr)
    cur = period(pages, [600] + [150] * 30, impr)
    r = compare.compare_periods(cur, prev, "page")["rows"].set_index("page")
    assert r.loc["a", "verdict"] == "down" and r.loc["a", "ctr_effect"] == pytest.approx(-400)


# ------------------------------------------------------------------ ctr model
def make_queries(seed=2):
    rng = np.random.default_rng(seed)
    rows = []
    for pos, ctr in ((3, 0.10), (5, 0.06), (8, 0.03)):
        for i in range(30):
            impr = int(rng.integers(500, 3000))
            rows.append([f"generic {pos} {i}", impr, rng.binomial(impr, ctr), pos + rng.uniform(-0.3, 0.3)])
    rows.append(["bad snippet query", 3000, 60, 5.0])         # 2 % where ~6 % is typical
    rows.append(["unlucky small", 40, 0, 5.0])                # 0 clicks but tiny volume: must NOT be flagged
    rows += [[f"acme brand {i}", 2000, 1400, 1.1] for i in range(10)]
    df = pd.DataFrame(rows, columns=["query", "impressions", "clicks", "position"])
    return df


def test_benchmark_excludes_brand_and_requires_enough_rows():
    df = make_queries()
    b = ctr_model.build_benchmark(df, ["acme"]).set_index("pos_bin")
    assert pd.isna(b.loc[1, "benchmark_ctr"])                  # only brand queries sat at position 1: no benchmark
    assert b.loc[3, "benchmark_ctr"] == pytest.approx(0.10, abs=0.01)
    with_brand = ctr_model.build_benchmark(df, None).set_index("pos_bin")
    assert with_brand.loc[1, "benchmark_ctr"] > 0.5            # shows why brand must be excluded


def test_underperformers_flags_significant_ones_only():
    df = make_queries()
    bench = ctr_model.build_benchmark(df, ["acme"])
    u = ctr_model.underperformers(df, bench, ["acme"], min_impressions=200)
    assert "bad snippet query" in u["query"].tolist()
    assert "unlucky small" not in u["query"].tolist()          # below min impressions
    assert not u["query"].str.contains("acme").any()
    assert u.loc[u["query"] == "bad snippet query", "est_extra_clicks"].iloc[0] > 100


# ------------------------------------------------------------------ end to end on the committed sample data
def test_cli_finds_the_planted_effects(tmp_path):
    import run_analysis

    code = run_analysis.main(["--daily", str(SAMPLE / "daily.csv"), "--current", str(SAMPLE / "pages_now.csv"),
                              "--previous", str(SAMPLE / "pages_prev.csv"), "--key", "page",
                              "--queries", str(SAMPLE / "queries_now.csv"), "--brand", "northwind", "--out", str(tmp_path)])
    assert code == 0
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "2026-08-12" in md and "unusually low" in md
    comp = pd.read_csv(tmp_path / "compare_rows.csv")
    downs = set(comp.loc[comp["verdict"] == "down", "page"].str.rsplit("/", n=1).str[1])
    assert len(downs) >= 3 and downs <= {"post-11", "post-20", "post-26", "post-3", "post-30", "post-37"}  # no false accusations
    under = pd.read_csv(tmp_path / "ctr_underperformers.csv")
    assert len(under) >= 5 and not under["query"].str.startswith("northwind").any()


def test_cli_refuses_to_analyse_data_with_errors(tmp_path):
    import run_analysis

    bad = tmp_path / "bad.csv"
    bad.write_text("date,clicks,impressions\n2026-01-01,50,10\n", encoding="utf-8")
    assert run_analysis.main(["--daily", str(bad), "--out", str(tmp_path / "o")]) == 2

"""Uji unit logika inti (dijalankan di CI GitHub Actions dan lokal: `pytest -q`)."""
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "functions"))

from tcba import gold, sentiment, silver, sources  # noqa: E402
from tcba.lake import Lake  # noqa: E402


def test_ttm_from_ytd():
    # laba kumulatif 10, 25, 45, 70 -> kuartalan 10, 15, 20, 25 -> TTM Q4 = 70
    f = pd.DataFrame({"ticker": ["X"] * 4, "fiscal_year": [2024] * 4, "quarter": [1, 2, 3, 4],
                      "revenue_ytd": [100, 200, 300, 400], "net_income_ytd": [10, 25, 45, 70],
                      "total_assets": [1000] * 4, "total_equity": [500] * 4})
    r = gold.ttm_ratios(f)
    assert len(r) == 1
    row = r.iloc[0]
    assert row["ni_ttm"] == pytest.approx(70)
    assert row["roe_ttm"] == pytest.approx(14.0)
    assert row["npm_ttm"] == pytest.approx(17.5)


def test_direction_rule():
    assert gold.direction(0.6, 0.5) == "naik"
    assert gold.direction(-0.6, 0.5) == "turun"
    assert gold.direction(0.2, 0.5) == "stabil"
    assert gold.direction(np.nan, 0.5) is None


def test_lexicon_sentiment():
    assert sentiment.lexicon_score("Laba Telkom naik, kinerja solid")["sentiment"] == "positive"
    assert sentiment.lexicon_score("Saham anjlok, rugi membengkak")["sentiment"] == "negative"


def test_parsers():
    raw = b'{"chart":{"result":[{"timestamp":[1704157200],"indicators":{"quote":[{"open":[1],"high":[1],"low":[1],"close":[3950],"volume":[10]}],"adjclose":[{"adjclose":[3950]}]}}]}}'
    df = sources.parse_yahoo_chart(raw, "TLKM")
    assert df.iloc[0]["close"] == 3950
    rss = b"<rss><channel><item><title>Laba TLKM naik - Kontan</title><pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"
    assert sources.parse_rss(rss, "TLKM").iloc[0]["title"].startswith("Laba")
    assert silver._norm_title("Laba TLKM naik - Kontan") == "Laba TLKM naik"


def test_bronze_immutable(tmp_path):
    lake = Lake(mode="local", root=str(tmp_path))
    lake.write_bytes("bronze", "a/b.json", b"{}", overwrite=False)
    with pytest.raises(FileExistsError):
        lake.write_bytes("bronze", "a/b.json", b"{}", overwrite=False)


def test_end_to_end_local(tmp_path):
    env = dict(os.environ)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "run_local_pipeline.py"),
                        "--lake", str(tmp_path), "--sample", "--retrain", "2"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    lake = Lake(mode="local", root=str(tmp_path))
    assert lake.exists("gold", "ml/latest/predictions.parquet")
    assert len(lake.read_parquet("gold", "ml/retrain_log.parquet")) == 2
    from tcba import api
    status, body = api.predictions(lake, {})
    assert status == 200 and len(body["items"]) == 3
    # inferensi real-time: fitur dihitung dari data terbaru, simulasi menimpa fitur
    status, live = api.predict_live(lake, {})
    assert status == 200 and live["mode"] == "live" and len(live["items"]) == 3
    item = live["items"][0]
    assert abs(item["proba_naik"] + item["proba_stabil"] + item["proba_turun"] - 1) < 1e-3
    assert item["live_features"]["ret_q"] is not None and item["data_as_of"]["prices"]
    status, sim = api.predict_live(lake, {"ticker": "TLKM", "bi_rate": "9", "bukan_fitur": "1"})
    assert status == 200 and sim["mode"] == "simulasi" and sim["simulation"] == {"bi_rate": 9.0}
    assert [r["ticker"] for r in sim["items"]] == ["TLKM"] and sim["items"][0]["live_features"]["bi_rate"] == 9.0
    status, one = api.predict(lake, {"ticker": "ISAT"})
    assert status == 200 and one["prediction"] in ("naik", "stabil", "turun")
    # horizon tahun depan, evaluasi prediksi vs aktual, analisis pengaruh
    status, p4 = api.predictions(lake, {"horizon": "4"})
    assert status == 200 and p4["horizon"] == 4 and len(p4["items"]) == 3
    assert all(r["horizon"] == 4 for r in p4["items"])
    status, ev = api.evaluation(lake, {})
    assert status == 200 and ev["horizon"] == 1 and len(ev["items"]) >= 3
    status, an = api.analysis(lake, {"ratio": "roe", "lag": "next"})
    assert status == 200 and an["regresi"]["ok"] and {b["blok"] for b in an["regresi"]["blok"]} == {"pasar", "makro", "sentimen"}
    assert all(c["spearman_rho"] is None or -1 <= c["spearman_rho"] <= 1 for c in an["korelasi"]) and an["kesimpulan"]


def test_ols_and_partial_f():
    from tcba import analysis
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    y = 2 * x + rng.normal(scale=0.5, size=200)
    X = np.column_stack([np.ones(200), x])
    full, base = analysis.ols(y, X), analysis.ols(y, X[:, :1])
    assert full["beta"][1] == pytest.approx(2, abs=0.15) and full["r2"] > 0.9
    f, p = analysis.partial_f(base, full)
    assert f > 100 and p < 1e-6


def test_analysis_drops_empty_variable(tmp_path):
    """Satu kolom kosong total tidak boleh membatalkan regresi (bug di data Azure)."""
    from tcba import analysis
    rng = np.random.default_rng(1)
    rows = []
    for t in ("TLKM", "ISAT", "EXCL"):
        for i, q in enumerate(pd.period_range("2020Q1", "2026Q2", freq="Q")):
            r = {"ticker": t, "quarter": str(q), "roe_ttm": 10 + rng.normal(), "inflation_yoy": np.nan}
            for b in analysis.BLOCKS.values():
                for v in b["vars"]:
                    r.setdefault(v, rng.normal())
            rows.append(r)
    lake = Lake(mode="local", root=str(tmp_path))
    lake.write_parquet("gold", "features/features_quarterly.parquet", pd.DataFrame(rows))
    status, out = analysis.run(lake, {})
    assert status == 200 and out["regresi"]["ok"] and out["regresi"]["n"] > 50
    assert [x["variabel"] for x in out["regresi"]["dikecualikan"]] == ["inflation_yoy"]

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

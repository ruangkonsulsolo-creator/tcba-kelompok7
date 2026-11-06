"""Backfill judul berita historis dari GDELT DOC 2.0 API (gratis, sejak 2017) ke Bronze.

Satu permintaan per emiten per kuartal (maks 250 artikel), respons JSON disimpan APA ADANYA:
    bronze/news/source=gdelt/ticker=<T>/quarter=<YYYYQn>/gdelt.json

    python scripts/backfill_news_gdelt.py --start 2017Q1 --end 2026Q3
    LAKE_MODE=adls LAKE_ACCOUNT=<akun> python scripts/backfill_news_gdelt.py ...

Catatan: GDELT membatasi laju permintaan — skrip menunggu 6 detik antar-permintaan (±10 menit total).
Jalankan oleh anggota dengan koneksi/laptop yang stabil (Raihan).
"""
import argparse
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions"))
from tcba import config, sources  # noqa: E402
from tcba.lake import Lake  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2017Q1")
    ap.add_argument("--end", default="2026Q3")
    ap.add_argument("--sleep", type=float, default=6.0)
    a = ap.parse_args()
    lake = Lake()
    for q in pd.period_range(a.start, a.end, freq="Q"):
        for t, meta in config.TICKERS.items():
            path = f"news/source=gdelt/ticker={t}/quarter={q}/gdelt.json"
            if lake.exists(config.BRONZE, path):
                continue                                   # sudah pernah diambil (Bronze immutable)
            url = sources.gdelt_url(meta["news_query"], q.start_time.to_pydatetime(), q.end_time.to_pydatetime())
            try:
                raw = sources._get(url, retries=3, backoff=10)
                lake.write_bytes(config.BRONZE, path, raw, overwrite=False)
                print(q, t, len(sources.parse_gdelt(raw, t)), "artikel")
            except Exception as e:
                print(q, t, "GAGAL:", e)
            time.sleep(a.sleep)


if __name__ == "__main__":
    main()

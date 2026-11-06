"""Backfill harga historis (sekali jalan) ke Bronze — respons ASLI Yahoo chart API per simbol.

    # ke lake lokal (lalu unggah dengan upload_bronze.py), atau langsung ke ADLS:
    python scripts/backfill_prices.py --start 2014-01-01                    # LAKE_MODE=local
    LAKE_MODE=adls LAKE_ACCOUNT=<akun> python scripts/backfill_prices.py --start 2014-01-01

Jika Yahoo menolak (HTTP 401/429), unduh CSV historis manual dari situs Yahoo Finance/Investing,
simpan apa adanya ke bronze/manual/prices_csv/upload_date=YYYY-MM-DD/<TICKER>.csv dan catat di laporan.
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions"))
from tcba import jobs  # noqa: E402
from tcba.lake import Lake  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    a = ap.parse_args()
    out = jobs.ingest_market(Lake(), start=dt.date.fromisoformat(a.start), end=dt.date.fromisoformat(a.end))
    print(out)
    out = jobs.ingest_fx(Lake(), start=dt.date.fromisoformat(a.start), end=dt.date.fromisoformat(a.end))
    print(out)


if __name__ == "__main__":
    main()

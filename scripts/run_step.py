"""Jalankan satu langkah pipeline terhadap lake lokal ATAU ADLS (tanpa batas waktu 230 detik ADF).

    python scripts/run_step.py silver --max-new 3000         # mis. skor sentimen backfill sekaligus
    LAKE_MODE=adls LAKE_ACCOUNT=<akun> LANGUAGE_ENDPOINT=... LANGUAGE_KEY=... python scripts/run_step.py silver
    python scripts/run_step.py gold
    python scripts/run_step.py ingest_market|ingest_fx|ingest_news
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions"))
from tcba import gold, jobs, silver  # noqa: E402
from tcba.lake import Lake  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["ingest_market", "ingest_fx", "ingest_news", "silver", "gold", "manual_parquet"])
    ap.add_argument("--max-new", type=int, default=None)
    a = ap.parse_args()
    lake = Lake()
    fn = {"ingest_market": lambda: jobs.ingest_market(lake), "ingest_fx": lambda: jobs.ingest_fx(lake),
          "ingest_news": lambda: jobs.ingest_news(lake), "silver": lambda: silver.run_silver(lake, a.max_new),
          "gold": lambda: gold.build_features(lake),
          "manual_parquet": lambda: [jobs.manual_csv_to_parquet(lake, n) for n in ("fundamentals", "bi_rate", "inflation")]}
    print(json.dumps(fn[a.step](), indent=1, default=str))


if __name__ == "__main__":
    main()

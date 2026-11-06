"""Unggah file ke Bronze ADLS dengan pola path yang benar (tanpa mengubah isi file).

1) CSV manual (laporan keuangan / BI rate / inflasi) — memicu pipeline ADF event otomatis:
    python scripts/upload_bronze.py manual --name fundamentals --file data/fundamentals.csv
    python scripts/upload_bronze.py manual --name bi_rate      --file data/bi_rate.csv
    python scripts/upload_bronze.py manual --name inflation    --file data/inflation.csv

2) Sinkron folder bronze lokal (hasil backfill lokal) ke ADLS:
    python scripts/upload_bronze.py sync --local-lake ./_lake

Butuh: `az login` + role Storage Blob Data Contributor pada container bronze; env LAKE_ACCOUNT.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "functions"))
from tcba import config, jobs  # noqa: E402
from tcba.lake import Lake  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manual")
    m.add_argument("--name", required=True, choices=["fundamentals", "bi_rate", "inflation"])
    m.add_argument("--file", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--local-lake", default=os.path.join(ROOT, "_lake"))
    s.add_argument("--skip-sample", action="store_true", default=True)
    a = ap.parse_args()
    remote = Lake(mode="adls")
    if a.cmd == "manual":
        with open(a.file, "rb") as f:
            raw = f.read()
        print("diunggah:", jobs.upload_manual_csv(remote, a.name, raw, os.path.basename(a.file)))
        print("ADF trigger 'tr_new_manual_file' akan menjalankan konversi Parquet + Gold (+ retrain bila fundamentals).")
    else:
        local = Lake(mode="local", root=a.local_lake)
        n = 0
        for p in local.list_paths(config.BRONZE):
            if a.skip_sample and "SAMPLE" in p:
                continue
            if not remote.exists(config.BRONZE, p):
                remote.write_bytes(config.BRONZE, p, local.read_bytes(config.BRONZE, p), overwrite=False)
                n += 1
        print(f"{n} file baru diunggah ke bronze")


if __name__ == "__main__":
    main()

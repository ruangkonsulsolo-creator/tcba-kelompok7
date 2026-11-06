"""Menjalankan seluruh pipeline secara LOKAL (tanpa Azure, tanpa biaya) — meniru alur ADF.

    python scripts/run_local_pipeline.py --sample --retrain 4

Langkah: [sampel] -> CSV manual->Parquet (padanan ADF Copy) -> Bronze->Silver -> Gold -> Training (xN)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "functions"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default=os.path.join(ROOT, "_lake"))
    ap.add_argument("--sample", action="store_true", help="buat data sintetis dulu")
    ap.add_argument("--retrain", type=int, default=1, help="berapa kali training dijalankan (simulasi retrain)")
    ap.add_argument("--skip-train", action="store_true")
    a = ap.parse_args()
    os.environ["LAKE_MODE"], os.environ["LAKE_ROOT"] = "local", a.lake

    if a.sample:
        subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "make_sample_data.py"), "--lake", a.lake])

    from tcba import gold, jobs, silver
    from tcba.lake import Lake
    lake = Lake()
    print("== [1] CSV manual -> Parquet (di Azure: ADF Copy activity)")
    for name in ("fundamentals", "bi_rate", "inflation"):
        print("  ", json.dumps(jobs.manual_csv_to_parquet(lake, name), default=str))
    print("== [2] Bronze -> Silver")
    print(json.dumps(silver.run_silver(lake, max_new_sentiment=100000), indent=1, default=str))
    print("== [3] Silver -> Gold")
    print(json.dumps(gold.build_features(lake), indent=1, default=str))
    if a.skip_train:
        return
    for i in range(a.retrain):
        print(f"== [4] Training #{i + 1}")
        subprocess.check_call([sys.executable, os.path.join(ROOT, "aml", "src", "train.py"),
                               "--features", os.path.join(a.lake, "gold", "features"),
                               "--out", os.path.join(a.lake, "gold", "ml"), "--trigger", "local"])
    print("\nSelesai. Jalankan dashboard lokal:  python scripts/serve_local.py  lalu buka http://localhost:8000")


if __name__ == "__main__":
    main()

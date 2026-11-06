"""Membuat DATA SINTETIS (contoh) dalam format ASLI sumber, untuk uji pipeline end-to-end.

PERINGATAN: data ini BUKAN data riil. Dipakai hanya agar pipeline, training, API, dan dashboard
bisa dicoba sebelum data asli terkumpul. Semua file diberi penanda 'SAMPLE'. Hapus/ganti sebelum
melaporkan hasil (lihat panduan Bab 7).

Pemakaian:
    python scripts/make_sample_data.py --lake ./_lake
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
from email.utils import format_datetime

import numpy as np
import pandas as pd

RNG = np.random.default_rng(7)
random.seed(7)
TICKERS = {  # (pendapatan tahunan, laba tahunan, aset, ekuitas) dalam miliar rupiah — skala kasar
    "TLKM": (150_000, 24_000, 280_000, 150_000, "TLKM.JK", 3800),
    "ISAT": (55_000, 4_000, 110_000, 30_000, "ISAT.JK", 6500),
    "EXCL": (32_000, 1_200, 70_000, 25_000, "EXCL.JK", 2400),
}
POS_T = ["{n} catat laba bersih naik {p}% didorong bisnis data", "Pendapatan {n} tumbuh solid, analis optimis",
         "{n} perluas jaringan 5G, kinerja membaik", "Saham {n} menguat, investor asing akumulasi",
         "{n} bagikan dividen jumbo, laba rekor", "Efisiensi biaya dorong margin {n} meningkat"]
NEG_T = ["Laba {n} turun {p}% tertekan beban bunga", "Saham {n} anjlok usai rilis kinerja kuartalan",
         "{n} hadapi tekanan persaingan, pendapatan melemah", "Beban depresiasi tinggi, margin {n} merosot",
         "{n} terkena denda regulator, saham terkoreksi", "Kinerja {n} lesu, analis pangkas target harga"]
NEU_T = ["{n} gelar RUPS tahunan di Jakarta", "{n} umumkan perubahan susunan direksi",
         "{n} jalin kerja sama dengan mitra teknologi", "Jadwal paparan publik {n} pekan depan"]


def w(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="./_lake")
    a = ap.parse_args()
    B = os.path.join(a.lake, "bronze")
    tag = "ingest_date=2026-11-06"
    quarters = pd.period_range("2014Q1", "2026Q3", freq="Q")

    # ---- penggerak laten per emiten (AR(1)) -> memengaruhi laba kuartal berikutnya, harga & sentimen kuartal ini
    latent = {t: np.zeros(len(quarters)) for t in TICKERS}
    for t in TICKERS:
        for i in range(1, len(quarters)):
            latent[t][i] = 0.6 * latent[t][i - 1] + RNG.normal(0, 1)

    # ---- laporan keuangan (KUMULATIF YTD, seperti laporan resmi IDX)
    rows = []
    for t, (rev, ni, assets, eq, _, _) in TICKERS.items():
        lvl_rev, base_margin = rev / 4, ni / rev
        ytd_rev = ytd_ni = 0.0
        for i, q in enumerate(quarters):
            if q.quarter == 1:
                ytd_rev = ytd_ni = 0.0
            lvl_rev *= 1 + 0.010 + RNG.normal(0, 0.015)
            z_prev = latent[t][i - 1] if i else 0
            # margin bersih kembali ke rata-rata, dipengaruhi penggerak laten kuartal SEBELUMNYA
            margin = base_margin * (1 + 0.25 * z_prev) + RNG.normal(0, base_margin * 0.08)
            lvl_ni = lvl_rev * margin
            ytd_rev += lvl_rev
            ytd_ni += lvl_ni
            assets *= 1 + 0.012 + RNG.normal(0, 0.01)
            eq = eq * (1 + 0.004 + RNG.normal(0, 0.008)) + lvl_ni * 0.05
            rows.append({"ticker": t, "fiscal_year": q.year, "quarter": q.quarter,
                         "period_end": q.end_time.date().isoformat(), "revenue_ytd": round(ytd_rev, 1),
                         "net_income_ytd": round(ytd_ni, 1), "total_assets": round(assets, 1),
                         "total_equity": round(eq, 1), "currency_unit": "miliar_rupiah",
                         "source_url": "SAMPLE_SYNTHETIC_NOT_REAL"})
    w(f"{B}/manual/fundamentals/upload_date=2026-11-06/fundamentals_SAMPLE.csv",
      pd.DataFrame(rows).to_csv(index=False).encode())

    # ---- BI rate & inflasi bulanan
    months = pd.date_range("2014-01-01", "2026-10-01", freq="MS")
    bi = np.empty(len(months)); bi[0] = 7.5
    for k in range(1, len(months)):   # kembali ke rata-rata 5,5% dengan langkah 25 bps
        step = 0.25 if RNG.random() < 0.12 else 0.0
        bi[k] = bi[k - 1] + (-step if bi[k - 1] > 5.5 + RNG.normal(0, 1) else step)
    bi = np.clip(bi, 3.5, 7.75)
    infl = np.clip(3.0 + np.cumsum(RNG.normal(0, 0.25, len(months))) * 0.3, 1.0, 8.0)
    w(f"{B}/manual/bi_rate/upload_date=2026-11-06/bi_rate_SAMPLE.csv",
      pd.DataFrame({"date": months.date, "bi_rate": bi.round(2), "source": "SAMPLE"}).to_csv(index=False).encode())
    w(f"{B}/manual/inflation/upload_date=2026-11-06/inflation_SAMPLE.csv",
      pd.DataFrame({"date": months.date, "inflation_yoy": infl.round(2), "source": "SAMPLE"}).to_csv(index=False).encode())

    # ---- harga harian dalam format respons Yahoo chart API
    days = pd.bdate_range("2014-01-02", "2026-11-05")
    qidx = {q: i for i, q in enumerate(quarters)}
    def chart(symbol, start_px, zser):
        px, closes, vols = start_px, [], []
        for d in days:
            z = zser[qidx.get(pd.Period(d, "Q"), len(quarters) - 1)] if zser is not None else 0
            px *= np.exp(0.00012 + 0.001 * z + RNG.normal(0, 0.011))
            closes.append(round(px, 0))
            vols.append(int(abs(RNG.normal(4e7, 1.5e7))))
        ts = [int(pd.Timestamp(d, tz="Asia/Jakarta").replace(hour=9).timestamp()) for d in days]
        c = np.array(closes)
        return {"chart": {"result": [{"meta": {"symbol": symbol, "currency": "IDR", "gmtoffset": 25200,
                                               "note": "SAMPLE_SYNTHETIC"},
                                      "timestamp": ts,
                                      "indicators": {"quote": [{"open": c.tolist(), "high": (c * 1.01).round(0).tolist(),
                                                                "low": (c * 0.99).round(0).tolist(), "close": c.tolist(),
                                                                "volume": vols}],
                                                     "adjclose": [{"adjclose": c.tolist()}]}}], "error": None}}
    for t, v in TICKERS.items():
        w(f"{B}/market/prices/symbol={v[4]}/{tag}/yahoo_chart_SAMPLE.json", json.dumps(chart(v[4], v[5], latent[t])).encode())
    w(f"{B}/market/prices/symbol=^JKSE/{tag}/yahoo_chart_SAMPLE.json", json.dumps(chart("^JKSE", 5200, None)).encode())

    # ---- kurs USD/IDR dalam format respons Frankfurter
    fx = 12200 * np.exp(np.cumsum(RNG.normal(0.00012, 0.004, len(days))))
    w(f"{B}/macro/fx_usdidr/{tag}/frankfurter_SAMPLE.json", json.dumps(
        {"amount": 1.0, "base": "USD", "start_date": str(days[0].date()), "end_date": str(days[-1].date()),
         "rates": {str(d.date()): {"IDR": round(float(x), 2)} for d, x in zip(days, fx)}}).encode())

    # ---- berita: GDELT (historis) + Google News RSS (terbaru)
    for t, v in TICKERS.items():
        name = t
        by_month: dict[str, list] = {}
        rss_items = []
        for i, q in enumerate(quarters):
            if q < pd.Period("2017Q1", "Q"):
                continue
            p_pos = 1 / (1 + np.exp(-1.2 * latent[t][i]))
            for k in range(30):
                r = RNG.random()
                tpl = random.choice(POS_T if r < p_pos * 0.8 else NEG_T if r < 0.8 else NEU_T)
                title = tpl.format(n=name, p=int(RNG.integers(3, 40))) + f" ({q} #{k})"
                when = q.start_time + pd.Timedelta(days=int(RNG.integers(0, 89)), hours=int(RNG.integers(0, 23)))
                if q >= pd.Period("2026Q2", "Q"):
                    rss_items.append((title, when))
                else:
                    by_month.setdefault(when.strftime("%Y-%m"), []).append(
                        {"url": f"https://example.org/{t}/{q}/{k}", "title": title,
                         "seendate": when.strftime("%Y%m%dT%H%M%SZ"), "domain": "example.org",
                         "language": "Indonesian", "sourcecountry": "Indonesia"})
        for m, arts in by_month.items():
            w(f"{B}/news/source=gdelt/ticker={t}/month={m}/gdelt_SAMPLE.json", json.dumps({"articles": arts}).encode())
        items = "".join(
            f"<item><title>{tt} - Media Contoh</title><link>https://example.org/rss/{t}/{j}</link>"
            f"<pubDate>{format_datetime(wh.to_pydatetime().replace(tzinfo=dt.timezone.utc))}</pubDate>"
            f"<source url=\"https://example.org\">Media Contoh</source></item>" for j, (tt, wh) in enumerate(rss_items))
        w(f"{B}/news/source=googlenews/ticker={t}/{tag}/rss_SAMPLE.xml",
          f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel><title>SAMPLE</title>{items}</channel></rss>".encode())
    print("Data sampel dibuat di", os.path.abspath(B))


if __name__ == "__main__":
    main()

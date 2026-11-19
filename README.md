# TCBA Kelompok 7 — Prediksi Arah Rasio Profitabilitas TLKM · ISAT · EXCL di Azure

Panduan lengkap langkah demi langkah ada di **`Panduan_Proyek_TCBA_Kelompok7.pdf`**. README ini ringkasan cara menjalankan.

## Arsitektur singkat
```
Yahoo Finance / Frankfurter / Google News RSS / GDELT / CSV manual (IDX, BI, BPS)
        │  (ADF schedule trigger, hari bursa 17:30 WIB  |  ADF storage-event trigger untuk CSV baru)
        ▼
Azure Data Factory ──► Azure Function (ingest) ──► ADLS Gen2  bronze/  (data ASLI: JSON/XML/CSV, tidak diubah)
        │                                                     silver/  (PARQUET: bersih, tipe benar, dedup, sentimen)
        ├─ Copy activity CSV → PARQUET ───────────────────►   silver/manual/
        └─ Azure Function build_gold ─────────────────────►   gold/features/ (PARQUET: fitur kuartalan + label)
                                                             gold/ml/      (prediksi, metrik, model, log retrain)
Azure ML (command job, cluster 0–1 node)  ◄── retrain: ADF mingguan · ADF saat laporan keuangan baru · manual
Azure Function API (/api/predictions …) ──► Dashboard web (Static Website: tabel + grafik)  [+ Power BI opsional]
Azure AI Language F0 (sentimen) · Key Vault · Managed Identity/RBAC · Log Analytics · Budget alert
```

## 1) Coba lokal dulu (gratis, ±5 menit)
```bash
make setup          # atau: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make local          # data SINTETIS -> Bronze -> Silver -> Gold -> 4x training
make serve          # buka http://localhost:8000
make test
```
> Data sintetis diberi penanda `SAMPLE`. Jangan dipakai untuk laporan.

## 2) Deploy ke Azure (oleh pemilik akun — Jonnathan)
```bash
az login
cp config/project.env.example config/project.env   # isi email, UPN teman, region
make azure-check azure-core azure-kv azure-func azure-aml azure-adf azure-web azure-team
```
Urutan penting: `azure-aml` sebelum `azure-adf` tidak wajib, tetapi `azure-func` harus sebelum `azure-adf` (ADF butuh host key Function).

## 3) Data asli (Raihan)
```bash
export LAKE_MODE=adls LAKE_ACCOUNT=<st...lake...>
python scripts/backfill_prices.py --start 2014-01-01
python scripts/backfill_news_gdelt.py --start 2017Q1 --end 2026Q3
python scripts/upload_bronze.py manual --name bi_rate --file data/bi_rate.csv
python scripts/upload_bronze.py manual --name inflation --file data/inflation.csv
python scripts/upload_bronze.py manual --name fundamentals --file data/fundamentals.csv   # memicu retrain
```

## 4) Harian
```bash
make cost      # cek biaya & resource berisiko
```

## Model v3 — data 10 tahun + proyeksi mekanis (Nov 2026)
- **Data**: fundamental TLKM/ISAT/EXCL kini 2015Q1–2026Q3 (sebelumnya 2020+), BI-Rate & inflasi 2015–2026.
  Baris berlabel 67 → 128. TLKM 2015–2019 dari Info Memo/laporan keuangan resmi Telkom. ISAT & EXCL
  2015–2019: pendapatan & laba YTD dari rilis/berita keuangan (link per baris di `source_url`), neraca
  akhir tahun dari laporan tahunan resmi; neraca Q1–Q3 tidak tersedia publik → diinterpolasi untuk LABEL
  (ditandai `total_equity_interp`), sedangkan FITUR proyeksi memakai neraca terakhir yang sudah dirilis (point-in-time).
  BI-Rate: BI Rate lama s.d. Mar-2016, BI 7-Day RR Rate sejak Apr-2016 (ada lompatan karena ganti instrumen).
- **Fitur baru** `roe_proj_delta` (Gold): proyeksi ROE TTM kuartal depan = laba TTM − laba kuartal yang keluar
  dari jendela TTM + run-rate 2 kuartal terakhir, dibagi ekuitas rata-rata dengan pola musiman ekuitas (dividen).
- **Kandidat model baru** `proyeksi_mekanis` (`ProjectionRule` di `aml/src/tcba_model.py`): arah = ambang 'stabil'
  yang sama dengan label; tidak ada parameter arah yang dilatih. Dipilih otomatis lewat validasi walk-forward.
- **Hasil uji jujur (walk-forward, tanpa data masa depan)**, ambang stabil ±0,91 pp, 3 kelas seimbang:

  | Evaluasi | n prediksi | Akurasi | Macro-F1 |
  |---|---|---|---|
  | Uji 2023Q4–2026Q2 (model terpilih) | 32 | **75,0%** | 0,74 |
  | Walk-forward penuh 2017Q4–2026Q2 | 104 | **64,4%** | 0,64 |
  | Baseline persistence (uji) | 32 | 28,1% | 0,27 |
  | Model lama `random_forest|lengkap` (uji) | 32 | 59,4% | 0,60 |

  Per emiten (walk-forward penuh): TLKM 69%, ISAT 66%, EXCL 59%. Horizon tahun depan (4 kuartal) masih lemah (±38–52%).

## API untuk dashboard / Power BI (GET, tanpa key)
| Endpoint | Isi |
|---|---|
| `/api/predictions?horizon=1\|4` | prediksi batch hasil retrain terakhir (1 = kuartal depan, 4 = tahun depan) |
| `/api/predict_live?ticker=&horizon=&bi_rate=…` | inferensi real-time dari data 90 hari terakhir (+ simulasi what-if) |
| `/api/evaluation?horizon=` | prediksi yang pernah dibuat vs nilai aktual setelah laporan terbit |
| `/api/analysis?ratio=roe\|roa\|npm&lag=next\|same&ticker=` | uji korelasi + regresi panel + kontribusi blok pasar/makro/sentimen |
| `/api/backtest`, `/api/metrics`, `/api/retrain_log`, `/api/ratios`, `/api/prices` | evaluasi model, riwayat retrain, rasio, harga |

## Struktur folder
| Folder | Isi |
|---|---|
| `functions/` | Azure Function App (Python v2) + paket `tcba` (lake, sumber, Silver, Gold, API, retrain) |
| `aml/` | `src/train.py` (scikit-learn), template job Azure ML |
| `adf/` | JSON linked service, dataset, pipeline, trigger Data Factory |
| `infra/` | Skrip Azure CLI bernomor (00–08), cost guard, pause, destroy |
| `web/` | Dashboard statis (HTML + Chart.js) |
| `scripts/` | Data sampel, backfill, unggah Bronze, runner lokal, server lokal |
| `data_templates/` | Template CSV laporan keuangan, BI rate, inflasi |
| `sql/` | View Synapse serverless (opsional) |
| `tests/` | Pytest |

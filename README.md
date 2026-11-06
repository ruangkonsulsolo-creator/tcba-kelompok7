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

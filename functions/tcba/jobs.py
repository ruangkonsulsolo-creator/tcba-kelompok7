"""Job ingestion ke Bronze. Dipanggil oleh Azure Function (via ADF) maupun skrip lokal.

Aturan Bronze (sesuai arahan dosen): data ASLI, tidak diubah, append-only.
Setiap eksekusi menulis file baru bernama timestamp -> tidak pernah menimpa file lama.
"""
from __future__ import annotations

import datetime as dt

from . import config, sources
from .lake import Lake

WIB = dt.timezone(dt.timedelta(hours=7))


def _stamp() -> tuple[str, str]:
    now = dt.datetime.now(dt.timezone.utc)
    return now.astimezone(WIB).date().isoformat(), now.strftime("%Y%m%dT%H%M%SZ")


def ingest_market(lake: Lake, days: int = 10, start: dt.date | None = None, end: dt.date | None = None) -> dict:
    end = end or dt.datetime.now(WIB).date()
    start = start or end - dt.timedelta(days=days)
    day, ts = _stamp()
    written, errors = [], []
    symbols = {k: v["yahoo"] for k, v in config.TICKERS.items()} | config.MARKET_INDEX
    for ticker, symbol in symbols.items():
        try:
            raw = sources.fetch_yahoo_chart(symbol, start, end)
            path = f"market/prices/symbol={symbol}/ingest_date={day}/yahoo_chart_{ts}.json"
            written.append(lake.write_bytes(config.BRONZE, path, raw, overwrite=False))
        except Exception as e:
            errors.append(f"{symbol}: {e}")
    return {"job": "ingest_market", "start": str(start), "end": str(end), "written": written, "errors": errors,
            "status": "ok" if written else "failed"}


def ingest_fx(lake: Lake, days: int = 15, start: dt.date | None = None, end: dt.date | None = None) -> dict:
    end = end or dt.datetime.now(WIB).date()
    start = start or end - dt.timedelta(days=days)
    day, ts = _stamp()
    raw = sources.fetch_frankfurter(start, end)
    path = f"macro/fx_usdidr/ingest_date={day}/frankfurter_{ts}.json"
    return {"job": "ingest_fx", "written": [lake.write_bytes(config.BRONZE, path, raw, overwrite=False)],
            "errors": [], "status": "ok"}


def ingest_news(lake: Lake) -> dict:
    day, ts = _stamp()
    written, errors = [], []
    for ticker, meta in config.TICKERS.items():
        try:
            raw = sources.fetch_google_news_rss(meta["news_query"])
            path = f"news/source=googlenews/ticker={ticker}/ingest_date={day}/rss_{ts}.xml"
            written.append(lake.write_bytes(config.BRONZE, path, raw, overwrite=False))
        except Exception as e:
            errors.append(f"{ticker}: {e}")
    return {"job": "ingest_news", "written": written, "errors": errors, "status": "ok" if written else "failed"}


def upload_manual_csv(lake: Lake, name: str, raw: bytes, filename: str | None = None) -> str:
    """Simpan CSV manual (laporan keuangan/BI rate/inflasi) ke Bronze dengan versi tanggal unggah."""
    day, ts = _stamp()
    path = f"manual/{name}/upload_date={day}/{filename or name + '_' + ts + '.csv'}"
    return lake.write_bytes(config.BRONZE, path, raw, overwrite=False)


def manual_csv_to_parquet(lake: Lake, name: str) -> dict:
    """Padanan lokal untuk ADF Copy Activity (CSV Bronze terbaru -> Parquet Silver).

    Di Azure langkah ini DIKERJAKAN OLEH ADF (pipeline pl_manual_to_parquet). Fungsi ini dipakai
    saat menjalankan pipeline secara lokal agar alurnya identik.
    """
    files = [p for p in lake.list_paths(config.BRONZE, f"manual/{name}") if p.lower().endswith(".csv")]
    if not files:
        return {"job": f"manual_to_parquet:{name}", "status": "skipped", "reason": "belum ada CSV"}
    latest = files[-1]
    df = sources.parse_manual_csv(lake.read_bytes(config.BRONZE, latest)).astype(str)  # ADF Copy -> string
    out = lake.write_parquet(config.SILVER, f"manual/{name}/{name}.parquet", df)
    return {"job": f"manual_to_parquet:{name}", "status": "ok", "source": latest, "written": [out], "rows": len(df)}

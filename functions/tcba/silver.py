"""Bronze -> Silver: parsing, tipe data, deduplikasi, sentimen. Output selalu Parquet.

Silver dibangun ulang penuh dari Bronze setiap run (data proyek kecil), sehingga idempoten:
menjalankan ulang berkali-kali menghasilkan Silver yang sama.
"""
from __future__ import annotations

import hashlib
import re

import pandas as pd

from . import config, sentiment, sources
from .lake import Lake

S = config.SILVER
NEWS_PATH = "news/news_scored.parquet"


# --------------------------------------------------------------------------- market & fx
def build_prices(lake: Lake) -> dict:
    files = [p for p in lake.list_paths(config.BRONZE, "market/prices") if p.endswith(".json")]
    sym2tick = {v["yahoo"]: k for k, v in config.TICKERS.items()} | {v: k for k, v in config.MARKET_INDEX.items()}
    frames = []
    for i, p in enumerate(files):
        sym = re.search(r"symbol=([^/]+)/", p).group(1)
        df = sources.parse_yahoo_chart(lake.read_bytes(config.BRONZE, p), sym2tick.get(sym, sym))
        if len(df):
            df["_order"] = i
            frames.append(df)
    if not frames:
        return {"table": "prices_daily", "rows": 0, "status": "skipped"}
    df = pd.concat(frames, ignore_index=True).sort_values("_order")
    df = df.drop_duplicates(["ticker", "date"], keep="last").drop(columns="_order")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    for c in ("open", "high", "low", "close", "adj_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    df = df[(df["close"] > 0)]
    lake.write_parquet(S, "market/prices_daily.parquet", df)
    return {"table": "prices_daily", "rows": len(df), "files": len(files), "status": "ok",
            "max_date": str(df["date"].max().date())}


def build_fx(lake: Lake) -> dict:
    files = [p for p in lake.list_paths(config.BRONZE, "macro/fx_usdidr") if p.endswith(".json")]
    frames = [sources.parse_frankfurter(lake.read_bytes(config.BRONZE, p)).assign(_order=i) for i, p in enumerate(files)]
    frames = [f for f in frames if len(f)]
    if not frames:
        return {"table": "fx_usdidr_daily", "rows": 0, "status": "skipped"}
    df = pd.concat(frames).sort_values("_order").drop_duplicates("date", keep="last").drop(columns="_order")
    df["date"] = pd.to_datetime(df["date"])
    df["usd_idr"] = pd.to_numeric(df["usd_idr"], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    lake.write_parquet(S, "macro/fx_usdidr_daily.parquet", df)
    return {"table": "fx_usdidr_daily", "rows": len(df), "status": "ok"}


# --------------------------------------------------------------------------- news + sentiment
def _norm_title(t: str) -> str:
    t = re.sub(r"\s+-\s+[^-]{2,60}$", "", t or "")      # Google News: "Judul - Nama Media"
    return re.sub(r"\s+", " ", t).strip()


def _nid(ticker: str, title: str) -> str:
    return hashlib.sha1(f"{ticker}|{title.lower()}".encode()).hexdigest()[:16]


def build_news(lake: Lake, max_new: int | None = None) -> dict:
    max_new = config.SENTIMENT_MAX_NEW_PER_RUN if max_new is None else max_new
    frames = []
    for p in lake.list_paths(config.BRONZE, "news"):
        m = re.search(r"ticker=([A-Z]+)/", p)
        if not m:
            continue
        raw = lake.read_bytes(config.BRONZE, p)
        try:
            df = sources.parse_rss(raw, m.group(1)) if p.endswith(".xml") else sources.parse_gdelt(raw, m.group(1))
        except Exception:
            continue
        if len(df):
            frames.append(df)
    if not frames:
        return {"table": "news_scored", "rows": 0, "status": "skipped"}
    df = pd.concat(frames, ignore_index=True)
    df["title"] = df["title"].map(_norm_title)
    df = df[df["title"].str.len() > 15].copy()
    df["published_utc"] = pd.to_datetime(df["published_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["published_utc"])
    df["news_id"] = [_nid(t, s) for t, s in zip(df["ticker"], df["title"])]
    df = df.sort_values("published_utc").drop_duplicates("news_id", keep="first")
    df["quarter"] = df["published_utc"].dt.tz_convert("Asia/Jakarta").dt.tz_localize(None).dt.to_period("Q").astype(str)
    # Batasi jumlah berita per emiten per kuartal (hemat kuota sentimen), pilih deterministik via hash.
    df["_h"] = df["news_id"]
    df = (df.sort_values(["ticker", "quarter", "_h"]).groupby(["ticker", "quarter"], group_keys=False)
            .head(config.SENTIMENT_MAX_PER_TICKER_QUARTER).drop(columns="_h"))

    cache = lake.read_parquet_or_empty(S, NEWS_PATH)
    keep_cols = ["news_id", "sentiment", "pos", "neu", "neg", "score", "method"]
    if len(cache) and "method" in cache:
        df = df.merge(cache[keep_cols], on="news_id", how="left")
    else:
        for c in keep_cols[1:]:
            df[c] = None
    pending = df.index[df["method"].isna()].tolist()
    # Prioritaskan berita terbaru agar dashboard selalu terisi.
    pending = sorted(pending, key=lambda i: df.at[i, "published_utc"], reverse=True)[:max_new]
    scores = sentiment.score_texts(df.loc[pending, "title"].tolist())
    for i, sc in zip(pending, scores):
        for k, v in sc.items():
            df.at[i, k] = v
    for c in ("pos", "neu", "neg", "score"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["ticker", "published_utc"]).reset_index(drop=True)
    lake.write_parquet(S, NEWS_PATH, df)
    return {"table": "news_scored", "rows": len(df), "scored_now": len(pending),
            "pending": int(df["method"].isna().sum()), "status": "ok"}


# --------------------------------------------------------------------------- manual tables
def load_manual(lake: Lake, name: str) -> pd.DataFrame:
    """Prioritas: Parquet hasil ADF Copy (silver/manual/<name>/) -> CSV terbaru di Bronze."""
    pq = f"manual/{name}/{name}.parquet"
    if lake.exists(S, pq):
        return lake.read_parquet(S, pq)
    files = [p for p in lake.list_paths(config.BRONZE, f"manual/{name}") if p.lower().endswith(".csv")]
    if not files:
        return pd.DataFrame()
    return sources.parse_manual_csv(lake.read_bytes(config.BRONZE, files[-1]))


def build_manual_clean(lake: Lake) -> dict:
    out = {}
    f = load_manual(lake, "fundamentals")
    if len(f):
        f.columns = [c.strip().lower() for c in f.columns]
        for c in ("fiscal_year", "quarter"):
            f[c] = pd.to_numeric(f[c], errors="coerce").astype("Int64")
        for c in ("revenue_ytd", "net_income_ytd", "total_assets", "total_equity"):
            f[c] = pd.to_numeric(f[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
        f["ticker"] = f["ticker"].astype(str).str.upper().str.replace(".JK", "", regex=False).str.strip()
        f = f.dropna(subset=["fiscal_year", "quarter", "net_income_ytd"]).drop_duplicates(
            ["ticker", "fiscal_year", "quarter"], keep="last")
        lake.write_parquet(S, "manual_clean/fundamentals.parquet", f)
        out["fundamentals"] = len(f)
    for name, col in (("bi_rate", "bi_rate"), ("inflation", "inflation_yoy")):
        m = load_manual(lake, name)
        if len(m):
            m.columns = [c.strip().lower() for c in m.columns]
            m["date"] = pd.to_datetime(m["date"], errors="coerce")
            m[col] = pd.to_numeric(m[col].astype(str).str.replace(",", ".", regex=False), errors="coerce")
            m = m.dropna(subset=["date", col]).sort_values("date").drop_duplicates("date", keep="last")
            lake.write_parquet(S, f"manual_clean/{name}.parquet", m[["date", col]])
            out[name] = len(m)
    return {"table": "manual_clean", "rows": out, "status": "ok" if out else "skipped"}


def run_silver(lake: Lake, max_new_sentiment: int | None = None) -> dict:
    steps = [build_prices(lake), build_fx(lake), build_news(lake, max_new_sentiment), build_manual_clean(lake)]
    return {"job": "bronze_to_silver", "steps": steps,
            "status": "ok" if any(s.get("status") == "ok" for s in steps) else "skipped"}

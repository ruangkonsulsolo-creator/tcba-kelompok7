"""Pengambil data (fetcher) dan parser sumber.

Prinsip Bronze: fetcher mengembalikan BYTES ASLI respons sumber (JSON/XML/CSV) tanpa diubah.
Parser hanya dipakai saat membangun Silver.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

from . import config

_S = requests.Session()
_S.headers.update({"User-Agent": config.USER_AGENT, "Accept": "*/*"})


def _get(url: str, retries: int = 3, backoff: float = 3.0) -> bytes:
    last = None
    for i in range(retries):
        try:
            r = _S.get(url, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.content
        except Exception as e:  # retry dengan exponential backoff
            last = e
            time.sleep(backoff * (2 ** i))
    raise RuntimeError(f"Gagal mengambil {url}: {last}")


# =========================================================== Harga saham (Yahoo chart API)
def fetch_yahoo_chart(symbol: str, start: dt.date, end: dt.date) -> bytes:
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time()).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit&includeAdjustedClose=true")
    return _get(url)


def parse_yahoo_chart(raw: bytes, ticker: str) -> pd.DataFrame:
    j = json.loads(raw)
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        return pd.DataFrame()
    r = res[0]
    ts = r.get("timestamp") or []
    if not ts:
        return pd.DataFrame()
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q.get("close")
    df = pd.DataFrame({
        "date": pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Jakarta").date,
        "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
        "close": q.get("close"), "adj_close": adj, "volume": q.get("volume"),
    })
    df.insert(0, "ticker", ticker)
    return df.dropna(subset=["close"])


# =========================================================== Kurs USD/IDR (Frankfurter, data ECB)
def fetch_frankfurter(start: dt.date, end: dt.date) -> bytes:
    for base in ("https://api.frankfurter.app", "https://api.frankfurter.dev/v1"):
        try:
            return _get(f"{base}/{start.isoformat()}..{end.isoformat()}?from=USD&to=IDR", retries=2)
        except Exception:
            continue
    raise RuntimeError("Frankfurter API tidak dapat diakses")


def parse_frankfurter(raw: bytes) -> pd.DataFrame:
    j = json.loads(raw)
    rows = [{"date": pd.to_datetime(d).date(), "usd_idr": v.get("IDR")} for d, v in (j.get("rates") or {}).items()]
    return pd.DataFrame(rows)


# =========================================================== Berita (Google News RSS & GDELT)
def google_news_rss_url(query: str) -> str:
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"


def fetch_google_news_rss(query: str) -> bytes:
    return _get(google_news_rss_url(query))


def parse_rss(raw: bytes, ticker: str) -> pd.DataFrame:
    root = ET.fromstring(raw)
    rows = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone(dt.timezone.utc) if pub else None
        except Exception:
            published = None
        src = it.find("source")
        rows.append({
            "ticker": ticker, "title": title, "url": it.findtext("link"),
            "published_utc": published, "source": src.text if src is not None else None,
            "origin": "googlenews",
        })
    return pd.DataFrame(rows)


def gdelt_url(query: str, start: dt.datetime, end: dt.datetime, maxrecords: int = 250) -> str:
    params = {
        "query": f"({query}) sourcelang:indonesian", "mode": "artlist", "format": "json",
        "maxrecords": str(maxrecords), "sort": "datedesc",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"), "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }
    return "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)


def parse_gdelt(raw: bytes, ticker: str) -> pd.DataFrame:
    try:
        j = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return pd.DataFrame()
    rows = []
    for a in j.get("articles", []) or []:
        try:
            published = dt.datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            published = None
        rows.append({"ticker": ticker, "title": (a.get("title") or "").strip(), "url": a.get("url"),
                     "published_utc": published, "source": a.get("domain"), "origin": "gdelt"})
    return pd.DataFrame(rows)


# =========================================================== CSV manual (laporan keuangan, BI rate, inflasi)
FUNDAMENTAL_COLS = ["ticker", "fiscal_year", "quarter", "revenue_ytd", "net_income_ytd",
                    "total_assets", "total_equity"]


def parse_manual_csv(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig")
    sep = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    import io
    df = pd.read_csv(io.StringIO(text), sep=sep)
    df.columns = [c.strip().lower() for c in df.columns]
    return df

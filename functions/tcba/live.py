"""Inferensi real-time (nowcast) — dipakai endpoint GET /api/predict_live.

Prediksi batch (/api/predictions) dihitung sekali per retrain dari tabel Gold kuartalan.
Endpoint ini menghitung ulang fitur pasar, makro, dan sentimen SAAT DIPANGGIL dari data Silver terbaru
(jendela bergulir 90 hari s.d. data terakhir), menggabungkannya dengan rasio fundamental dari laporan
keuangan terakhir di Gold, lalu langsung menjalankan model hasil retrain terakhir.

Definisi fitur jendela 90 hari dibuat setara dengan fitur kuartalan di gold.py:
  ret_q        = return harga 90 hari (%)              vol_q        = volatilitas tahunan log-return (%)
  volume_chg   = perubahan rata-rata volume vs 90 hari sebelumnya (%)
  ret_jkse     = return IHSG 90 hari (%)               excess_ret_q = ret_q - ret_jkse
  usd_idr_avg  = rata-rata kurs 90 hari                usd_idr_chg  = perubahan vs 90 hari sebelumnya (%)
  bi_rate      = BI-Rate terakhir                      bi_rate_chg  = selisih vs 90 hari sebelumnya (pp)
  inflation_yoy= rata-rata inflasi 90 hari (fallback: nilai terakhir)
  sent_*       = sentimen berita 90 hari terakhir

Parameter query opsional dengan nama fitur (mis. ?bi_rate=6.5&sent_mean=-0.3) dipakai untuk SIMULASI
"what-if": nilainya menimpa fitur hasil hitungan sebelum prediksi. Endpoint tetap read-only.
"""
from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd

from . import config
from .lake import Lake

G, S = config.GOLD, config.SILVER
ML = "ml/latest"
WINDOW_DAYS = 90
DATA_TTL_SECONDS = 120          # data Silver di-cache singkat agar panggilan beruntun tetap cepat

MARKET_FEATURES = ("ret_q", "vol_q", "volume_chg", "excess_ret_q", "ret_jkse")
MACRO_FEATURES = ("usd_idr_avg", "usd_idr_chg", "bi_rate", "bi_rate_chg", "inflation_yoy")
NEWS_FEATURES = ("sent_mean", "sent_n", "sent_neg_share", "has_news")
LIVE_FEATURES = MARKET_FEATURES + MACRO_FEATURES + NEWS_FEATURES

_MODEL: dict = {}
_DATA: dict = {}


def _utcnow() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None)


# ----------------------------------------------------------------------------- cache
def _model_paths() -> None:
    """model.pkl bisa memuat kelas RegDirection dari aml/src/tcba_model.py (di Azure: functions/aml_src)."""
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "..", "aml_src"), os.path.join(here, "..", "..", "aml", "src")):
        p = os.path.normpath(p)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)


def load_model(lake: Lake, horizon: int = 1) -> dict | None:
    """Model di-cache per (horizon, run_id): setelah retrain, panggilan berikutnya otomatis memakai model baru."""
    import joblib
    _model_paths()
    d = ML if horizon == 1 else f"{ML}/h4"
    if not lake.exists(G, f"{d}/model.pkl"):
        return None
    run_id = "latest"
    if lake.exists(G, f"{d}/metrics.json"):
        run_id = str(lake.read_json(G, f"{d}/metrics.json").get("run_id") or "latest")
    hit = _MODEL.get(horizon)
    if not hit or hit["run_id"] != run_id:
        _MODEL[horizon] = {"run_id": run_id, "bundle": joblib.load(io.BytesIO(lake.read_bytes(G, f"{d}/model.pkl")))}
    return _MODEL[horizon]["bundle"]


def _cached(lake: Lake, container: str, path: str) -> pd.DataFrame:
    key = (container, path)
    hit = _DATA.get(key)
    if hit and time.time() - hit[0] < DATA_TTL_SECONDS:
        return hit[1]
    df = lake.read_parquet_or_empty(container, path)
    _DATA[key] = (time.time(), df)
    return df


# ----------------------------------------------------------------------------- fitur jendela 90 hari
def _ret(px: pd.DataFrame, end: pd.Timestamp, days: int = WINDOW_DAYS) -> float:
    """Return (%) dari penutupan terakhir <= (end - days) ke penutupan terakhir <= end."""
    s = px.set_index("date")["adj_close"].dropna().sort_index()
    s_end = s[s.index <= end]
    s_start = s[s.index <= end - pd.Timedelta(days=days)]
    if s_end.empty or s_start.empty:
        return np.nan
    return float((s_end.iloc[-1] / s_start.iloc[-1] - 1) * 100)


def market_window(prices: pd.DataFrame, ticker: str) -> dict:
    out = {k: np.nan for k in MARKET_FEATURES}
    out["prices_as_of"] = None
    if prices.empty:
        return out
    p = prices.copy()
    p["date"] = pd.to_datetime(p["date"])
    me = p[p["ticker"] == ticker].sort_values("date")
    if me.empty:
        return out
    end = me["date"].max()
    start, prev_start = end - pd.Timedelta(days=WINDOW_DAYS), end - pd.Timedelta(days=2 * WINDOW_DAYS)
    win = me[me["date"] > start]
    prev = me[(me["date"] > prev_start) & (me["date"] <= start)]
    logret = np.log(win["adj_close"]).diff()
    out["ret_q"] = _ret(me, end)
    out["vol_q"] = float(logret.std() * np.sqrt(252) * 100) if logret.notna().sum() > 2 else np.nan
    if len(prev) and prev["volume"].mean() > 0:
        out["volume_chg"] = float((win["volume"].mean() / prev["volume"].mean() - 1) * 100)
    idx = p[p["ticker"].isin(config.MARKET_INDEX)]
    out["ret_jkse"] = _ret(idx, end) if len(idx) else np.nan
    out["excess_ret_q"] = out["ret_q"] - out["ret_jkse"] if not np.isnan(out["ret_jkse"]) else np.nan
    out["prices_as_of"] = str(end.date())
    return out


def macro_window(fx: pd.DataFrame, bi: pd.DataFrame, infl: pd.DataFrame) -> dict:
    out = {k: np.nan for k in MACRO_FEATURES}
    out["fx_as_of"] = None
    if len(fx):
        f = fx.assign(date=pd.to_datetime(fx["date"])).sort_values("date")
        end = f["date"].max()
        start, prev_start = end - pd.Timedelta(days=WINDOW_DAYS), end - pd.Timedelta(days=2 * WINDOW_DAYS)
        cur = f[f["date"] > start]["usd_idr"].mean()
        prv = f[(f["date"] > prev_start) & (f["date"] <= start)]["usd_idr"].mean()
        out["usd_idr_avg"] = float(cur)
        out["usd_idr_chg"] = float((cur / prv - 1) * 100) if prv and not np.isnan(prv) else np.nan
        out["fx_as_of"] = str(end.date())
    now = _utcnow().normalize()
    if len(bi):
        b = bi.assign(date=pd.to_datetime(bi["date"])).sort_values("date")
        out["bi_rate"] = float(b["bi_rate"].iloc[-1])
        before = b[b["date"] <= now - pd.Timedelta(days=WINDOW_DAYS)]
        out["bi_rate_chg"] = float(out["bi_rate"] - before["bi_rate"].iloc[-1]) if len(before) else 0.0
    if len(infl):
        i = infl.assign(date=pd.to_datetime(infl["date"])).sort_values("date")
        recent = i[i["date"] > now - pd.Timedelta(days=WINDOW_DAYS)]["inflation_yoy"]
        out["inflation_yoy"] = float(recent.mean()) if len(recent) else float(i["inflation_yoy"].iloc[-1])
    return out


def news_window(news: pd.DataFrame, ticker: str) -> dict:
    out = {"sent_mean": 0.0, "sent_n": 0.0, "sent_neg_share": 0.0, "has_news": 0, "news_as_of": None}
    if news.empty or "method" not in news:
        return out
    n = news[(news["ticker"] == ticker) & news["method"].notna()].copy()
    if n.empty:
        return out
    n["published_utc"] = pd.to_datetime(n["published_utc"], utc=True, errors="coerce").dt.tz_localize(None)
    end = n["published_utc"].max()
    w = n[n["published_utc"] > _utcnow() - pd.Timedelta(days=WINDOW_DAYS)]   # berita 90 hari terakhir dari SEKARANG
    if w.empty:
        return out
    out.update(sent_mean=float(w["score"].mean()), sent_n=float(len(w)),
               sent_neg_share=float((w["sentiment"] == "negative").mean()), has_news=1,
               news_as_of=str(end.date()))
    return out


# ----------------------------------------------------------------------------- endpoint
def _num(v):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    return round(float(v), 4)


def predict_live(lake: Lake, q: dict | None = None):
    t0 = time.perf_counter()
    q = q or {}
    from .api import horizon_of
    horizon = horizon_of(q)
    bundle = load_model(lake, horizon)
    if bundle is None:
        return 404, {"error": "Model belum tersedia. Jalankan retrain dulu.", "items": []}
    feats = _cached(lake, G, "features/features_quarterly.parquet")
    if feats.empty:
        return 404, {"error": "Fitur Gold belum tersedia.", "items": []}
    model, cols = bundle["model"], bundle["features"]

    sim = {}
    for k, v in q.items():
        if k in ("ticker", "horizon"):
            continue
        if k in cols:
            try:
                sim[k] = float(v)
            except (TypeError, ValueError):
                pass

    prices = _cached(lake, S, "market/prices_daily.parquet")
    macro = macro_window(_cached(lake, S, "macro/fx_usdidr_daily.parquet"),
                         _cached(lake, S, "manual_clean/bi_rate.parquet"),
                         _cached(lake, S, "manual_clean/inflation.parquet"))
    news = _cached(lake, S, "news/news_scored.parquet")

    latest = feats.sort_values("quarter").groupby("ticker").tail(1)
    want = str(q.get("ticker") or "").upper()
    if want:
        latest = latest[latest["ticker"] == want]
    cur_q = str(_utcnow().to_period("Q"))

    items = []
    for _, base in latest.sort_values("ticker").iterrows():
        tic = base["ticker"]
        mk, nw = market_window(prices, tic), news_window(news, tic)
        row = {c: base.get(c) for c in cols}
        live = {**{k: mk[k] for k in MARKET_FEATURES}, **{k: macro[k] for k in MACRO_FEATURES},
                **{k: nw[k] for k in NEWS_FEATURES}}
        for k, v in live.items():                       # nilai live menggantikan nilai kuartal dasar
            if k in row and not (isinstance(v, float) and np.isnan(v)):
                row[k] = v
        row.update(sim)
        row["ticker"] = tic
        X = pd.DataFrame([row])
        for c in cols:
            X[c] = pd.to_numeric(X[c], errors="coerce")
        pr = model.predict_proba(X)[0]
        classes = list(model.classes_)
        proba = {c: round(float(v), 4) for c, v in zip(classes, pr)}
        pred_q = str(base.get("predicted_quarter" if horizon == 1 else "predicted_quarter_4q",
                              base.get("predicted_quarter")))
        items.append({
            "ticker": tic, "fundamental_quarter": str(base["quarter"]), "predicted_quarter": pred_q,
            "current_value": _num(base.get("target_value")),
            "prediction": classes[int(np.argmax(pr))], "confidence": round(float(np.max(pr)), 4),
            "proba_naik": proba.get("naik", 0.0), "proba_stabil": proba.get("stabil", 0.0),
            "proba_turun": proba.get("turun", 0.0),
            "live_features": {k: _num(sim.get(k, live.get(k))) for k in LIVE_FEATURES},
            "data_as_of": {"prices": mk["prices_as_of"], "fx": macro["fx_as_of"], "news": nw["news_as_of"]},
            "fundamentals_stale": str(base["quarter"]) < str(pd.Period(cur_q, freq="Q") - 1),
        })

    return 200, {
        "mode": "simulasi" if sim else "live", "horizon": horizon,
        "simulation": sim,
        "window_days": WINDOW_DAYS,
        "generated_at": _utcnow().isoformat() + "Z",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "model": bundle.get("model_name"), "run_id": bundle.get("run_id"), "trained_at": bundle.get("trained_at"),
        "current_quarter": cur_q, "fitur_model": list(cols),
        "fitur_live_dipakai": [k for k in LIVE_FEATURES if k in cols],
        "items": items,
        "note": ("Rasio fundamental dari laporan keuangan terakhir; fitur pasar, kurs, makro, dan sentimen "
                 f"dihitung saat ini dari {WINDOW_DAYS} hari data terakhir."),
    }

"""Handler API (dipakai Azure Function dan server lokal). Semua fungsi mengembalikan (status, dict)."""
from __future__ import annotations

import datetime as dt
import io
import math
import os

import pandas as pd

from . import config
from .lake import Lake

G, S = config.GOLD, config.SILVER
ML = "ml/latest"


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (pd.Timestamp, dt.date, dt.datetime)):
        return v.isoformat()
    if hasattr(v, "item"):
        try:
            return _clean(v.item())
        except Exception:
            return str(v)
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict(orient="records")]


def _not_ready(what: str):
    return 404, {"error": f"{what} belum tersedia. Jalankan pipeline/training dulu.", "items": []}


def health(lake: Lake, _=None):
    return 200, {"status": "ok", "lake_mode": lake.mode, "time_utc": dt.datetime.utcnow().isoformat() + "Z",
                 "model_ready": lake.exists(G, f"{ML}/predictions.parquet")}


def predictions(lake: Lake, q: dict | None = None):
    p = f"{ML}/predictions.parquet"
    if not lake.exists(G, p):
        return _not_ready("Prediksi")
    df = lake.read_parquet(G, p)
    if q and q.get("ticker"):
        df = df[df["ticker"] == q["ticker"].upper()]
    meta = lake.read_json(G, f"{ML}/metrics.json") if lake.exists(G, f"{ML}/metrics.json") else {}
    return 200, {"items": records(df), "model": meta.get("best_model"), "run_id": meta.get("run_id"),
                 "trained_at": meta.get("trained_at"), "target_ratio": meta.get("target_ratio"),
                 "test_macro_f1": (meta.get("test") or {}).get("macro_f1")}


def backtest(lake: Lake, q: dict | None = None):
    p = f"{ML}/backtest.parquet"
    if not lake.exists(G, p):
        return _not_ready("Backtest")
    df = lake.read_parquet(G, p)
    if q and q.get("ticker"):
        df = df[df["ticker"] == q["ticker"].upper()]
    return 200, {"items": records(df)}


def retrain_log(lake: Lake, _=None):
    p = "ml/retrain_log.parquet"
    if not lake.exists(G, p):
        return _not_ready("Riwayat retrain")
    df = lake.read_parquet(G, p).sort_values("trained_at")
    return 200, {"count": len(df), "items": records(df)}


def metrics(lake: Lake, _=None):
    if not lake.exists(G, f"{ML}/metrics.json"):
        return _not_ready("Metrik")
    m = lake.read_json(G, f"{ML}/metrics.json")
    fi = lake.read_parquet_or_empty(G, f"{ML}/feature_importance.parquet")
    m["feature_importance"] = records(fi.head(15)) if len(fi) else []
    return 200, m


def ratios(lake: Lake, q: dict | None = None):
    p = "features/features_quarterly.parquet"
    if not lake.exists(G, p):
        return _not_ready("Fitur Gold")
    df = lake.read_parquet(G, p)[["ticker", "quarter", "period_end", "roe_ttm", "roa_ttm", "npm_ttm",
                                   "sent_mean", "label"]]
    if q and q.get("ticker"):
        df = df[df["ticker"] == q["ticker"].upper()]
    return 200, {"items": records(df.sort_values(["ticker", "quarter"]))}


def prices(lake: Lake, q: dict | None = None):
    p = "market/prices_daily.parquet"
    if not lake.exists(S, p):
        return _not_ready("Harga")
    q = q or {}
    days = int(q.get("days", 730))
    df = lake.read_parquet(S, p)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= df["date"].max() - pd.Timedelta(days=days)]
    if q.get("ticker"):
        df = df[df["ticker"] == q["ticker"].upper()]
    df = df[["ticker", "date", "close", "volume"]]
    return 200, {"items": records(df.sort_values(["ticker", "date"]))}


_MODEL_CACHE: dict = {}


def predict(lake: Lake, body: dict | None):
    """Prediksi on-demand: body = {"ticker": "TLKM", "features": {...}} (fitur yang kosong diimputasi)."""
    import joblib
    body = body or {}
    p = f"{ML}/model.pkl"
    if not lake.exists(G, p):
        return _not_ready("Model")
    key = os.getenv("MODEL_CACHE_KEY", "latest")
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = joblib.load(io.BytesIO(lake.read_bytes(G, p)))
    bundle = _MODEL_CACHE[key]
    model, feats = bundle["model"], bundle["features"]
    row = {f: (body.get("features") or {}).get(f) for f in feats}
    row["ticker"] = (body.get("ticker") or "TLKM").upper()
    X = pd.DataFrame([row])
    for f in feats:
        X[f] = pd.to_numeric(X[f], errors="coerce")
    proba = model.predict_proba(X)[0]
    classes = list(model.classes_)
    return 200, {"ticker": row["ticker"], "prediction": classes[int(proba.argmax())],
                 "probabilities": {c: round(float(v), 4) for c, v in zip(classes, proba)},
                 "model": bundle.get("model_name"), "run_id": bundle.get("run_id")}


ROUTES = {
    "health": health, "predictions": predictions, "backtest": backtest, "retrain_log": retrain_log,
    "metrics": metrics, "ratios": ratios, "prices": prices,
}

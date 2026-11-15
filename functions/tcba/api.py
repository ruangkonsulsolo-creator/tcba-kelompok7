"""Handler API (dipakai Azure Function dan server lokal). Semua fungsi mengembalikan (status, dict)."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from . import config
from .lake import Lake

G, S = config.GOLD, config.SILVER
ML = "ml/latest"


def horizon_of(q: dict | None) -> int:
    """?horizon=4 (atau 'tahun') -> model tahun depan; selain itu kuartal depan."""
    v = str((q or {}).get("horizon", "1")).strip().lower()
    return 4 if v in ("4", "4q", "tahun", "year") else 1


def ml_dir(q: dict | None) -> str:
    return ML if horizon_of(q) == 1 else f"{ML}/h4"


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
    d = ml_dir(q)
    p = f"{d}/predictions.parquet"
    if not lake.exists(G, p):
        return _not_ready("Prediksi" + ("" if d == ML else " tahun depan (jalankan retrain dengan kode terbaru)"))
    df = lake.read_parquet(G, p)
    if q and q.get("ticker"):
        df = df[df["ticker"] == q["ticker"].upper()]
    meta = lake.read_json(G, f"{d}/metrics.json") if lake.exists(G, f"{d}/metrics.json") else {}
    return 200, {"items": records(df), "model": meta.get("best_model"), "run_id": meta.get("run_id"),
                 "trained_at": meta.get("trained_at"), "target_ratio": meta.get("target_ratio"),
                 "horizon": horizon_of(q), "test_macro_f1": (meta.get("test") or {}).get("macro_f1"),
                 "baseline_persistence_f1": ((meta.get("baselines") or {}).get("persistence") or {}).get("macro_f1"),
                 "model_lama_f1": ((meta.get("baselines") or {}).get("model_lama") or {}).get("macro_f1"),
                 "n_uji": (meta.get("test") or {}).get("n"), "walk_forward": meta.get("walk_forward"),
                 "jenis_model": meta.get("jenis_model"), "n_fitur": meta.get("n_fitur")}


def backtest(lake: Lake, q: dict | None = None):
    p = f"{ml_dir(q)}/backtest.parquet"
    if not lake.exists(G, p):
        return _not_ready("Backtest")
    df = lake.read_parquet(G, p)
    if q and q.get("ticker"):
        df = df[df["ticker"] == q["ticker"].upper()]
    return 200, {"items": records(df), "horizon": horizon_of(q)}


def retrain_log(lake: Lake, _=None):
    p = "ml/retrain_log.parquet"
    if not lake.exists(G, p):
        return _not_ready("Riwayat retrain")
    df = lake.read_parquet(G, p).sort_values("trained_at")
    return 200, {"count": len(df), "items": records(df)}


def metrics(lake: Lake, q: dict | None = None):
    d = ml_dir(q)
    if not lake.exists(G, f"{d}/metrics.json"):
        return _not_ready("Metrik")
    m = lake.read_json(G, f"{d}/metrics.json")
    fi = lake.read_parquet_or_empty(G, f"{d}/feature_importance.parquet")
    m["feature_importance"] = records(fi.head(15)) if len(fi) else []
    return 200, m


def evaluation(lake: Lake, q: dict | None = None):
    """Uji akurasi SUNGGUHAN: prediksi yang dulu dibuat sistem (riwayat retrain) vs nilai aktual yang kini terbit.

    Untuk tiap (emiten, kuartal dasar) dipakai prediksi TERAKHIR yang dibuat sebelum laporan kuartal tujuan masuk
    (yaitu saat kuartal dasar masih menjadi data terbaru). Aktual diambil dari label Gold saat ini.
    """
    h = horizon_of(q)
    hist = lake.read_parquet_or_empty(G, "ml/history/predictions_history.parquet")
    feats = lake.read_parquet_or_empty(G, "features/features_quarterly.parquet")
    if hist.empty or feats.empty:
        return _not_ready("Riwayat prediksi")
    if "horizon" not in hist:
        hist["horizon"] = 1
    hist = hist[hist["horizon"].fillna(1).astype(int) == h].copy()
    hist = hist.sort_values("generated_at").groupby(["ticker", "base_quarter"]).tail(1)
    lab_col, nxt = ("label", "target_next") if h == 1 else ("label_4q", "target_next4")
    if lab_col not in feats:
        return _not_ready("Label aktual tahun depan")
    act = feats[["ticker", "quarter", "target_value", nxt, lab_col]].rename(
        columns={"quarter": "base_quarter", lab_col: "actual", nxt: "actual_value", "target_value": "base_value"})
    df = hist.merge(act, on=["ticker", "base_quarter"], how="left")
    df["status"] = ["menunggu laporan" if pd.isna(a) else ("benar" if a == p else "salah")
                    for a, p in zip(df["actual"], df["prediction"])]
    done = df[df["actual"].notna()]
    cols = ["ticker", "base_quarter", "predicted_quarter", "prediction", "actual", "status", "base_value",
            "actual_value", "proba_naik", "proba_stabil", "proba_turun", "model_name", "run_id", "generated_at"]
    df = df[[c for c in cols if c in df]].sort_values(["predicted_quarter", "ticker"], ascending=[False, True])
    return 200, {"horizon": h, "evaluated": int(len(done)),
                 "correct": int((done["actual"] == done["prediction"]).sum()),
                 "accuracy": (float((done["actual"] == done["prediction"]).mean()) if len(done) else None),
                 "items": records(df)}


def analysis(lake: Lake, q: dict | None = None):
    from .analysis import run as _run
    return _run(lake, q or {})


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


def predict(lake: Lake, body: dict | None):
    """Prediksi on-demand: body = {"ticker": "TLKM", "features": {...}} (fitur yang kosong diimputasi)."""
    from .live import load_model
    body = body or {}
    bundle = load_model(lake, horizon_of(body))
    if bundle is None:
        return _not_ready("Model")
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


def predict_live(lake: Lake, q: dict | None = None):
    from .live import predict_live as _pl
    return _pl(lake, q)


ROUTES = {
    "health": health, "predictions": predictions, "backtest": backtest, "retrain_log": retrain_log,
    "metrics": metrics, "ratios": ratios, "prices": prices, "predict_live": predict_live,
    "evaluation": evaluation, "analysis": analysis,
}

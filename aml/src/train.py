"""Training + evaluasi + registrasi + batch scoring model arah rasio profitabilitas.

Dijalankan sebagai Azure ML command job (lihat aml/job_train.yml) atau lokal:
    python aml/src/train.py --features _lake/gold/features --out _lake/gold/ml --trigger local

Input : folder berisi features_quarterly.parquet (+ feature_list.json) dari lapisan Gold.
Output: folder `ml/` di Gold:
    latest/{predictions,backtest,feature_importance}.parquet, latest/metrics.json, latest/model.pkl
    runs/<run_id>/...   (salinan per retrain)    retrain_log.parquet   history/predictions_history.parquet
Model : klasik (scikit-learn) — sesuai arahan dosen: tanpa deep learning agar biaya rendah.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sys
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tcba_model import RegDirection  # noqa: E402

warnings.filterwarnings("ignore")
LABELS = ["turun", "stabil", "naik"]
DEV_PICKLE = os.getenv("TCBA_DEV_NO_PYARROW") == "1"


# ----------------------------------------------------------------------------- io
def read_table(path: str) -> pd.DataFrame:
    return pd.read_pickle(path) if DEV_PICKLE else pd.read_parquet(path)


def write_table(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_pickle(path) if DEV_PICKLE else df.to_parquet(path, index=False)


def load_features(folder: str) -> tuple[pd.DataFrame, dict]:
    files = sorted(glob.glob(os.path.join(folder, "**", "*.parquet"), recursive=True))
    if not files:
        raise FileNotFoundError(f"Tidak ada file parquet di {folder}")
    df = pd.concat([read_table(f) for f in files], ignore_index=True)
    meta_path = os.path.join(folder, "feature_list.json")
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    return df, meta


# ----------------------------------------------------------------------------- models
# Fitur "ringkas": fundamental inti + efek basis + variabel yang terbukti berpengaruh di analisis pengaruh
# (/api/analysis) + penanda kejadian khusus. Dengan ±70 baris data, fitur sedikit = overfitting lebih kecil.
RINGKAS = ["roe_ttm", "roe_ttm_chg1", "roe_ttm_chg4", "npm_ttm_chg1", "rev_growth_yoy",
           "roe_q", "roe_q_drop", "base_gap", "ni_base_gap",
           "vol_q", "volume_chg", "ret_q", "usd_idr_chg", "bi_rate_chg", "sent_mean", "sent_n",
           "evt_merger", "evt_akuntansi"]


def _pre(features: list[str], scale: bool):
    num = [("imp", SimpleImputer(strategy="median"))] + ([("sc", StandardScaler())] if scale else [])
    return ColumnTransformer([("num", Pipeline(num), features),
                              ("cat", OneHotEncoder(handle_unknown="ignore"), ["ticker"])])


# Fitur "inti": efek basis TTM (korelasi ±0,7 dengan perubahan ROE kuartal depan pada data asli) + kejadian khusus.
INTI = ["base_gap", "ni_base_gap", "roe_q", "roe_q_drop", "roe_ttm_chg1"]
INTI_EVENT = INTI + ["evt_merger", "evt_akuntansi"]


def make_candidates(all_features: list[str], thr: float, horizon: int = 1) -> dict:
    """Kandidat = (algoritma) × (set fitur). 'clf' = klasifikasi langsung, 'reg' = regresi Δ lalu jadi arah."""
    sets = {"lengkap": all_features, "ringkas": [f for f in RINGKAS if f in all_features] or all_features}
    for name, lst in (("inti", INTI), ("inti_event", INTI_EVENT)):
        # Efek basis adalah mekanisme 1 kuartal (kuartal yang keluar dari jendela TTM); tidak relevan untuk 4 kuartal.
        if horizon == 1 and all(f in all_features for f in INTI):
            sets[name] = [f for f in lst if f in all_features]
    out = {}
    for sname, feats in sets.items():
        out[f"logistic_regression|{sname}"] = ("clf", feats, Pipeline([("pre", _pre(feats, True)), ("clf", LogisticRegression(
            C=0.3, max_iter=3000, class_weight="balanced"))]))
        out[f"random_forest|{sname}"] = ("clf", feats, Pipeline([("pre", _pre(feats, False)), ("clf", RandomForestClassifier(
            n_estimators=200, max_depth=3, min_samples_leaf=4, class_weight="balanced_subsample", random_state=42))]))
        out[f"hist_gradient_boosting|{sname}"] = ("clf", feats, Pipeline([("pre", _pre(feats, False)), ("clf", HistGradientBoostingClassifier(
            max_depth=2, learning_rate=0.05, max_iter=120, l2_regularization=2.0, class_weight="balanced", random_state=42))]))
        out[f"ridge_regresi_arah|{sname}"] = ("reg", feats, RegDirection(
            Pipeline([("pre", _pre(feats, True)), ("reg", Ridge(alpha=5.0))]), thr=thr))
        out[f"rf_regresi_arah|{sname}"] = ("reg", feats, RegDirection(
            Pipeline([("pre", _pre(feats, False)), ("reg", RandomForestRegressor(
                n_estimators=200, max_depth=3, min_samples_leaf=4, random_state=42))]), thr=thr))
    return out


def macro_f1(y, p) -> float:
    return float(f1_score(y, p, labels=LABELS, average="macro", zero_division=0))


def persistence_pred(df: pd.DataFrame, thr: float, target: str, horizon: int = 1) -> list[str]:
    """Baseline naif: arah ke depan = arah perubahan terakhir (1 kuartal, atau 4 kuartal untuk horizon tahun)."""
    chg = df[f"{target}_chg{4 if horizon == 4 else 1}"]
    return ["naik" if c > thr else "turun" if c < -thr else "stabil" for c in chg.fillna(0)]


def _fit(kind, feats, est, d: pd.DataFrame):
    cols = feats + ["ticker"]
    y = d["target_delta"] if kind == "reg" else d["label"]
    return clone(est).fit(d[cols], y)


def walk_forward(lab: pd.DataFrame, kind, feats, est, eval_q: list[str], gap: int, quarters: list[str]) -> pd.DataFrame:
    """Uji maju-bertahap: untuk tiap kuartal q, latih HANYA dengan data yang labelnya sudah diketahui saat itu
    (kuartal dasar < q - (gap-1)), lalu prediksi kuartal q. Tidak ada kebocoran data masa depan."""
    rows = []
    cols = feats + ["ticker"]
    for q in eval_q:
        i = quarters.index(q)
        tr = lab[lab["quarter"].isin(quarters[:max(0, i - (gap - 1))])]
        te = lab[lab["quarter"] == q]
        if te.empty or tr["label"].nunique() < 2 or len(tr) < 12:
            continue
        m = _fit(kind, feats, est, tr)
        pr = m.predict_proba(te[cols])
        cls = list(m.classes_)
        r = te[["ticker", "quarter", "predicted_quarter", "label", "target_value", "target_next"]].copy()
        r["predicted"] = [cls[j] for j in pr.argmax(1)]
        for c in LABELS:
            r[f"proba_{c}"] = pr[:, cls.index(c)] if c in cls else 0.0
        rows.append(r)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# ----------------------------------------------------------------------------- mlflow (opsional)
def mlflow_log(params: dict, metrics: dict, model, run_name: str) -> str | None:
    try:
        import mlflow
        import mlflow.sklearn
    except ImportError:
        return None
    if not (os.getenv("MLFLOW_TRACKING_URI") or os.getenv("AZUREML_RUN_ID")):
        return None
    try:
        with mlflow.start_run(run_name=run_name, nested=bool(mlflow.active_run())):
            mlflow.log_params(params)
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
            info = mlflow.sklearn.log_model(model, "model", registered_model_name="tcba7-profit-direction")
            return str(getattr(info, "registered_model_version", "") or "")
    except Exception as e:  # registrasi gagal tidak boleh menggagalkan retrain
        print("[mlflow] dilewati:", e)
        return None


# ----------------------------------------------------------------------------- main
HORIZONS = {1: {"label": "label", "pred_q": "predicted_quarter", "next": "target_next", "thr": "stable_threshold_pp",
                "name": "kuartal depan"},
            4: {"label": "label_4q", "pred_q": "predicted_quarter_4q", "next": "target_next4",
                "thr": "stable_threshold_pp_4q", "name": "tahun depan (4 kuartal)"}}


def run_horizon(df: pd.DataFrame, meta: dict, features: list[str], target: str, horizon: int,
                test_quarters: int, run_id: str, now: dt.datetime, trigger: str) -> dict | None:
    """Pilih model terbaik lewat walk-forward (validasi) -> uji jujur pada kuartal terakhir -> refit -> prediksi."""
    h = HORIZONS[horizon]
    if h["label"] not in df:
        return None
    df = df.copy()
    df["label"], df["predicted_quarter"], df["target_next"] = df[h["label"]], df[h["pred_q"]], df[h["next"]]
    df["target_delta"] = df["target_next"] - df["target_value"]
    thr = float(meta.get(h["thr"], meta.get("stable_threshold_pp", 0.5)))

    lab = df[df["label"].notna()].sort_values(["period_end", "ticker"]).reset_index(drop=True)
    unl = df[df["label"].isna()].sort_values("period_end").groupby("ticker").tail(1)
    quarters = sorted(lab["quarter"].unique())
    min_train = 8
    if len(lab) < 12 or len(quarters) < min_train + 3:
        if horizon == 1:
            raise SystemExit(f"Data berlabel terlalu sedikit ({len(lab)} baris, {len(quarters)} kuartal).")
        print(f"[h{horizon}] dilewati: data berlabel terlalu sedikit ({len(lab)} baris)")
        return None
    wf_q = quarters[min_train:]
    n_test = min(test_quarters, max(2, len(wf_q) // 3))
    val_q, test_q = wf_q[:-n_test], wf_q[-n_test:]

    # ---- 1) seleksi kandidat pada kuartal validasi (walk-forward)
    cands = make_candidates(features, thr, horizon)
    val_scores, val_preds = {}, {}
    for name, (kind, feats, est) in cands.items():
        wf = walk_forward(lab, kind, feats, est, val_q, horizon, quarters)
        val_preds[name] = wf
        val_scores[name] = macro_f1(wf["label"], wf["predicted"]) if len(wf) else 0.0
    best_name = max(val_scores, key=lambda k: (round(val_scores[k], 3), -len(cands[k][1])))   # seri -> fitur lebih sedikit
    kind, feats, est = cands[best_name]
    old_name = "random_forest|lengkap"                                   # padanan model versi sebelumnya

    # ---- 2) uji jujur pada kuartal terakhir (walk-forward) untuk model terpilih + pembanding
    test = walk_forward(lab, kind, feats, est, test_q, horizon, quarters)
    old = walk_forward(lab, *cands[old_name], test_q, horizon, quarters) if old_name in cands else pd.DataFrame()
    allwf = pd.concat([val_preds[best_name], test], ignore_index=True)
    y, yp = test["label"], test["predicted"]
    p_, r_, f_, s_ = precision_recall_fscore_support(y, yp, labels=LABELS, zero_division=0)
    tr_major = lab[lab["quarter"] < test_q[0]]["label"].mode()
    maj = [tr_major.iloc[0] if len(tr_major) else "stabil"] * len(test)
    pers = persistence_pred(lab.set_index(["ticker", "quarter"]).loc[list(zip(test["ticker"], test["quarter"]))]
                            .reset_index(), thr, target, horizon)
    test_metrics = {
        "accuracy": float(accuracy_score(y, yp)), "macro_f1": macro_f1(y, yp), "n": int(len(test)),
        "per_class": {lbl: {"precision": float(p_[i]), "recall": float(r_[i]), "f1": float(f_[i]), "support": int(s_[i])}
                      for i, lbl in enumerate(LABELS)},
        "confusion_matrix": {"labels": LABELS, "matrix": confusion_matrix(y, yp, labels=LABELS).tolist()},
    }
    baselines = {"majority": {"accuracy": float(accuracy_score(y, maj)), "macro_f1": macro_f1(y, maj)},
                 "persistence": {"accuracy": float(accuracy_score(y, pers)), "macro_f1": macro_f1(y, pers)},
                 "model_lama": ({"accuracy": float(accuracy_score(old["label"], old["predicted"])),
                                 "macro_f1": macro_f1(old["label"], old["predicted"])} if len(old) else None)}
    walk = {"n_prediksi": int(len(allwf)), "kuartal": [str(wf_q[0]), str(wf_q[-1])],
            "accuracy": float(accuracy_score(allwf["label"], allwf["predicted"])) if len(allwf) else None,
            "macro_f1": macro_f1(allwf["label"], allwf["predicted"]) if len(allwf) else None}

    # ---- 3) refit pada SEMUA data berlabel, prediksi kuartal berikutnya
    final = _fit(kind, feats, est, lab)
    cols = feats + ["ticker"]
    pre_test = lab[lab["quarter"] < test_q[0]]
    imp_model = _fit(kind, feats, est, pre_test) if pre_test["label"].nunique() >= 2 else final
    ev = lab[lab["quarter"].isin(test_q)]
    pi = permutation_importance(imp_model, ev[cols], ev["label"], n_repeats=10, random_state=0, scoring="f1_macro")
    fi = pd.DataFrame({"feature": cols, "importance": pi.importances_mean, "std": pi.importances_std}) \
        .sort_values("importance", ascending=False)

    backtest = test.rename(columns={"label": "actual"})
    backtest["correct"] = backtest["actual"] == backtest["predicted"]
    pred = unl[["ticker", "quarter", "predicted_quarter", "target_value"]].rename(
        columns={"quarter": "base_quarter", "target_value": "current_value"}).copy()
    if len(unl):
        pr = final.predict_proba(unl[cols])
        cls = list(final.classes_)
        pred["prediction"] = [cls[j] for j in pr.argmax(1)]
        for c in LABELS:
            pred[f"proba_{c}"] = pr[:, cls.index(c)] if c in cls else 0.0
        pred["confidence"] = pr.max(1)
        if kind == "reg":
            pred["predicted_delta"] = final.predict_delta(unl[cols])
    pred["target_ratio"], pred["model_name"], pred["run_id"] = target, best_name, run_id
    pred["generated_at"], pred["horizon"] = now.isoformat(), horizon

    model_version = mlflow_log({"best_model": best_name, "target": target, "trigger": trigger, "horizon": horizon,
                                "n_labeled": len(lab), "n_test": len(test)},
                               {"val_macro_f1": val_scores[best_name], "test_accuracy": test_metrics["accuracy"],
                                "test_macro_f1": test_metrics["macro_f1"]}, final,
                               f"retrain-{trigger}" + ("" if horizon == 1 else f"-h{horizon}"))
    metrics = {"run_id": run_id, "trained_at": now.isoformat(), "trigger": trigger, "best_model": best_name,
               "jenis_model": "regresi→arah" if kind == "reg" else "klasifikasi", "n_fitur": len(feats),
               "fitur": feats, "horizon": horizon, "horizon_name": h["name"],
               "model_version": model_version, "target_ratio": target, "stable_threshold_pp": thr,
               "n_rows_labeled": len(lab), "n_train": int(len(pre_test)), "n_test": int(len(test)),
               "test_quarters": test_q, "validation_quarters": val_q,
               "data_max_quarter": str(df["quarter"].max()), "cv_macro_f1": val_scores, "test": test_metrics,
               "walk_forward": walk, "baselines": baselines, "sklearn_version": sklearn.__version__}
    bundle = {"model": final, "features": feats, "classes": list(final.classes_), "model_name": best_name,
              "run_id": run_id, "trained_at": now.isoformat(), "horizon": horizon}
    return {"pred": pred, "backtest": backtest, "fi": fi, "metrics": metrics, "bundle": bundle,
            "n_lab": len(lab), "cv_best": val_scores[best_name]}


def write_outputs(res: dict, folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    write_table(res["pred"], os.path.join(folder, "predictions.parquet"))
    write_table(res["backtest"], os.path.join(folder, "backtest.parquet"))
    write_table(res["fi"], os.path.join(folder, "feature_importance.parquet"))
    json.dump(res["metrics"], open(os.path.join(folder, "metrics.json"), "w"), indent=2, default=str)
    joblib.dump(res["bundle"], os.path.join(folder, "model.pkl"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trigger", default="manual")
    ap.add_argument("--test-quarters", type=int, default=6)
    a = ap.parse_args()

    df, meta = load_features(a.features)
    features = meta.get("features") or [c for c in df.columns if df[c].dtype.kind in "fi" and c not in (
        "target_value", "target_next", "target_delta", "target_next4", "target_delta4")]
    target = meta.get("target_ratio", df["target_ratio"].iloc[0] if "target_ratio" in df else "roe_ttm")
    df["period_end"] = pd.to_datetime(df["period_end"])
    for c in features:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    run_id = os.getenv("AZUREML_RUN_ID") or f"local-{now.strftime('%Y%m%dT%H%M%SZ')}"
    r1 = run_horizon(df, meta, features, target, 1, a.test_quarters, run_id, now, a.trigger)
    r4 = run_horizon(df, meta, features, target, 4, a.test_quarters, run_id, now, a.trigger)

    # ---- tulis output (horizon 1 di latest/ agar kompatibel; horizon 4 di latest/h4/)
    latest = os.path.join(a.out, "latest")
    if os.path.isdir(latest):
        shutil.rmtree(latest, ignore_errors=True)
    write_outputs(r1, latest)
    if r4:
        write_outputs(r4, os.path.join(latest, "h4"))
    run_dir = os.path.join(a.out, "runs", run_id.replace("/", "_"))
    shutil.copytree(latest, run_dir, dirs_exist_ok=True)

    m1 = r1["metrics"]
    log_path = os.path.join(a.out, "retrain_log.parquet")
    row = pd.DataFrame([{"run_id": run_id, "trained_at": now.isoformat(), "trigger": a.trigger,
                         "best_model": m1["best_model"], "model_version": m1["model_version"],
                         "n_rows_labeled": r1["n_lab"], "data_max_quarter": m1["data_max_quarter"],
                         "cv_macro_f1": r1["cv_best"], "test_accuracy": m1["test"]["accuracy"],
                         "test_macro_f1": m1["test"]["macro_f1"],
                         "baseline_persistence_f1": m1["baselines"]["persistence"]["macro_f1"],
                         "h4_best_model": r4["metrics"]["best_model"] if r4 else None,
                         "h4_test_macro_f1": r4["metrics"]["test"]["macro_f1"] if r4 else None}])
    log = pd.concat([read_table(log_path), row], ignore_index=True) if os.path.exists(log_path) else row
    write_table(log, log_path)
    hist_path = os.path.join(a.out, "history", "predictions_history.parquet")
    new_hist = pd.concat([r1["pred"]] + ([r4["pred"]] if r4 else []), ignore_index=True)
    hist = pd.concat([read_table(hist_path), new_hist], ignore_index=True) if os.path.exists(hist_path) else new_hist
    write_table(hist, hist_path)

    print(json.dumps({"run_id": run_id, "best_model": m1["best_model"], "cv_macro_f1": m1["cv_macro_f1"],
                      "test_macro_f1": round(m1["test"]["macro_f1"], 3), "retrain_count": len(log),
                      "h4_test_macro_f1": round(r4["metrics"]["test"]["macro_f1"], 3) if r4 else None,
                      "predictions": new_hist[["ticker", "horizon", "predicted_quarter", "prediction"]].to_dict("records")},
                     indent=2, default=str))


if __name__ == "__main__":
    main()

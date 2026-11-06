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
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

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
def make_models(features: list[str]) -> dict:
    def pre(scale: bool):
        num = [("imp", SimpleImputer(strategy="median"))] + ([("sc", StandardScaler())] if scale else [])
        return ColumnTransformer([
            ("num", Pipeline(num), features),
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["ticker"]),
        ])
    return {
        "logistic_regression": Pipeline([("pre", pre(True)), ("clf", LogisticRegression(
            C=0.5, max_iter=2000, class_weight="balanced"))]),
        "random_forest": Pipeline([("pre", pre(False)), ("clf", RandomForestClassifier(
            n_estimators=300, max_depth=4, min_samples_leaf=3, class_weight="balanced_subsample", random_state=42))]),
        "hist_gradient_boosting": Pipeline([("pre", pre(False)), ("clf", HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0, class_weight="balanced",
            random_state=42))]),
    }


def macro_f1(y, p) -> float:
    return float(f1_score(y, p, labels=LABELS, average="macro", zero_division=0))


def time_folds(quarters: list[str], n_splits: int = 3, min_train: int = 6):
    """Expanding-window CV berbasis kuartal (tanpa kebocoran data masa depan)."""
    q = sorted(quarters)
    if len(q) < min_train + n_splits:
        n_splits = max(1, len(q) - min_train)
    step = max(1, (len(q) - min_train) // max(n_splits, 1))
    for k in range(n_splits):
        cut = min_train + k * step
        val = q[cut:cut + step]
        if val:
            yield q[:cut], val


def persistence_pred(df: pd.DataFrame, thr: float, target: str) -> list[str]:
    """Baseline naif: arah kuartal depan = arah perubahan kuartal terakhir."""
    chg = df[f"{target}_chg1"]
    return ["naik" if c > thr else "turun" if c < -thr else "stabil" for c in chg.fillna(0)]


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
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trigger", default="manual")
    ap.add_argument("--test-quarters", type=int, default=4)
    a = ap.parse_args()

    df, meta = load_features(a.features)
    features = meta.get("features") or [c for c in df.columns if df[c].dtype.kind in "fi"
                                         and c not in ("target_value", "target_next", "target_delta")]
    target = meta.get("target_ratio", df["target_ratio"].iloc[0] if "target_ratio" in df else "roe_ttm")
    thr = float(meta.get("stable_threshold_pp", 0.5))
    df["period_end"] = pd.to_datetime(df["period_end"])
    for c in features:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    lab = df[df["label"].notna()].sort_values(["period_end", "ticker"]).reset_index(drop=True)
    unl = df[df["label"].isna()].sort_values("period_end").groupby("ticker").tail(1)
    quarters = sorted(lab["quarter"].unique())
    if len(lab) < 12 or len(quarters) < 6:
        raise SystemExit(f"Data berlabel terlalu sedikit ({len(lab)} baris, {len(quarters)} kuartal).")
    n_test_q = a.test_quarters if len(quarters) >= 12 else max(1, len(quarters) // 4)
    test_q = quarters[-n_test_q:]
    train, test = lab[~lab["quarter"].isin(test_q)], lab[lab["quarter"].isin(test_q)]
    cols = features + ["ticker"]

    # ---- seleksi model dengan CV berbasis waktu
    models = make_models(features)
    cv = {}
    for name, mdl in models.items():
        scores = []
        for tr_q, va_q in time_folds(sorted(train["quarter"].unique())):
            tr, va = train[train["quarter"].isin(tr_q)], train[train["quarter"].isin(va_q)]
            if tr["label"].nunique() < 2 or va.empty:
                continue
            m = clone(mdl).fit(tr[cols], tr["label"])
            scores.append(macro_f1(va["label"], m.predict(va[cols])))
        cv[name] = float(np.mean(scores)) if scores else 0.0
    best_name = max(cv, key=cv.get)
    best = clone(models[best_name]).fit(train[cols], train["label"])

    # ---- evaluasi pada kuartal uji (hold-out paling akhir)
    y_pred = best.predict(test[cols])
    p, r, f, s = precision_recall_fscore_support(test["label"], y_pred, labels=LABELS, zero_division=0)
    maj = DummyClassifier(strategy="most_frequent").fit(train[cols], train["label"]).predict(test[cols])
    pers = persistence_pred(test, thr, target)
    test_metrics = {
        "accuracy": float(accuracy_score(test["label"], y_pred)), "macro_f1": macro_f1(test["label"], y_pred),
        "per_class": {lbl: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
                      for i, lbl in enumerate(LABELS)},
        "confusion_matrix": {"labels": LABELS, "matrix": confusion_matrix(test["label"], y_pred, labels=LABELS).tolist()},
    }
    baselines = {"majority": {"accuracy": float(accuracy_score(test["label"], maj)), "macro_f1": macro_f1(test["label"], maj)},
                 "persistence": {"accuracy": float(accuracy_score(test["label"], pers)), "macro_f1": macro_f1(test["label"], pers)}}

    eval_set = test if len(test) >= 6 else train
    pi = permutation_importance(best, eval_set[cols], eval_set["label"], n_repeats=10, random_state=0,
                                scoring="f1_macro")
    fi = pd.DataFrame({"feature": cols, "importance": pi.importances_mean, "std": pi.importances_std}) \
        .sort_values("importance", ascending=False)

    proba_cols = lambda m: [f"proba_{c}" for c in m.classes_]  # noqa: E731
    backtest = test[["ticker", "quarter", "predicted_quarter", "label", "target_value", "target_next"]].copy()
    backtest = backtest.rename(columns={"label": "actual"})
    backtest["predicted"] = y_pred
    backtest["correct"] = backtest["actual"] == backtest["predicted"]
    backtest[proba_cols(best)] = best.predict_proba(test[cols])

    # ---- refit pada seluruh data berlabel, lalu prediksi kuartal berikutnya (batch scoring)
    final = clone(models[best_name]).fit(lab[cols], lab["label"])
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    run_id = os.getenv("AZUREML_RUN_ID") or f"local-{now.strftime('%Y%m%dT%H%M%SZ')}"
    pred = unl[["ticker", "quarter", "predicted_quarter", "target_value"]].rename(
        columns={"quarter": "base_quarter", "target_value": "current_value"}).copy()
    if len(unl):
        pr = final.predict_proba(unl[cols])
        pred["prediction"] = final.classes_[pr.argmax(1)]
        pred[proba_cols(final)] = pr
        pred["confidence"] = pr.max(1)
    for c in LABELS:
        if f"proba_{c}" not in pred:
            pred[f"proba_{c}"] = 0.0
    pred["target_ratio"], pred["model_name"], pred["run_id"] = target, best_name, run_id
    pred["generated_at"] = now.isoformat()

    model_version = mlflow_log({"best_model": best_name, "target": target, "trigger": a.trigger,
                                "n_train": len(train), "n_test": len(test)},
                               {"cv_macro_f1": cv[best_name], "test_accuracy": test_metrics["accuracy"],
                                "test_macro_f1": test_metrics["macro_f1"]}, final, f"retrain-{a.trigger}")

    metrics = {"run_id": run_id, "trained_at": now.isoformat(), "trigger": a.trigger, "best_model": best_name,
               "model_version": model_version, "target_ratio": target, "stable_threshold_pp": thr,
               "n_rows_labeled": len(lab), "n_train": len(train), "n_test": len(test), "test_quarters": test_q,
               "data_max_quarter": str(df["quarter"].max()), "cv_macro_f1": cv, "test": test_metrics,
               "baselines": baselines, "sklearn_version": sklearn.__version__}

    # ---- tulis output
    latest = os.path.join(a.out, "latest")
    if os.path.isdir(latest):
        shutil.rmtree(latest, ignore_errors=True)
    os.makedirs(latest, exist_ok=True)
    write_table(pred, os.path.join(latest, "predictions.parquet"))
    write_table(backtest, os.path.join(latest, "backtest.parquet"))
    write_table(fi, os.path.join(latest, "feature_importance.parquet"))
    json.dump(metrics, open(os.path.join(latest, "metrics.json"), "w"), indent=2, default=str)
    joblib.dump({"model": final, "features": features, "classes": list(final.classes_), "model_name": best_name,
                 "run_id": run_id, "trained_at": now.isoformat()}, os.path.join(latest, "model.pkl"))
    run_dir = os.path.join(a.out, "runs", run_id.replace("/", "_"))
    shutil.copytree(latest, run_dir, dirs_exist_ok=True)

    log_path = os.path.join(a.out, "retrain_log.parquet")
    row = pd.DataFrame([{"run_id": run_id, "trained_at": now.isoformat(), "trigger": a.trigger, "best_model": best_name,
                         "model_version": model_version, "n_rows_labeled": len(lab),
                         "data_max_quarter": metrics["data_max_quarter"], "cv_macro_f1": cv[best_name],
                         "test_accuracy": test_metrics["accuracy"], "test_macro_f1": test_metrics["macro_f1"],
                         "baseline_persistence_f1": baselines["persistence"]["macro_f1"]}])
    log = pd.concat([read_table(log_path), row], ignore_index=True) if os.path.exists(log_path) else row
    write_table(log, log_path)
    hist_path = os.path.join(a.out, "history", "predictions_history.parquet")
    hist = pd.concat([read_table(hist_path), pred], ignore_index=True) if os.path.exists(hist_path) else pred
    write_table(hist, hist_path)

    print(json.dumps({"run_id": run_id, "best_model": best_name, "cv_macro_f1": cv,
                      "test_macro_f1": round(test_metrics["macro_f1"], 3), "retrain_count": len(log),
                      "predictions": pred[["ticker", "predicted_quarter", "prediction"]].to_dict("records")},
                     indent=2, default=str))


if __name__ == "__main__":
    main()

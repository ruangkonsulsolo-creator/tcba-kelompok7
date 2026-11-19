"""Model "regresi -> arah": memprediksi BESAR perubahan rasio (Δ, poin persen), lalu mengubahnya menjadi
probabilitas naik / stabil / turun memakai sebaran galat dari validasi silang.

Kenapa? Dengan data kecil, kelas 'stabil' yang sempit membuat klasifikasi langsung mudah meleset tipis.
Regresi memakai seluruh informasi besaran perubahan, lalu ambang 'stabil' diterapkan di akhir.

Modul ini terpisah dari train.py agar model.pkl bisa dibuka di Azure Function (folder aml_src ikut di-deploy).
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.model_selection import KFold, cross_val_predict

CLASSES = np.array(["naik", "stabil", "turun"])          # urutan sama dengan classes_ klasifier sklearn


class RegDirection(BaseEstimator, ClassifierMixin):
    def __init__(self, regressor=None, thr: float = 0.5, cv: int = 3):
        self.regressor = regressor
        self.thr = thr
        self.cv = cv

    def fit(self, X, y_delta):
        y = np.asarray(y_delta, dtype=float)
        self.reg_ = clone(self.regressor).fit(X, y)
        k = min(self.cv, max(2, len(y) // 6))
        try:
            oof = cross_val_predict(clone(self.regressor), X, y, cv=KFold(k, shuffle=True, random_state=0))
            sd = float(np.std(y - oof))
        except Exception:
            sd = float(np.std(y - self.reg_.predict(X))) * 1.5
        self.sigma_ = max(sd, 1e-3)
        self.classes_ = CLASSES
        return self

    def predict_delta(self, X):
        return self.reg_.predict(X)

    def predict_proba(self, X):
        mu = self.reg_.predict(X)
        p_up = 1 - norm.cdf((self.thr - mu) / self.sigma_)
        p_down = norm.cdf((-self.thr - mu) / self.sigma_)
        p_flat = np.clip(1 - p_up - p_down, 0, 1)
        return np.column_stack([p_up, p_flat, p_down])

    def predict(self, X):
        return CLASSES[self.predict_proba(X).argmax(1)]


class ProjectionRule(BaseEstimator, ClassifierMixin):
    """Model "proyeksi mekanis" ROE TTM kuartal depan (tanpa parameter yang dilatih untuk arah).

    ROE_TTM(t+1) = [laba TTM(t) - laba kuartal (t-3) yang keluar dari jendela + laba kuartal baru] / rata2 ekuitas.
    Laba kuartal baru diproyeksikan = rata-rata laba 2 kuartal terakhir (run-rate), ekuitas t+1 = ekuitas t +
    perubahan ekuitas kuartal yang sama tahun lalu (pola dividen musiman). Selisihnya terhadap ROE_TTM(t)
    = kolom Gold `roe_proj_delta` (dihitung point-in-time: hanya memakai data yang sudah dirilis pada t).

    Arah = ambang 'stabil' yang SAMA dengan definisi label. Satu-satunya hal yang 'dilatih' adalah suhu (tau)
    untuk probabilitas, dari sebaran galat proyeksi pada data latih. argmax(proba) == aturan ambang.
    """

    def __init__(self, feature: str = "roe_proj_delta", thr: float = 0.5):
        self.feature = feature
        self.thr = thr

    def _mu(self, X):
        v = X[self.feature] if hasattr(X, "columns") else np.asarray(X)[:, 0]
        return np.nan_to_num(np.asarray(v, dtype=float), nan=0.0)

    def fit(self, X, y_delta):
        y = np.asarray(y_delta, dtype=float)
        res = y - self._mu(X)
        self.tau_ = max(float(np.nanstd(res)) / 2, 1e-3)
        self.classes_ = CLASSES
        return self

    def predict_delta(self, X):
        return self._mu(X)

    def predict_proba(self, X):
        mu = self._mu(X)
        s = np.column_stack([mu - self.thr, self.thr - np.abs(mu), -self.thr - mu]) / self.tau_   # naik, stabil, turun
        e = np.exp(s - s.max(1, keepdims=True))
        return e / e.sum(1, keepdims=True)

    def predict(self, X):
        return CLASSES[self.predict_proba(X).argmax(1)]

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

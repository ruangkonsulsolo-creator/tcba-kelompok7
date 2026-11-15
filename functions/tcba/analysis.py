"""Analisis pengaruh: Data Pasar Keuangan, Makroekonomi, dan Sentimen Berita -> fluktuasi rasio profitabilitas.

Endpoint GET /api/analysis?ratio=roe|roa|npm&lag=next|same&ticker=
Dihitung langsung dari tabel Gold (features_quarterly.parquet), jadi selalu mengikuti data terbaru.

1) Uji korelasi  : Pearson (linier) dan Spearman (monoton, tahan outlier) + p-value, per variabel.
2) Regresi panel : OLS dengan efek tetap emiten (dummy TLKM/ISAT/EXCL) dan kontrol persistensi
                   (perubahan rasio periode sebelumnya). Koefisien distandarkan (beta), galat baku robust HC1.
3) Kontribusi blok (uji integrasi): selisih R² ketika SATU blok (pasar / makro / sentimen) dikeluarkan dari
   model lengkap + uji F parsial -> menjawab "apakah blok ini menambah daya jelas di atas blok lain".
4) Pembanding ML : jumlah permutation importance per blok dari model hasil retrain terakhir.

Y (variabel terikat):
  lag=next (default) -> Δ rasio kuartal BERIKUTNYA (t -> t+1): apakah kondisi kuartal ini mendahului perubahan.
  lag=same           -> Δ rasio kuartal yang SAMA (t-1 -> t): apakah bergerak bersamaan.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy import stats

from . import config
from .lake import Lake

G = config.GOLD
BLOCKS = {
    "pasar": {"nama": "Data pasar keuangan",
              "vars": {"ret_q": "Return saham kuartalan", "excess_ret_q": "Excess return vs IHSG",
                       "vol_q": "Volatilitas saham", "volume_chg": "Perubahan volume transaksi",
                       "ret_jkse": "Return IHSG"}},
    "makro": {"nama": "Makroekonomi",
              "vars": {"usd_idr_chg": "Perubahan kurs USD/IDR", "bi_rate": "BI-Rate",
                       "bi_rate_chg": "Perubahan BI-Rate", "inflation_yoy": "Inflasi (YoY)"}},
    "sentimen": {"nama": "Sentimen berita industri",
                 "vars": {"sent_mean": "Rata-rata skor sentimen", "sent_neg_share": "Porsi berita negatif",
                          "sent_n": "Jumlah berita"}},
}
RATIOS = {"roe": "roe_ttm", "roa": "roa_ttm", "npm": "npm_ttm"}
_CACHE: dict = {}


def _stars(p) -> str:
    if p is None or np.isnan(p):
        return ""
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""


def _r(v, d=4):
    return None if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else round(float(v), d)


def ols(y: np.ndarray, X: np.ndarray) -> dict:
    """OLS dengan galat baku robust HC1. X sudah termasuk konstanta/dummy."""
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    e = y - X @ beta
    ssr = float(e @ e)
    sst = float(((y - y.mean()) ** 2).sum())
    meat = X.T @ (X * (e ** 2)[:, None])
    cov = xtx_inv @ meat @ xtx_inv * (n / max(n - k, 1))
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    t = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    p = 2 * stats.t.sf(np.abs(t), df=max(n - k, 1))
    r2 = 1 - ssr / sst if sst > 0 else np.nan
    adj = 1 - (1 - r2) * (n - 1) / max(n - k, 1) if sst > 0 else np.nan
    return {"beta": beta, "se": se, "t": t, "p": p, "ssr": ssr, "r2": r2, "adj_r2": adj, "n": n, "k": k}


def partial_f(restricted: dict, full: dict) -> tuple[float, float]:
    q = full["k"] - restricted["k"]
    dfree = full["n"] - full["k"]
    if q <= 0 or dfree <= 0 or full["ssr"] <= 0:
        return np.nan, np.nan
    f = ((restricted["ssr"] - full["ssr"]) / q) / (full["ssr"] / dfree)
    return float(f), float(stats.f.sf(f, q, dfree))


def _design(d: pd.DataFrame, cols: list[str], fe: bool) -> np.ndarray:
    parts = [np.ones((len(d), 1))]
    if fe:
        tick = sorted(d["ticker"].unique())
        for t_ in tick[1:]:
            parts.append((d["ticker"] == t_).to_numpy(float)[:, None])
    if cols:
        parts.append(d[cols].to_numpy(float))
    return np.hstack(parts)


def run(lake: Lake, q: dict):
    ratio_key = str(q.get("ratio", config.TARGET_RATIO.replace("_ttm", ""))).lower()
    ratio = RATIOS.get(ratio_key, "roe_ttm")
    lag = "same" if str(q.get("lag", "next")).lower() == "same" else "next"
    ticker = str(q.get("ticker") or "").upper()
    key = (id(lake), ratio, lag, ticker)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 300:
        return 200, hit[1]

    df = lake.read_parquet_or_empty(G, "features/features_quarterly.parquet")
    if df.empty:
        return 404, {"error": "Fitur Gold belum tersedia."}
    df = df.sort_values(["ticker", "quarter"]).reset_index(drop=True)
    df["d_now"] = df.groupby("ticker")[ratio].diff(1)
    if lag == "next":
        df["y"] = df.groupby("ticker")[ratio].shift(-1) - df[ratio]
        df["ctrl"] = df["d_now"]                       # persistensi: perubahan kuartal ini
    else:
        df["y"] = df["d_now"]
        df["ctrl"] = df.groupby("ticker")["d_now"].shift(1)
    if ticker:
        df = df[df["ticker"] == ticker]
    fe = not ticker and df["ticker"].nunique() > 1

    allvars = [v for b in BLOCKS.values() for v in b["vars"] if v in df]
    # ---- 1) korelasi (pairwise complete)
    corr = []
    for bk, b in BLOCKS.items():
        for v, label in b["vars"].items():
            if v not in df:
                continue
            m = df[["y", v]].dropna()
            row = {"blok": bk, "blok_nama": b["nama"], "variabel": v, "label": label, "n": int(len(m))}
            if len(m) >= 8 and m[v].std() > 0 and m["y"].std() > 0:
                pr, pp = stats.pearsonr(m[v], m["y"])
                sr, sp = stats.spearmanr(m[v], m["y"])
                row.update(pearson_r=_r(pr), pearson_p=_r(pp), spearman_rho=_r(sr), spearman_p=_r(sp),
                           sig=_stars(sp))
            corr.append(row)

    # ---- 2) regresi panel (sampel lengkap yang sama untuk semua model)
    # Variabel yang datanya terlalu jarang/konstan dikeluarkan agar tidak membuang seluruh sampel (listwise).
    has_y = df[df["y"].notna() & df["ctrl"].notna()]
    min_n = max(12, int(0.6 * len(has_y)))
    usable, excluded = [], []
    for v in allvars:
        nn = int(has_y[v].notna().sum())
        sd = has_y[v].std()
        if nn >= min_n and sd and sd > 0:
            usable.append(v)
        else:
            lbl = next(b["vars"][v] for b in BLOCKS.values() if v in b["vars"])
            excluded.append({"variabel": v, "label": lbl, "n": nn,
                             "alasan": "nilai konstan" if nn >= min_n else f"data hanya {nn} dari {len(has_y)} baris"})
    allvars = usable
    d = df.dropna(subset=["y", "ctrl"] + allvars).copy()
    reg = {"n": int(len(d)), "fixed_effect_emiten": fe, "ok": False, "dikecualikan": excluded}
    if allvars and len(d) >= len(allvars) + 8:
        z = d.copy()
        for c in ["y", "ctrl"] + allvars:                       # standarisasi -> koefisien = beta
            sd = z[c].std()
            z[c] = (z[c] - z[c].mean()) / sd if sd and sd > 0 else 0.0
        y = z["y"].to_numpy(float)
        full_cols = ["ctrl"] + allvars
        full = ols(y, _design(z, full_cols, fe))
        base = ols(y, _design(z, ["ctrl"], fe))
        off = 1 + (z["ticker"].nunique() - 1 if fe else 0)
        coefs = []
        for i, c in enumerate(full_cols):
            j = off + i
            blk = next((bk for bk, b in BLOCKS.items() if c in b["vars"]), "kontrol")
            lbl = BLOCKS[blk]["vars"][c] if blk != "kontrol" else "Perubahan rasio periode sebelumnya (kontrol)"
            coefs.append({"variabel": c, "label": lbl, "blok": blk, "beta": _r(full["beta"][j]),
                          "se": _r(full["se"][j]), "t": _r(full["t"][j], 3), "p": _r(full["p"][j]),
                          "sig": _stars(full["p"][j])})
        blocks = []
        for bk, b in BLOCKS.items():
            vs = [v for v in b["vars"] if v in allvars]
            if not vs:
                continue
            without = ols(y, _design(z, [c for c in full_cols if c not in vs], fe))
            alone = ols(y, _design(z, ["ctrl"] + vs, fe))
            f, p = partial_f(without, full)
            blocks.append({"blok": bk, "nama": b["nama"], "n_var": len(vs),
                           "delta_r2_unik": _r(full["r2"] - without["r2"]),
                           "delta_r2_sendiri": _r(alone["r2"] - base["r2"]),
                           "f": _r(f, 3), "p": _r(p), "sig": _stars(p)})
        f_all, p_all = partial_f(base, full)
        reg.update(ok=True, r2_kontrol=_r(base["r2"]), r2_lengkap=_r(full["r2"]), adj_r2_lengkap=_r(full["adj_r2"]),
                   delta_r2_integrasi=_r(full["r2"] - base["r2"]), f_integrasi=_r(f_all, 3), p_integrasi=_r(p_all),
                   sig_integrasi=_stars(p_all), koefisien=coefs, blok=blocks)

    # ---- 3) pembanding: permutation importance model ML per blok
    fi = lake.read_parquet_or_empty(G, "ml/latest/feature_importance.parquet")
    ml_blocks = []
    if len(fi):
        for bk, b in BLOCKS.items():
            ml_blocks.append({"blok": bk, "nama": b["nama"],
                              "importance": _r(fi[fi["feature"].isin(b["vars"])]["importance"].clip(lower=0).sum())})
        ml_blocks.append({"blok": "fundamental", "nama": "Rasio fundamental (pembanding)",
                          "importance": _r(fi[~fi["feature"].isin(allvars + ["ticker"])]["importance"].clip(lower=0).sum())})

    out = {"ratio": ratio, "lag": lag, "ticker": ticker or "SEMUA",
           "y_label": f"Δ {ratio_key.upper()} TTM " + ("kuartal berikutnya (t→t+1)" if lag == "next" else "kuartal yang sama (t−1→t)"),
           "periode": [str(df["quarter"].min()), str(df["quarter"].max())],
           "korelasi": corr, "regresi": reg, "ml_importance_blok": ml_blocks,
           "kesimpulan": _narrate(corr, reg, ratio_key.upper(), lag),
           "catatan": ("Sampel kecil (kuartalan × 3 emiten), sehingga hasil bersifat indikatif. Signifikansi: "
                       "*** p<0,01; ** p<0,05; * p<0,10. Korelasi tidak sama dengan kausalitas.")}
    _CACHE[key] = (time.time(), out)
    return 200, out


def _narrate(corr: list[dict], reg: dict, rname: str, lag: str) -> list[str]:
    lines = []
    when = "kuartal berikutnya" if lag == "next" else "pada kuartal yang sama"
    sig = [c for c in corr if c.get("spearman_p") is not None and c["spearman_p"] < 0.10]
    if not any(c.get("spearman_p") is not None for c in corr):
        lines.append("Korelasi belum bisa dihitung: data pasangan kurang dari 8 baris untuk semua variabel.")
    elif sig:
        parts = [f"{c['label']} ({'+' if c['spearman_rho'] > 0 else '−'}, ρ={c['spearman_rho']:.2f}{c['sig']})"
                 for c in sorted(sig, key=lambda c: c["spearman_p"])]
        lines.append(f"Korelasi Spearman yang signifikan (p<0,10) dengan perubahan {rname} {when}: " + "; ".join(parts) + ".")
    else:
        lines.append(f"Tidak ada variabel yang berkorelasi signifikan (p<0,10) dengan perubahan {rname} {when}.")
    if reg.get("ok"):
        lines.append(f"Menambahkan ketiga blok data eksternal ke model kontrol menaikkan R² dari {reg['r2_kontrol']:.2f} "
                     f"menjadi {reg['r2_lengkap']:.2f} (ΔR²={reg['delta_r2_integrasi']:.2f}; uji F p={reg['p_integrasi']:.3f}"
                     f"{reg['sig_integrasi']}).")
        best = max(reg["blok"], key=lambda b: b["delta_r2_unik"] or 0, default=None)
        if best:
            lines.append(f"Kontribusi unik terbesar berasal dari blok {best['nama'].lower()} "
                         f"(ΔR²={best['delta_r2_unik']:.2f}, p={best['p']:.3f}{best['sig']}).")
        sigc = [c for c in reg["koefisien"] if c["blok"] != "kontrol" and c["p"] is not None and c["p"] < 0.10]
        if sigc:
            lines.append("Dalam regresi bersama, variabel yang signifikan: " + "; ".join(
                f"{c['label']} (β={c['beta']:+.2f}{c['sig']})" for c in sigc) + ".")
    else:
        lines.append(f"Regresi tidak dijalankan: sampel lengkap hanya {reg.get('n', 0)} baris.")
    if reg.get("dikecualikan"):
        lines.append("Dikeluarkan dari regresi karena datanya belum cukup: " + "; ".join(
            f"{x['label']} ({x['alasan']})" for x in reg["dikecualikan"]) + ".")
    return lines

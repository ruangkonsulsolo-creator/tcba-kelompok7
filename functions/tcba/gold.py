"""Silver -> Gold: tabel fitur kuartalan per emiten + label arah rasio profitabilitas.

Kenapa TTM? Laporan keuangan emiten IDX bersifat KUMULATIF (Q1, 6 bulan, 9 bulan, 12 bulan).
Laba kuartal berdiri sendiri = YTD_q - YTD_(q-1) pada tahun yang sama, lalu dijumlah 4 kuartal
terakhir (trailing twelve months) agar rasio antar-kuartal sebanding dan bebas efek musiman.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .lake import Lake

S, G = config.SILVER, config.GOLD
FEATURES_PATH = "features/features_quarterly.parquet"
LABELS = ("turun", "stabil", "naik")


# --------------------------------------------------------------------------- fundamentals
def ttm_ratios(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["period"] = [pd.Period(year=int(y), quarter=int(q), freq="Q") for y, q in zip(f["fiscal_year"], f["quarter"])]
    out = []
    for tic, g in f.groupby("ticker"):
        g = g.set_index("period").sort_index()
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        g["ticker"] = tic
        prev_ytd_ni = g["net_income_ytd"].shift(1)
        prev_ytd_rev = g["revenue_ytd"].shift(1)
        q1 = np.array([p.quarter == 1 for p in g.index])
        g["ni_q"] = np.where(q1, g["net_income_ytd"], g["net_income_ytd"] - prev_ytd_ni)
        g["rev_q"] = np.where(q1, g["revenue_ytd"], g["revenue_ytd"] - prev_ytd_rev)
        g["ni_ttm"] = g["ni_q"].rolling(4, min_periods=4).sum()
        g["rev_ttm"] = g["rev_q"].rolling(4, min_periods=4).sum()
        avg_assets = ((g["total_assets"] + g["total_assets"].shift(4)) / 2).fillna(g["total_assets"])
        avg_equity = ((g["total_equity"] + g["total_equity"].shift(4)) / 2).fillna(g["total_equity"])
        g["roa_ttm"] = g["ni_ttm"] / avg_assets * 100
        g["roe_ttm"] = g["ni_ttm"] / avg_equity * 100
        g["npm_ttm"] = g["ni_ttm"] / g["rev_ttm"] * 100
        g["rev_growth_yoy"] = (g["rev_ttm"] / g["rev_ttm"].shift(4) - 1) * 100
        out.append(g.reset_index(names="period"))
    r = pd.concat(out, ignore_index=True)
    return r.dropna(subset=["roe_ttm", "roa_ttm", "npm_ttm"])


# --------------------------------------------------------------------------- exogenous features
def market_quarterly(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=["ticker", "period"])
    p = prices.copy()
    p["date"] = pd.to_datetime(p["date"])
    p["period"] = p["date"].dt.to_period("Q")
    p = p.sort_values(["ticker", "date"])
    p["logret"] = p.groupby("ticker")["adj_close"].transform(lambda s: np.log(s).diff())
    agg = p.groupby(["ticker", "period"]).agg(
        px_end=("adj_close", "last"), vol_q=("logret", "std"), volume_mean=("volume", "mean"),
        trading_days=("date", "count")).reset_index()
    agg["vol_q"] = agg["vol_q"] * np.sqrt(252) * 100
    agg = agg.sort_values(["ticker", "period"])
    agg["ret_q"] = agg.groupby("ticker")["px_end"].pct_change() * 100
    agg["volume_chg"] = agg.groupby("ticker")["volume_mean"].pct_change() * 100
    idx = agg[agg["ticker"].isin(config.MARKET_INDEX)][["period", "ret_q"]].rename(columns={"ret_q": "ret_jkse"})
    agg = agg[~agg["ticker"].isin(config.MARKET_INDEX)].merge(idx, on="period", how="left")
    agg["excess_ret_q"] = agg["ret_q"] - agg["ret_jkse"]
    return agg[["ticker", "period", "ret_q", "vol_q", "volume_chg", "excess_ret_q", "ret_jkse"]]


def macro_quarterly(fx: pd.DataFrame, bi: pd.DataFrame, infl: pd.DataFrame) -> pd.DataFrame:
    parts = []
    if len(fx):
        x = fx.assign(period=pd.to_datetime(fx["date"]).dt.to_period("Q")).groupby("period")["usd_idr"].mean()
        parts.append(pd.DataFrame({"usd_idr_avg": x, "usd_idr_chg": x.pct_change() * 100}))
    if len(bi):
        b = bi.assign(period=pd.to_datetime(bi["date"]).dt.to_period("Q")).groupby("period")["bi_rate"].last()
        parts.append(pd.DataFrame({"bi_rate": b, "bi_rate_chg": b.diff()}))
    if len(infl):
        i = infl.assign(period=pd.to_datetime(infl["date"]).dt.to_period("Q")).groupby("period")["inflation_yoy"].mean()
        parts.append(pd.DataFrame({"inflation_yoy": i}))
    if not parts:
        return pd.DataFrame(columns=["period"])
    return pd.concat(parts, axis=1).reset_index(names="period")


def sentiment_quarterly(news: pd.DataFrame) -> pd.DataFrame:
    if news.empty or "method" not in news:
        return pd.DataFrame(columns=["ticker", "period"])
    n = news[news["method"].notna()].copy()
    n["period"] = pd.PeriodIndex(n["quarter"], freq="Q")
    n["is_neg"] = (n["sentiment"] == "negative").astype(float)
    return n.groupby(["ticker", "period"]).agg(
        sent_mean=("score", "mean"), sent_n=("news_id", "count"), sent_neg_share=("is_neg", "mean")).reset_index()


# --------------------------------------------------------------------------- label
def direction(delta: float, thr: float) -> str | None:
    if pd.isna(delta):
        return None
    return "naik" if delta > thr else "turun" if delta < -thr else "stabil"


def build_features(lake: Lake) -> dict:
    fund = lake.read_parquet_or_empty(S, "manual_clean/fundamentals.parquet")
    if fund.empty:
        return {"job": "build_gold", "status": "skipped", "reason": "fundamentals belum tersedia di Silver"}
    base = ttm_ratios(fund)
    mkt = market_quarterly(lake.read_parquet_or_empty(S, "market/prices_daily.parquet"))
    mac = macro_quarterly(lake.read_parquet_or_empty(S, "macro/fx_usdidr_daily.parquet"),
                          lake.read_parquet_or_empty(S, "manual_clean/bi_rate.parquet"),
                          lake.read_parquet_or_empty(S, "manual_clean/inflation.parquet"))
    sen = sentiment_quarterly(lake.read_parquet_or_empty(S, "news/news_scored.parquet"))

    df = base.merge(mkt, on=["ticker", "period"], how="left").merge(mac, on="period", how="left")
    df = df.merge(sen, on=["ticker", "period"], how="left")
    for c in ("ret_q", "vol_q", "volume_chg", "excess_ret_q", "ret_jkse", "usd_idr_avg", "usd_idr_chg",
              "bi_rate", "bi_rate_chg", "inflation_yoy", "sent_mean", "sent_n", "sent_neg_share"):
        if c not in df:
            df[c] = np.nan
    df["has_news"] = df["sent_n"].notna().astype(int)
    df[["sent_mean", "sent_neg_share"]] = df[["sent_mean", "sent_neg_share"]].fillna(0.0)
    df["sent_n"] = df["sent_n"].fillna(0)

    tgt = config.TARGET_RATIO
    df = df.sort_values(["ticker", "period"]).reset_index(drop=True)
    for r in ("roe_ttm", "roa_ttm", "npm_ttm"):
        df[f"{r}_chg1"] = df.groupby("ticker")[r].diff(1)
        df[f"{r}_chg4"] = df.groupby("ticker")[r].diff(4)
    df["target_ratio"] = tgt
    df["target_value"] = df[tgt]
    df["target_next"] = df.groupby("ticker")[tgt].shift(-1)
    df["target_delta"] = df["target_next"] - df[tgt]
    thr_cfg = str(config.STABLE_THRESHOLD_PP[tgt]).strip().lower()
    thr = float(df["target_delta"].abs().quantile(1 / 3)) if thr_cfg == "auto" else float(thr_cfg)
    thr = round(thr, 4)
    df["label"] = [direction(d, thr) for d in df["target_delta"]]
    df["predicted_quarter"] = (df["period"] + 1).astype(str)
    df["quarter"] = df["period"].astype(str)
    df["period_end"] = df["period"].dt.end_time.dt.normalize()
    df = df.drop(columns=["period"])

    feature_cols = [
        "roe_ttm", "roa_ttm", "npm_ttm", "roe_ttm_chg1", "roa_ttm_chg1", "npm_ttm_chg1",
        "roe_ttm_chg4", "roa_ttm_chg4", "npm_ttm_chg4", "rev_growth_yoy",
        "ret_q", "vol_q", "volume_chg", "excess_ret_q", "ret_jkse",
        "usd_idr_avg", "usd_idr_chg", "bi_rate", "bi_rate_chg", "inflation_yoy",
        "sent_mean", "sent_n", "sent_neg_share", "has_news",
    ]
    for c in feature_cols:
        if c not in df:
            df[c] = np.nan
    cols = ["ticker", "quarter", "period_end", "predicted_quarter"] + feature_cols + \
           ["target_ratio", "target_value", "target_next", "target_delta", "label"]
    df = df[cols]
    lake.write_parquet(G, FEATURES_PATH, df)
    lake.write_json(G, "features/feature_list.json",
                    {"features": feature_cols, "categorical": ["ticker"], "target_ratio": tgt,
                     "stable_threshold_pp": thr, "labels": list(LABELS)})
    lab = df["label"].dropna()
    return {"job": "build_gold", "status": "ok", "rows": len(df), "labeled": int(lab.size),
            "label_counts": lab.value_counts().to_dict(),
            "latest_quarter": df.groupby("ticker")["quarter"].max().to_dict()}

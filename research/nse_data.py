"""Load NSE F&O stocks and indices, and build the feature table for the morning picker.

Every feature uses only information available at 9:15 on the trading day:
the previous sessions' bars plus today's opening price (gap).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

DATA = Path(__file__).parent / "data" / "nse"
START = "2012-01-01"


def load(name: str) -> pd.DataFrame | None:
    f = DATA / (name.replace(" ", "_").replace("&", "and") + ".csv")
    if not f.exists():
        return None
    d = pd.read_csv(f, parse_dates=["Date"])
    if "Series" in d and d["Series"].dtype == object:
        d = d[d["Series"].isin(["EQ", "BE"]) | d["Series"].isna()]
    d = d.drop_duplicates("Date").set_index("Date").sort_index()
    d = d[d.index >= START]
    for c in ("Open", "High", "Low", "Close", "Volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["Open", "High", "Low", "Close"])
    d = d[(d["Open"] > 0) & (d["High"] >= d["Low"])]
    return d


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    dlt = c.diff()
    up = dlt.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-dlt.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def stock_features(d: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = d["Open"], d["High"], d["Low"], d["Close"], d["Volume"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f = pd.DataFrame(index=d.index)
    # --- known at 9:15 today
    f["gap"] = o / pc - 1
    f["abs_gap"] = f["gap"].abs()
    # --- previous sessions (shift 1 = yesterday)
    S = lambda s: s.shift(1)  # noqa: E731
    f["atr_pct"] = S(atr / c)
    f["atr5_atr20"] = S(tr.rolling(5).mean() / tr.rolling(20).mean())
    f["range1"] = S((h - l) / c)
    f["range1_atr"] = S((h - l) / atr)
    f["nr7"] = S(((h - l) <= (h - l).rolling(7).min()).astype(float))
    f["inside"] = S(((h <= h.shift(1)) & (l >= l.shift(1))).astype(float))
    f["ibs"] = S((c - l) / (h - l).replace(0, np.nan))
    for n in (1, 3, 5, 10, 20, 60):
        f[f"ret{n}"] = S(c.pct_change(n))
    f["ret1_atr"] = f["ret1"] / f["atr_pct"]
    f["oc1"] = S(c / o - 1)  # yesterday's intraday move
    lv = np.log1p(v)
    f["vol_z"] = S((lv - lv.rolling(20).mean()) / lv.rolling(20).std())
    f["vol_ratio5"] = S(v.rolling(5).mean() / v.rolling(50).mean())
    if "DLV_QTY" in d:
        dq = pd.to_numeric(d["DLV_QTY"], errors="coerce")
        dp = dq / v.replace(0, np.nan)
        f["deliv_pct"] = S(dp)
        f["deliv_chg"] = S(dp - dp.rolling(20).mean())
    if "TOTAL_TRADES" in d:
        tt = pd.to_numeric(d["TOTAL_TRADES"], errors="coerce")
        f["trades_z"] = S(np.log1p(tt) - np.log1p(tt).rolling(20).mean())
        f["qty_per_trade_chg"] = S(np.log((v / tt.replace(0, np.nan)) / (v / tt.replace(0, np.nan)).rolling(20).mean()))
    for n in (20, 50, 200):
        f[f"dist_ma{n}"] = S(c / c.rolling(n).mean() - 1)
    f["pos_52w"] = S((c - l.rolling(250).min()) / (h.rolling(250).max() - l.rolling(250).min()))
    f["dist_52wh"] = S(c / h.rolling(250).max() - 1)
    f["rsi14"] = S(rsi(c, 14))
    f["rsi2"] = S(rsi(c, 2))
    up = (c > pc).astype(int)
    f["streak"] = S(up.groupby((up != up.shift()).cumsum()).cumcount() + 1) * np.where(S(up) == 1, 1, -1)
    f["px"] = S(c)
    # --- outcomes from today's open (targets, never used as features)
    f["up_move"] = h / o - 1
    f["dn_move"] = 1 - l / o
    f["oc_move"] = c / o - 1
    f["o"], f["h"], f["l"], f["c"] = o, h, l, c
    f["turnover_cr"] = S((v * c).rolling(20).mean()) / 1e7
    return f


def market_features() -> pd.DataFrame:
    n = load("nifty 50")
    m = pd.DataFrame(index=n.index)
    m["mkt_gap"] = n["Open"] / n["Close"].shift(1) - 1
    m["mkt_ret1"] = n["Close"].pct_change().shift(1)
    m["mkt_ret5"] = n["Close"].pct_change(5).shift(1)
    m["mkt_ret20"] = n["Close"].pct_change(20).shift(1)
    m["mkt_dist_ma50"] = (n["Close"] / n["Close"].rolling(50).mean() - 1).shift(1)
    m["mkt_range1"] = ((n["High"] - n["Low"]) / n["Close"]).shift(1)
    m["mkt_oc_today"] = n["Close"] / n["Open"] - 1  # outcome only (for analysis)
    vix = load("india vix")
    if vix is not None:
        m["vix"] = vix["Close"].shift(1).reindex(m.index)
        m["vix_chg5"] = vix["Close"].pct_change(5).shift(1).reindex(m.index)
        m["vix_z"] = ((vix["Close"] - vix["Close"].rolling(250).mean()) / vix["Close"].rolling(250).std()).shift(1).reindex(m.index)
    m["dow"] = m.index.dayofweek
    # Monthly F&O expiry: last Thursday (until Aug 2025), last Tuesday afterwards
    idx = m.index
    exp_wd = np.where(idx < pd.Timestamp("2025-09-01"), 3, 1)
    month_end = idx + pd.offsets.MonthEnd(0)
    last_exp = month_end - pd.to_timedelta((month_end.dayofweek - exp_wd) % 7, unit="D")
    m["days_to_expiry"] = np.clip(np.asarray((last_exp - idx).days), 0, None)
    m["expiry_week"] = (m["days_to_expiry"] <= 6).astype(float)
    return m


SECTOR_INDEX = {"Banks": "nifty bank", "Financial Services": "nifty financial services", "IT": "nifty it",
                "Auto": "nifty auto", "Pharma & Healthcare": "nifty pharma", "FMCG": "nifty fmcg",
                "Metals & Mining": "nifty metal", "Oil, Gas & Power": "nifty energy",
                "Capital Goods & Infra": "nifty infrastructure", "Realty": "nifty realty",
                "Consumer & Retail": "nifty india consumption", "Telecom": "nifty services sector",
                "Cement & Construction": "nifty commodities", "Chemicals": "nifty commodities"}


def build_panel(min_turnover_cr: float = 20.0) -> pd.DataFrame:
    mkt = market_features()
    sect = {}
    for s, nm in SECTOR_INDEX.items():
        x = load(nm)
        if x is not None:
            sect[s] = pd.DataFrame({"sec_ret1": x["Close"].pct_change().shift(1),
                                    "sec_ret5": x["Close"].pct_change(5).shift(1),
                                    "sec_gap": x["Open"] / x["Close"].shift(1) - 1})
    frames = []
    for sym, sector in U.FNO_SECTOR_OF.items():
        d = load(sym)
        if d is None or len(d) < 300:
            continue
        f = stock_features(d)
        f["sym"] = sym
        f["sector"] = sector
        if sector in sect:
            f = f.join(sect[sector], how="left")
        frames.append(f)
    p = pd.concat(frames).join(mkt, how="inner")
    p = p.reset_index().rename(columns={"index": "Date"})
    p["rel_ret5"] = p["ret5"] - p["mkt_ret5"]
    p["rel_ret20"] = p["ret20"] - p["mkt_ret20"]
    p["gap_vs_mkt"] = p["gap"] - p["mkt_gap"]
    p["gap_vs_sec"] = p["gap"] - p.get("sec_gap", 0)
    p["gap_atr"] = p["gap"] / p["atr_pct"]
    # Cross-sectional ranks per day (stationary across years)
    for col in ("abs_gap", "atr_pct", "vol_z", "ret1", "ret5", "ret20", "range1", "trades_z", "gap_atr", "deliv_chg"):
        if col in p:
            p[f"{col}_rk"] = p.groupby("Date")[col].rank(pct=True)
    # Liquidity filter: skip thin stocks (F&O names that were small in early years)
    p = p[(p["turnover_cr"] >= min_turnover_cr) & p["atr_pct"].notna() & p["gap"].notna()]
    # Drop obviously bad prints (corporate actions not adjusted): gaps beyond 25%
    p = p[p["abs_gap"] < 0.25]
    return p.sort_values(["Date", "sym"]).reset_index(drop=True)


if __name__ == "__main__":
    p = build_panel()
    print(p.shape, p.Date.min(), p.Date.max(), p.sym.nunique())
    p.to_parquet(Path(__file__).parent / "data" / "panel.parquet")
    print("base rate up>=3%:", (p.up_move >= .03).mean().round(4), " down>=3%:", (p.dn_move >= .03).mean().round(4),
          " either:", ((p.up_move >= .03) | (p.dn_move >= .03)).mean().round(4))

"""Which 9:30 readings pick the day's top gainers / losers (and the moves that continue after 9:30)?

For every F&O stock and day: readings from the 9:15-9:30 candles (known at 9:30) and the outcome:
- topper = in the day's top 10 gainers or top 10 losers (close vs yesterday's close);
- after = move from the 9:30 price (9:25 candle close) to 15:25, in the direction of the stock's move so far today
  (continuation; the tradable part).
Usage: python research/toppers_study.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402


def features(bars: dict, nifty: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = nifty[~nifty.index.duplicated()].sort_index()
    nd = n.index.normalize()
    n15 = {}
    for d, g in n.groupby(nd):
        a = g[g.index.strftime("%H:%M") < "09:30"]
        if len(a) >= 3:
            n15[d] = (a["Close"].iloc[-1] / a["Open"].iloc[0] - 1) * 100
    for sym, df in bars.items():
        if sym not in U.FNO_SECTOR_OF:
            continue
        x = df[~df.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        day = x.index.normalize()
        d = x.groupby(day).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"), v=("Volume", "sum"))
        pc = d["c"].shift()
        tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift()
        sma20 = d["c"].rolling(20).mean().shift()
        first = x[x.index.strftime("%H:%M") < "09:30"]
        f = first.groupby(first.index.normalize()).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"),
                                                         c=("Close", "last"), v=("Volume", "sum"), n=("Close", "size"),
                                                         up=("Close", lambda s: 0))
        cols = first.assign(dirc=np.sign(first["Close"] - first["Open"])).groupby(first.index.normalize())["dirc"].sum()
        vavg = f["v"].rolling(20, min_periods=5).mean().shift()
        for dd in f.index:
            if dd not in d.index or f.at[dd, "n"] < 3:
                continue
            i = d.index.get_loc(dd)
            if i < 15 or not np.isfinite(atr.iloc[i]) or atr.iloc[i] <= 0:
                continue
            P, A = pc.iloc[i], atr.iloc[i]
            o, h, l, c = f.at[dd, "o"], f.at[dd, "h"], f.at[dd, "l"], f.at[dd, "c"]
            close = d.at[dd, "c"]
            day_930 = (c / P - 1) * 100
            sd = np.sign(day_930) if day_930 != 0 else 1
            yh, yl = d["h"].iloc[i - 1], d["l"].iloc[i - 1]
            rows.append({
                "day": dd, "sym": sym, "sector": U.FNO_SECTOR_OF[sym],
                "gap_pct": (o / P - 1) * 100, "gap_atr": (o - P) / A, "r15_pct": (c / o - 1) * 100, "r15_atr": (c - o) / A,
                "day930_pct": day_930, "day930_atr": (c - P) / A, "orb_atr": (h - l) / A, "atr_pct": A / P * 100,
                "rvol15": f.at[dd, "v"] / vavg.loc[dd] if vavg.loc[dd] and vavg.loc[dd] > 0 else np.nan,
                "clv": (c - l) / (h - l) if h > l else 0.5, "same3": abs(cols.loc[dd]) == 3,
                "agree": np.sign(c - o) == np.sign(o - P),       # first 15 min continues the gap
                "beyond_y": 1 if c > yh else (-1 if c < yl else 0), "vs_yrange": (c - yl) / (yh - yl) if yh > yl else 0.5,
                "trend20": (P / sma20.iloc[i] - 1) * 100 if np.isfinite(sma20.iloc[i]) else np.nan,
                "yday_ret": (P / d["c"].iloc[i - 2] - 1) * 100 if i >= 2 else np.nan,
                "yday_rng_atr": (yh - yl) / A, "nifty15": n15.get(dd, np.nan),
                "day_pct": (close / P - 1) * 100, "after_pct": (close / c - 1) * 100, "dir930": sd,
                "cont_pct": sd * (close / c - 1) * 100,
            })
    t = pd.DataFrame(rows)
    t["sec_r15"] = t.groupby(["day", "sector"])["r15_pct"].transform("mean")
    t["sec_day930"] = t.groupby(["day", "sector"])["day930_pct"].transform("mean")
    t["rel_nifty15"] = t["r15_pct"] - t["nifty15"]
    t["rank_gain"] = t.groupby("day")["day_pct"].rank(ascending=False)
    t["rank_loss"] = t.groupby("day")["day_pct"].rank(ascending=True)
    t["topper"] = (t["rank_gain"] <= 10) | (t["rank_loss"] <= 10)
    t["rank930_abs"] = t.groupby("day")["day930_pct"].transform(lambda s: s.abs().rank(ascending=False))
    return t


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    t = features(bars, ix["NIFTY"])
    t.to_parquet(Path(sys.argv[1]).with_name("toppers.parquet"))
    print(len(t), "stock-days,", t["day"].nunique(), "days,", int(t["topper"].sum()), "toppers")

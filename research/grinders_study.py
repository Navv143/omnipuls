"""'Grinders': stocks that open flat (|gap| <= 0.3 ATR) but move all day to finish >= 1.25 ATR from yesterday's close.
What do they look like at 9:30 / 10:00 / 10:30 / 11:00 / 12:00 compared with the other flat-open stocks, and is the
rest of their move tradable from each checkpoint?
Usage: python research/grinders_study.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

CHECKS = ("09:30", "10:00", "10:30", "11:00", "12:00")
FLAT_GAP, BIG_DAY = 0.3, 1.25


def build(bars: dict, nifty: pd.DataFrame) -> pd.DataFrame:
    n = nifty[~nifty.index.duplicated()].sort_index()
    n_at = {}
    for d, g in n.groupby(n.index.normalize()):
        o = g["Open"].iloc[0]
        for T in CHECKS:
            a = g[g.index.strftime("%H:%M") < T]
            if len(a):
                n_at[(d, T)] = (a["Close"].iloc[-1] / o - 1) * 100
    rows = []
    for sym, df in bars.items():
        if sym not in U.FNO_SECTOR_OF:
            continue
        x = df[~df.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        dd = x.index.normalize()
        d = x.groupby(dd).agg(o=("Open", "first"), h=("High", "max"), l=("Low", "min"), c=("Close", "last"))
        pc = d["c"].shift()
        tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift()
        rng = d["h"] - d["l"]
        nr7 = rng.shift() <= rng.shift().rolling(7).min()
        hi20, lo20 = d["h"].rolling(20).max().shift(), d["l"].rolling(20).min().shift()
        hm = x.index.strftime("%H:%M")
        # usual cumulative volume by time of day (20 previous days)
        cumv = x["Volume"].groupby(dd).cumsum()
        cum_tab = cumv.groupby([dd, hm]).last().unstack()
        cum_avg = cum_tab.rolling(20, min_periods=5).mean().shift()
        for day, g in x.groupby(dd):
            i = d.index.get_loc(day)
            if i < 20 or not np.isfinite(atr.iloc[i]) or atr.iloc[i] <= 0:
                continue
            A, P, O = atr.iloc[i], pc.iloc[i], d["o"].iloc[i]
            gap_atr = (O - P) / A
            if abs(gap_atr) > FLAT_GAP:
                continue
            C = d["c"].iloc[i]
            day_atr = (C - P) / A
            ghm = g.index.strftime("%H:%M")
            tp = (g["High"] + g["Low"] + g["Close"]) / 3
            vw = (tp * g["Volume"]).cumsum() / g["Volume"].replace(0, np.nan).cumsum()
            for T in CHECKS:
                a = g[ghm < T]
                if len(a) < 3:
                    continue
                c = a["Close"].iloc[-1]
                mv = (c - P) / A
                sd = np.sign(mv) if mv != 0 else 1
                vwa = vw[ghm < T]
                above = ((a["Close"] - vwa) * sd > 0).mean()
                body = (np.sign(a["Close"] - a["Open"]) == sd).mean()
                ext = a["High"].max() if sd > 0 else a["Low"].min()
                pull = abs(ext - c) / max(abs(ext - O), 1e-9)
                lastT = ghm[ghm < T][-1]
                usual = cum_avg.at[day, lastT] if (day in cum_avg.index and lastT in cum_avg.columns) else np.nan
                rows.append({
                    "day": day, "sym": sym, "sector": U.FNO_SECTOR_OF[sym], "T": T, "gap_atr": gap_atr,
                    "move_atr": mv, "from_open_atr": (c - O) / A, "dir": sd,
                    "rel_nifty": sd * ((c / O - 1) * 100 - n_at.get((day, T), np.nan)),
                    "rvol": a["Volume"].sum() / usual if usual and usual > 0 else np.nan,
                    "vwap_hold": above, "body_with": body, "pullback": pull,
                    "range_atr": (a["High"].max() - a["Low"].min()) / A,
                    "atr_pct": A / P * 100, "yday_rng_atr": rng.iloc[i - 1] / A, "nr7": bool(nr7.iloc[i]),
                    "room_atr": ((hi20.iloc[i] - c) if sd > 0 else (c - lo20.iloc[i])) / A,
                    "day_atr": day_atr, "grinder": abs(day_atr) >= BIG_DAY,
                    "same_dir_close": np.sign(day_atr) == sd,
                    "rest_pct": sd * (C / c - 1) * 100,          # the move from T to the close, in its direction
                })
    t = pd.DataFrame(rows)
    t["sec_with"] = t.groupby(["day", "T", "sector"])["move_atr"].transform("mean") * t["dir"]
    t["rank_abs"] = t.groupby(["day", "T"])["move_atr"].transform(lambda s: s.abs().rank(ascending=False))
    return t


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    t = build(bars, ix["NIFTY"])
    t.to_parquet(Path(sys.argv[1]).with_name("grinders.parquet"))
    g = t[t["T"] == "09:30"]
    print(len(g), "flat-open stock-days;", int(g["grinder"].sum()), "grinders", f"({g['grinder'].mean() * 100:.1f}%)")

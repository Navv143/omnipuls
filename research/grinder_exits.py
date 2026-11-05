"""Grinder candidates: how fast does the move come after entry, and which target / stop / time limit works best?

For every flat-open stock that has already moved >= 0.3 ATR at 10:00 / 10:30 / 11:00 (rows from grinders_study.py),
enter at the open of the checkpoint candle (the next candle after the readings) and follow the rest of the day:
- best move in our favour (MFE) and worst against (MAE) within 30 / 60 / 120 minutes and by the close, in ATR;
- minutes until the day's best price after entry (t_peak);
- target / stop / time-limit grid (stop first when both are hit in one candle, 0.12% costs).
Usage: python research/grinder_exits.py fno60.pkl grinders.parquet
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CHECKS = ("10:00", "10:30", "11:00")
COST = 0.12
WINDOWS = (30, 60, 120)


def paths(bars: dict, t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t = t[t["T"].isin(CHECKS) & (t["move_atr"] * t["dir"] >= 0.3)]
    for sym, g in t.groupby("sym"):
        x = bars[sym]
        x = x[~x.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        byday = {d: v for d, v in x.groupby(x.index.normalize())}
        for r in g.itertuples(index=False):
            d = byday.get(r.day)
            if d is None:
                continue
            hm = d.index.strftime("%H:%M")
            pre, post = d[hm < r.T], d[hm >= r.T]
            if len(post) < 3 or len(pre) < 3:
                continue
            e = post["Open"].iloc[0]
            A = r.atr_pct / 100 * e                       # ATR in price
            sd = r.dir
            fav = ((post["High"] if sd > 0 else -post["Low"]) - sd * e) / A
            adv = (sd * e - (post["Low"] if sd > 0 else -post["High"])) / A
            cl = sd * (post["Close"] - e) / A
            mins = ((post.index - post.index[0]).total_seconds() / 60 + 5).to_numpy()   # minutes at candle end
            opp = pre["Low"].min() if sd > 0 else pre["High"].max()
            row = r._asdict()
            row.update({"entry": e, "A": A, "opp_atr": abs(e - opp) / A,
                        "fav": fav.to_numpy(), "adv": adv.to_numpy(), "cl": cl.to_numpy(), "mins": mins,
                        "mfe_close": fav.max(), "mae_close": adv.max(), "ret_close": cl.iloc[-1],
                        "t_peak": mins[int(np.argmax(fav.to_numpy()))]})
            for w in WINDOWS:
                k = mins <= w
                row[f"mfe_{w}"] = fav[k].max()
                row[f"mae_{w}"] = adv[k].max()
                row[f"ret_{w}"] = cl[k].iloc[-1]
            rows.append(row)
    return pd.DataFrame(rows)


def sim(p: pd.DataFrame, tp: float, sl, limit: int) -> pd.Series:
    """% result per trade: target tp ATR, stop sl ATR (or 'opp' = the day's opposite extreme before entry), exit at
    the close of the last candle within `limit` minutes (or 15:25)."""
    out = []
    for r in p.itertuples(index=False):
        s = r.opp_atr if sl == "opp" else sl
        k = r.mins <= limit
        fav, adv, cl = r.fav[k], r.adv[k], r.cl[k]
        res = cl[-1]
        for f, a in zip(fav, adv):
            if a >= s:
                res = -s
                break
            if f >= tp:
                res = tp
                break
        out.append(res * r.A / r.entry * 100 - COST)
    return pd.Series(out, index=p.index)


if __name__ == "__main__":
    bars, _ = pickle.load(open(sys.argv[1], "rb"))
    t = pd.read_parquet(sys.argv[2])
    p = paths(bars, t)
    p.drop(columns=["fav", "adv", "cl", "mins"]).to_parquet(Path(sys.argv[2]).with_name("grinder_exits.parquet"))
    pickle.dump(p, open(Path(sys.argv[2]).with_name("grinder_paths.pkl"), "wb"))
    print(len(p), "candidate entries")

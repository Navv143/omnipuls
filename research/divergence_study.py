"""Stocks and sectors that go their own way: with or against Nifty.

At 9:30 / 10:00 / 10:30 / 11:00 every stock already >= 0.5 ATR from yesterday's close is put in one of four groups
by its own direction, Nifty's direction (vs yesterday's close) and its sector's direction (other stocks of the sector):
  with/with       stock with Nifty, sector with Nifty
  with/sec-against stock with Nifty, its sector against
  against/sec-against stock against Nifty, its sector against too (a sector going its own way)
  against/alone   stock against Nifty while its sector follows Nifty
Outcome: finishes >= 1.25 ATR its way, and the rest of the move from the next candle's open to 15:25, in its direction,
after 0.12% costs.
Usage: python research/divergence_study.py fno60.pkl move_panel.parquet
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CHECK = {"09:25": "09:30", "09:55": "10:00", "10:25": "10:30", "10:55": "11:00"}   # panel candle -> time known


def build(bars: dict, nifty: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    n = nifty[~nifty.index.duplicated()].sort_index()
    nd = n.index.normalize()
    n_pc = n.groupby(nd)["Close"].last().shift()
    n_vs_pc = (n["Close"] / n_pc.reindex(nd).to_numpy() - 1) * 100
    n_at = pd.DataFrame({"day": nd, "hm": n.index.strftime("%H:%M"), "nifty_pc": n_vs_pc.to_numpy()})
    p = panel[panel["hm"].isin(list(CHECK))].merge(n_at, on=["day", "hm"], how="left").reset_index(drop=True)
    # sector direction from the other stocks of the sector
    g = p.groupby(["day", "hm", "sector"])["day_atr"]
    s_sum, s_n = g.transform("sum"), g.transform("size")
    p["sec_ex"] = (s_sum - p["day_atr"]) / (s_n - 1).replace(0, np.nan)
    p["sec_n"] = s_n
    # outcome from the bars
    out, idx = [], []
    for sym, q in p.groupby("sym"):
        x = bars[sym]
        x = x[~x.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        byday = {d: v for d, v in x.groupby(x.index.normalize())}
        for r in q.itertuples(index=True):
            idx.append(r.Index)
            d = byday.get(r.day)
            if d is None:
                out.append((np.nan, np.nan, np.nan, np.nan))
                continue
            hm = d.index.strftime("%H:%M")
            post = d[hm > r.hm]
            if len(post) < 3:
                out.append((np.nan, np.nan, np.nan, np.nan))
                continue
            e, close = post["Open"].iloc[0], post["Close"].iloc[-1]
            sd = 1 if r.day_atr >= 0 else -1
            A = r.atr_pct / 100 * e
            fav = ((post["High"] if sd > 0 else -post["Low"]) - sd * e).to_numpy() / A
            adv = (sd * e - (post["Low"] if sd > 0 else -post["High"])).to_numpy() / A
            out.append((sd * (close / e - 1) * 100, fav, adv, e))
    o = pd.DataFrame(out, columns=["rest_pct", "fav", "adv", "entry"], index=idx)
    p = p.join(o)
    p["T"] = p["hm"].map(CHECK)
    p["dir"] = np.sign(p["day_atr"]).replace(0, 1)
    p["nifty_dir"] = np.sign(p["nifty_pc"]).replace(0, 1)
    p["sec_dir"] = np.sign(p["sec_ex"]).replace(0, 1)
    with_n = p["dir"] == p["nifty_dir"]
    sec_with_n = p["sec_dir"] == p["nifty_dir"]
    p["group"] = np.select([with_n & sec_with_n, with_n & ~sec_with_n, ~with_n & ~sec_with_n, ~with_n & sec_with_n],
                           ["with/with", "with/sec-against", "against/sec-against", "against/alone"], default="")
    return p


def sim(p: pd.DataFrame, tp: float, sl: float) -> pd.Series:
    res = []
    for r in p.itertuples(index=False):
        out = None
        for f, a in zip(r.fav, r.adv):
            if a >= sl:
                out = -sl
                break
            if f >= tp:
                out = tp
                break
        res.append((out * r.atr_pct if out is not None else r.rest_pct) - 0.12)
    return pd.Series(res, index=p.index)


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    panel = pd.read_parquet(sys.argv[2])
    days = sorted(panel["day"].unique())[14:]
    panel = panel[panel["day"].isin(days)]
    p = build(bars, ix["NIFTY"], panel)
    p.drop(columns=["fav", "adv"]).to_parquet(Path(sys.argv[2]).with_name("divergence.parquet"))
    pickle.dump(p, open(Path(sys.argv[2]).with_name("divergence.pkl"), "wb"))
    print(len(p), "rows")

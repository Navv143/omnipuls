"""Sector leg + its top 2 stocks (instead of Nifty).

Sector index = average move (ATR from yesterday's close) of the sector's stocks, every 5 minutes (sectors with >= 5
stocks). Two ways in, both directions:
  A. sector breakout: between 11:00 and 14:00 the sector index closes above (below) its last-hour high (low) by
     `margin` ATR - first per sector, day and side;
  B. midday check (11:00 / 12:00 / 13:00): sectors already >= `min_sec` ATR one way.
Then take the sector's top 2 stocks that way (biggest move today), optionally filtered (beyond VWAP, volume, quiet,
near the day's extreme). Nifty is only used to split the results (with / against Nifty).
Entry at the next candle's open, stop first, 0.12% costs (nifty_leaders_study.sim).
Usage: python research/sector_leaders_study.py fno60.pkl move_panel.parquet
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nifty_leaders_study import sim  # noqa: E402


def sector_index(panel: pd.DataFrame) -> pd.DataFrame:
    s = panel.groupby(["day", "sector", "hm"]).agg(sec=("day_atr", "mean"), n=("day_atr", "size"),
                                                   up=("day_atr", lambda x: (x > 0).mean())).reset_index()
    s = s[s["n"] >= 5].sort_values(["day", "sector", "hm"])
    g = s.groupby(["day", "sector"])["sec"]
    s["hi12"] = g.transform(lambda x: x.rolling(12).max().shift())
    s["lo12"] = g.transform(lambda x: x.rolling(12).min().shift())
    return s


def breakouts(si: pd.DataFrame, margin: float = 0.05, first="11:00", last="14:00") -> pd.DataFrame:
    m = (si["hm"] >= first) & (si["hm"] <= last)
    up = si[m & (si["sec"] > si["hi12"] + margin)].assign(side=1)
    dn = si[m & (si["sec"] < si["lo12"] - margin)].assign(side=-1)
    return pd.concat([up, dn]).sort_values("hm").groupby(["day", "sector", "side"]).head(1)


def checks(si: pd.DataFrame, min_sec: float = 0.3, times=("10:55", "11:55", "12:55")) -> pd.DataFrame:
    c = si[si["hm"].isin(times) & (si["sec"].abs() >= min_sec)].copy()
    c["side"] = np.sign(c["sec"]).astype(int)
    return c


def top2(panel: pd.DataFrame, trig: pd.DataFrame, k: int = 2) -> pd.DataFrame:
    key = panel.set_index(["day", "hm", "sector"]).sort_index()
    out = []
    for t in trig.itertuples(index=False):
        try:
            c = key.loc[(t.day, t.hm, t.sector)].reset_index()
        except KeyError:
            continue
        c = c.assign(side=t.side, sec=t.sec, mv=c["day_atr"] * t.side)
        c["sec_rank"] = c["mv"].rank(ascending=False)
        out.append(c)
    a = pd.concat(out, ignore_index=True)
    a["vwap_ok"] = a["vwap_dist"] * a["side"] > 0
    a["near_ext"] = np.where(a["side"] > 0, a["hod_dist"], a["lod_dist"]) <= 0.3
    a["with_nifty"] = np.sign(a["n_day"]) == a["side"]
    a["r12s"] = a["r12"] * a["side"]
    return a


if __name__ == "__main__":
    bars, ix = pickle.load(open(sys.argv[1], "rb"))
    panel = pd.read_parquet(sys.argv[2])
    days = sorted(panel["day"].unique())[14:]
    panel = panel[panel["day"].isin(days) & np.isfinite(panel["atr_pct"])]
    half = days[len(days) // 2]
    nd = len(days)
    si = sector_index(panel)

    def rep(name, z, exits=((9, 9, 60), (9, 9, 120), (9, 9, 999), (1.0, 0.5, 999), (1.5, 0.75, 999))):
        if len(z) < 20:
            print(f"  {name:58s} n={len(z)} (too few)")
            return
        for tp, sl, lim in exits:
            r = sim(bars, z, tp, sl, lim)
            lab = (f"hold {lim}m" if lim < 999 else "hold close") if tp >= 9 else f"tp {tp} sl {sl}"
            print(f"  {name:58s} {lab:11s} {len(z) / nd:4.1f}/day avg {r.mean():+.3f}% "
                  f"halves {r[z['day'] < half].mean():+.3f}/{r[z['day'] >= half].mean():+.3f} win {(r > 0).mean() * 100:.0f}%")
        print()

    for title, trig in (("A. sector breakout of its last hour, 11:00-14:00", breakouts(si)),
                        ("B. midday check, sector already >= 0.3 ATR (11:00 / 12:00 / 13:00)", checks(si))):
        a = top2(panel, trig)
        print(f"\n=== {title}: {trig.groupby('day').size().mean():.1f} sector signals a day ===")
        for s, nm in ((1, "UP"), (-1, "DOWN")):
            b = a[a["side"] == s]
            print(f"-- {nm}")
            rep("top 2 of the sector", b[b["sec_rank"] <= 2])
            rep("top 2, beyond VWAP, near the day's extreme", b[(b["sec_rank"] <= 2) & b["vwap_ok"] & b["near_ext"]])
            rep("top 2, volume >= 1.5x", b[(b["sec_rank"] <= 2) & (b["rvol"] >= 1.5)])
            rep("top 2, sector against Nifty", b[(b["sec_rank"] <= 2) & ~b["with_nifty"]])
            rep("top 2, sector with Nifty", b[(b["sec_rank"] <= 2) & b["with_nifty"]])
            rep("rest of the sector (rank 3+), for comparison", b[b["sec_rank"] > 2], exits=((9, 9, 999), (1.5, 0.75, 999)))

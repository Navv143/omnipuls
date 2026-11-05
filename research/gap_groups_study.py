"""Top 10 gainers / losers by opening gap group (0-0.5%, 0.5-1%, 1-3%, > 3%, either direction): how many come from each
group, and WHEN their open-to-close move happens (how much of it is still left at 9:30 ... 13:00).
Usage: python research/gap_groups_study.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

GROUPS = ["0-0.5%", "0.5-1%", "1-3%", ">3%"]
TIMES = ["09:20", "09:30", "09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "14:00"]


def group(g):
    a = abs(g)
    return GROUPS[0] if a < 0.5 else GROUPS[1] if a < 1 else GROUPS[2] if a < 3 else GROUPS[3]


def build(bars: dict) -> pd.DataFrame:
    rows = []
    for sym, df in bars.items():
        if sym not in U.FNO_SECTOR_OF:
            continue
        x = df[~df.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        days = list(x.groupby(x.index.normalize()))
        for k in range(1, len(days)):
            d0, g = days[k]
            pc = days[k - 1][1]["Close"].iloc[-1]
            o, c = g["Open"].iloc[0], g["Close"].iloc[-1]
            hm = g.index.strftime("%H:%M")
            r = {"day": d0, "sym": sym, "gap": (o / pc - 1) * 100, "pct": (c / pc - 1) * 100, "oc": (c / o - 1) * 100}
            for T in TIMES:
                a = g[hm < T]
                r[f"at_{T}"] = (a["Close"].iloc[-1] / o - 1) * 100 if len(a) else 0.0
            # when the stock first reached half of its open-to-close move
            path = (g["Close"] / o - 1) * 100
            tgt = r["oc"] / 2
            hit = path[(path >= tgt)] if r["oc"] > 0 else path[(path <= tgt)]
            r["half_time"] = hit.index[0].strftime("%H:%M") if len(hit) else "15:25"
            rows.append(r)
    t = pd.DataFrame(rows)
    t["grp"] = t["gap"].map(group)
    t["top_g"] = t.groupby("day")["pct"].rank(ascending=False) <= 10
    t["top_l"] = t.groupby("day")["pct"].rank() <= 10
    return t


if __name__ == "__main__":
    bars, _ = pickle.load(open(sys.argv[1], "rb"))
    t = build(bars)
    for nm, m, way in (("TOP 10 GAINERS", "top_g", 1), ("TOP 10 LOSERS", "top_l", -1)):
        z = t[t[m]]
        print(f"\n{nm}: share of the open-to-close move still LEFT at each time (median), and when half was done")
        print(f"  {'gap group':9s} {'share':>6s} " + " ".join(f"{T:>6s}" for T in TIMES) + "  half done by (median)")
        for gname in GROUPS:
            q = z[z["grp"] == gname]
            if q.empty:
                continue
            left = [((q["oc"] - q[f"at_{T}"]) / q["oc"].where(q["oc"].abs() > 0.05)).median() * 100 for T in TIMES]
            print(f"  {gname:9s} {len(q) / len(z) * 100:5.0f}% " + " ".join(f"{v:5.0f}%" for v in left) + f"  {q['half_time'].median() if False else sorted(q['half_time'])[len(q) // 2]}")

"""After a V3-type breakout, hour by hour: where is the price, how far did it go each hour (high / low), and what does
the first hour say about the rest of the day?

Candidates: the 10 biggest movers at 9:30 (ATR) that close beyond their 9:15-9:30 range by 12:00 (entry at the next
candle's open, its direction). For each hour after entry (until 15:20): move from entry at the hour's end, best and
worst move inside that hour, in % (after 0.12% costs only on the final result).
Usage: python research/breakout_hourly.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

HOURS = 5


def build(bars: dict) -> pd.DataFrame:
    rows = []
    for sym, df in bars.items():
        if sym not in U.FNO_SECTOR_OF:
            continue
        x = df[~df.index.duplicated()].sort_index()
        x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:25")]
        days = list(x.groupby(x.index.normalize()))
        d = pd.DataFrame([(dd, g["High"].max(), g["Low"].min(), g["Close"].iloc[-1]) for dd, g in days],
                         columns=["day", "h", "l", "c"]).set_index("day")
        pc = d["c"].shift()
        tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift()
        for k in range(15, len(days)):
            dd, g = days[k]
            A, P = atr.loc[dd], pc.loc[dd]
            if not (np.isfinite(A) and A > 0):
                continue
            hm = np.asarray(g.index.strftime("%H:%M"))
            n0 = int((hm < "09:30").sum())
            if n0 < 3 or n0 >= len(g) - 3:
                continue
            mv = (g["Close"].iloc[n0 - 1] - P) / A
            sd = 1 if mv >= 0 else -1
            orh, orl = g["High"].iloc[:n0].max(), g["Low"].iloc[:n0].min()
            brk = None
            for j in range(n0, len(g) - 1):
                if hm[j] > "12:00":
                    break
                c = g["Close"].iloc[j]
                if (sd > 0 and c > orh) or (sd < 0 and c < orl):
                    brk = j
                    break
            r = {"day": dd, "sym": sym, "sd": sd, "mv930": mv, "brk_t": hm[brk] if brk is not None else None}
            if brk is not None:
                e_ts, e = g.index[brk + 1], g["Open"].iloc[brk + 1]
                post = g.iloc[brk + 1:]
                post = post[post.index.strftime("%H:%M") < "15:20"]
                for h in range(1, HOURS + 1):
                    w = post[(post.index >= e_ts + pd.Timedelta(hours=h - 1)) & (post.index < e_ts + pd.Timedelta(hours=h))]
                    if w.empty:
                        continue
                    r[f"h{h}"] = sd * (w["Close"].iloc[-1] / e - 1) * 100
                    r[f"h{h}_best"] = (sd * ((w["High"] if sd > 0 else w["Low"]) / e - 1) * 100).max()
                    r[f"h{h}_worst"] = (sd * ((w["Low"] if sd > 0 else w["High"]) / e - 1) * 100).min()
                r["close"] = sd * (post["Close"].iloc[-1] / e - 1) * 100 if len(post) else np.nan
            rows.append(r)
    t = pd.DataFrame(rows)
    t["rank"] = t.groupby("day")["mv930"].transform(lambda s: s.abs().rank(ascending=False))
    return t[(t["rank"] <= 10) & t["brk_t"].notna()]


if __name__ == "__main__":
    bars, _ = pickle.load(open(sys.argv[1], "rb"))
    t = build(bars)
    print(f"{len(t)} breakouts of the 9:30 top-10 movers ({t.day.nunique()} days)\n")
    print("Hour by hour after entry (median / average % its way, best and worst inside the hour):")
    for h in range(1, HOURS + 1):
        z = t.dropna(subset=[f"h{h}"])
        print(f"  hour {h}: at the end {z[f'h{h}'].median():+.2f}% (avg {z[f'h{h}'].mean():+.2f}%), positive {(z[f'h{h}'] > 0).mean() * 100:.0f}% | "
              f"best inside {z[f'h{h}_best'].median():+.2f}% | worst inside {z[f'h{h}_worst'].median():+.2f}%  (n {len(z)})")
    c = t["close"] - 0.12
    print(f"  to 15:20: avg {c.mean():+.2f}% after costs, positive {(c > 0).mean() * 100:.0f}%")
    print("\nWhat the first hour says about the rest of the day (hold to 15:20, after costs):")
    for lo, hi, nm in ((-99, -0.5, "hour 1 below -0.5%"), (-0.5, 0, "hour 1 -0.5% to 0"), (0, 0.5, "hour 1 0 to +0.5%"),
                       (0.5, 1.0, "hour 1 +0.5% to +1%"), (1.0, 99, "hour 1 above +1%")):
        z = t[(t["h1"] > lo) & (t["h1"] <= hi)]
        if len(z):
            rest = z["close"] - z["h1"]
            print(f"  {nm:22s} n={len(z):3d}: close {(z['close'] - 0.12).mean():+.2f}% | rest of day after hour 1 {rest.mean():+.2f}% "
                  f"| ends better than at hour 1: {(rest > 0).mean() * 100:.0f}%")
    z = t.dropna(subset=["h1", "h2"])
    for nm, m in (("hour 1 AND hour 2 positive", (z.h1 > 0) & (z.h2 > 0)), ("hour 1 negative, hour 2 negative", (z.h1 < 0) & (z.h2 < 0))):
        q = z[m]
        print(f"  {nm:32s} n={len(q):3d}: close {(q['close'] - 0.12).mean():+.2f}%, rest after hour 2 {(q['close'] - q['h2']).mean():+.2f}%")

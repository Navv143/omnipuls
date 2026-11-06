"""How and when to enter: five entry methods on the same candidates, and the time the breakout happens.

Candidates: each day the 10 F&O stocks with the biggest move (in ATR from yesterday's close) at 9:30 (the 9:15-9:25
candles), side = that move's direction (V3's universe). For each, from 9:30:
  A  market      buy / sell at the 9:30 candle's open
  B  breakout    first 5-min close beyond the 9:15-9:30 range (by 12:00), enter at the next open
  C  retest      after B's break, a limit order at the range edge, filled if price comes back within 60 minutes
  D  vwap        first candle that touches VWAP and closes back on its side (by 11:30), enter at the next open
  E  pullback    first candle against the side after 9:30 that holds above the range middle; enter on a break of its
                 high (low) in the next 3 candles (stop order)
Same exit for all: stop 0.5 ATR from the entry, otherwise 15:20; 0.12% costs. Results in % and R, by gap group and
half; plus the clock: when the breakout (B) and the day's extreme happen.
Usage: python research/entry_timing.py fno60.pkl
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import universe as U  # noqa: E402

COST, STOP = 0.12, 0.5


def _exit(o, h, l, hm, j0, side, e, stop):
    for j in range(j0, len(o)):
        if hm[j] >= "15:20":
            return side * (o[j] / e - 1) * 100
        if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
            px = min(o[j], stop) if side > 0 else max(o[j], stop)
            return side * (px / e - 1) * 100
    return side * (o[-1] / e - 1) * 100


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
            o, h, l, c, v = (g[k_].to_numpy() for k_ in ("Open", "High", "Low", "Close", "Volume"))
            first = hm < "09:30"
            n0 = int(first.sum())
            if n0 < 3 or n0 >= len(g) - 3:
                continue
            c930 = c[n0 - 1]
            mv = (c930 - P) / A
            sd = 1 if mv >= 0 else -1
            orh, orl = h[:n0].max(), l[:n0].min()
            mid = (orh + orl) / 2
            vw = np.cumsum((h + l + c) / 3 * v) / np.maximum(np.cumsum(v), 1)
            r = {"day": dd, "sym": sym, "sd": sd, "mv930": mv, "gap_pct": (o[0] / P - 1) * 100, "A": A,
                 "day_pct": (c[-1] / P - 1) * 100}
            # A market
            e = o[n0]
            r["A_ret"] = _exit(o, h, l, hm, n0, sd, e, e - sd * STOP * A)
            r["A_t"] = hm[n0]
            # B breakout
            brk = None
            for j in range(n0, len(g) - 1):
                if hm[j] > "12:00":
                    break
                if (sd > 0 and c[j] > orh) or (sd < 0 and c[j] < orl):
                    brk = j
                    break
            if brk is not None:
                e = o[brk + 1]
                r["B_ret"] = _exit(o, h, l, hm, brk + 1, sd, e, e - sd * STOP * A)
                r["B_t"] = hm[brk]
                # C retest of the range edge within 60 minutes after the break
                lvl = orh if sd > 0 else orl
                for j in range(brk + 1, min(len(g) - 1, brk + 13)):
                    if (sd > 0 and l[j] <= lvl) or (sd < 0 and h[j] >= lvl):
                        e = lvl if not ((sd > 0 and o[j] < lvl) or (sd < 0 and o[j] > lvl)) else o[j]
                        r["C_ret"] = _exit(o, h, l, hm, j + 1, sd, e, e - sd * STOP * A) if False else None
                        # the fill candle itself can stop us: evaluate from the fill candle (stop first)
                        stop = e - sd * STOP * A
                        if (sd > 0 and l[j] <= stop) or (sd < 0 and h[j] >= stop):
                            r["C_ret"] = sd * (stop / e - 1) * 100
                        else:
                            r["C_ret"] = _exit(o, h, l, hm, j + 1, sd, e, stop)
                        r["C_t"] = hm[j]
                        break
            # D vwap touch and hold
            for j in range(n0, len(g) - 1):
                if hm[j] > "11:30":
                    break
                if (sd > 0 and l[j] <= vw[j] < c[j]) or (sd < 0 and h[j] >= vw[j] > c[j]):
                    e = o[j + 1]
                    r["D_ret"] = _exit(o, h, l, hm, j + 1, sd, e, e - sd * STOP * A)
                    r["D_t"] = hm[j]
                    break
            # E first pullback candle holding the range middle, stop-entry on its extreme
            for j in range(n0, len(g) - 4):
                if hm[j] > "11:30":
                    break
                against = (c[j] < o[j]) if sd > 0 else (c[j] > o[j])
                holds = (l[j] > mid) if sd > 0 else (h[j] < mid)
                if against and holds:
                    trig = h[j] if sd > 0 else l[j]
                    for q in range(j + 1, j + 4):
                        if (sd > 0 and h[q] > trig) or (sd < 0 and l[q] < trig):
                            e = max(o[q], trig) if sd > 0 else min(o[q], trig)
                            stop = e - sd * STOP * A
                            if (sd > 0 and l[q] <= stop) or (sd < 0 and h[q] >= stop):
                                r["E_ret"] = sd * (stop / e - 1) * 100
                            else:
                                r["E_ret"] = _exit(o, h, l, hm, q + 1, sd, e, stop)
                            r["E_t"] = hm[q]
                            break
                    break
            # the clock: when the day's extreme in the side's direction happened
            ext = int(np.argmax(h) if sd > 0 else np.argmin(l))
            r["extreme_t"] = hm[ext]
            rows.append(r)
    t = pd.DataFrame(rows)
    t["rank930"] = t.groupby("day")["mv930"].transform(lambda s: s.abs().rank(ascending=False))
    return t[t["rank930"] <= 10]


def _grp(g):
    a = abs(g)
    return "0-0.5%" if a < 0.5 else "0.5-1%" if a < 1 else "1-3%" if a < 3 else ">3%"


if __name__ == "__main__":
    bars, _ = pickle.load(open(sys.argv[1], "rb"))
    t = build(bars)
    t["grp"] = t["gap_pct"].map(_grp)
    days = sorted(t.day.unique())
    half = days[len(days) // 2]
    t.to_parquet(Path(sys.argv[1]).with_name("entry_timing.parquet"))
    names = {"A": "A market at 9:30", "B": "B breakout close", "C": "C retest of the range edge", "D": "D VWAP pullback",
             "E": "E first pullback, stop entry"}
    print(f"{len(t)} candidates ({len(days)} days, top 10 movers at 9:30)\n")
    for k, nm in names.items():
        z = t.dropna(subset=[f"{k}_ret"])
        r = z[f"{k}_ret"] - COST
        R = r / (STOP * z["A"] / (z["A"] / (z["atr_dummy"] if "atr_dummy" in z else 1)) ) if False else None
        print(f"{nm:30s} fills {len(z) / len(t) * 100:4.0f}%  avg {r.mean():+.3f}%  halves {r[z.day < half].mean():+.3f}/"
              f"{r[z.day >= half].mean():+.3f}  win {(r > 0).mean() * 100:3.0f}%  median time {sorted(z[f'{k}_t'])[len(z) // 2]}")
    print("\nBy gap group (avg % a trade after costs; fills %):")
    print(f"{'group':8s} " + " ".join(f"{k:>14s}" for k in names))
    for g_ in ("0-0.5%", "0.5-1%", "1-3%", ">3%"):
        z = t[t.grp == g_]
        cells = []
        for k in names:
            q = z.dropna(subset=[f"{k}_ret"])
            cells.append(f"{(q[f'{k}_ret'] - COST).mean():+.2f} ({len(q) / max(len(z), 1) * 100:3.0f}%)" if len(q) else "-")
        print(f"{g_:8s} n={len(z):3d} " + " ".join(f"{c:>14s}" for c in cells))
    print("\nThe clock - share of breakouts (B) and of the day's extreme by time:")
    bins = ["09:30", "09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "14:00", "15:30"]
    for col, nm in (("B_t", "breakout close"), ("extreme_t", "day's extreme (high for longs / low for shorts)")):
        s = t[col].dropna()
        cnt = [((s >= a) & (s < b)).mean() * 100 for a, b in zip(bins[:-1], bins[1:])]
        print(f"  {nm:48s} " + " ".join(f"{a}-{b}:{c:3.0f}%" for a, b, c in zip(bins[:-1], bins[1:], cnt)))
    s = t["extreme_t"]
    print(f"  day's extreme before 9:30 (the move was already done): {(s < '09:30').mean() * 100:.0f}%")

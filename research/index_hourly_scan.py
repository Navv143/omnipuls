"""Index setups with a small structure stop, on 3 years of hourly candles (Yahoo 1h): yesterday's high/low break vs
sweep, gap fill vs gap go, first-hour break vs sweep. Entry at the next hourly open, stop at the signal candle's far
end, exit at the close (or the target), 0.03% costs. Usage: python research/index_hourly_scan.py yahoo1h.pkl
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd


def run(x: pd.DataFrame):
    x = x[~x.index.duplicated()].sort_index()
    if x.index.tz is not None:
        x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None)
    days = [(d, g) for d, g in x.groupby(x.index.normalize()) if len(g) >= 6]
    out = []
    for k in range(1, len(days)):
        (d, g), (_, y) = days[k], days[k - 1]
        PH, PL, PC = y["High"].max(), y["Low"].min(), y["Close"].iloc[-1]
        o, h, l, c = (g[c_].to_numpy() for c_ in ("Open", "High", "Low", "Close"))
        fh, fl = h[0], l[0]
        gap = (o[0] / PC - 1) * 100
        rules = {
            "pdh_break": lambda i: (1, l[i]) if c[i] > PH else ((-1, h[i]) if c[i] < PL else None),
            "pdh_sweep": lambda i: (-1, h[i]) if (h[i] > PH and c[i] < PH) else ((1, l[i]) if (l[i] < PL and c[i] > PL) else None),
            "fh_break": lambda i: (1, l[i]) if (i >= 1 and c[i] > fh) else ((-1, h[i]) if (i >= 1 and c[i] < fl) else None),
            "fh_sweep": lambda i: (-1, h[i]) if (i >= 1 and h[i] > fh and c[i] < fh) else ((1, l[i]) if (i >= 1 and l[i] < fl and c[i] > fl) else None),
        }
        if abs(gap) >= 0.4:
            gs = 1 if gap > 0 else -1
            rules["gap_go"] = lambda i, gs=gs: (gs, l[0] if gs > 0 else h[0]) if (i == 0 and np.sign(c[0] - o[0]) == gs) else None
            rules["gap_fill"] = lambda i, gs=gs: (-gs, h[0] if gs > 0 else l[0]) if (i == 0 and np.sign(c[0] - o[0]) == -gs) else None
        for name, f in rules.items():
            for i in range(0, len(g) - 1):
                s = f(i)
                if s is None:
                    continue
                side, stop = s
                e = o[i + 1]
                risk = side * (e - stop)
                if risk <= 0:
                    break
                res = {}
                for tgt in (1, 2, 99):
                    r = None
                    for j in range(i + 1, len(g)):
                        if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
                            r = side * ((min(o[j], stop) if side > 0 else max(o[j], stop)) - e) / risk
                            break
                        if tgt < 99 and ((side > 0 and h[j] >= e + tgt * risk) or (side < 0 and l[j] <= e - tgt * risk)):
                            r = tgt
                            break
                    res[tgt] = (side * (c[-1] - e) / risk if r is None else r) - 0.0003 * e / risk
                out.append({"day": d, "setup": name, "side": side, "risk_pct": risk / e * 100, **{f"R{t}": v for t, v in res.items()}})
                break
    return pd.DataFrame(out)


if __name__ == "__main__":
    data = pickle.load(open(sys.argv[1], "rb"))
    for sym in ("NIFTY", "BANKNIFTY"):
        z = run(data[sym])
        print(f"\n{sym}: {z.day.nunique()} days")
        for (s, sd), q in z.groupby(["setup", "side"]):
            mid = q["day"].quantile(0.5)
            best = max((1, 2, 99), key=lambda t: q[f"R{t}"].mean())
            r = q[f"R{best}"]
            yrs = " ".join(f"{q[q.day.dt.year == y][f'R{best}'].mean():+.2f}" for y in sorted(q.day.dt.year.unique()))
            print(f"  {s:9s} {'long ' if sd > 0 else 'short'} n={len(q):3d} best exit {'close' if best == 99 else f'{best}R'}: "
                  f"{r.mean():+.3f}R halves {r[q.day < mid].mean():+.3f}/{r[q.day >= mid].mean():+.3f} win {(r > 0).mean() * 100:.0f}% "
                  f"risk {q.risk_pct.median():.2f}% t={r.mean() / r.std() * np.sqrt(len(r)):+.1f} years {yrs}")

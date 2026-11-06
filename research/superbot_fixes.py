"""Fixes for the windowed Super Bot's weak points (chosen from research/superbot_weakpoints.py, then each tested with
both halves, monthly totals and worst day). Skipped candidates are replaced by the next best in the same window, as live.

Usage: python research/superbot_fixes.py <bars.pkl> <superbot_candidates.pkl>
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import superbot_backtest as BT   # noqa: E402
import superbot_strict as X      # noqa: E402
import superbot_windows as W     # noqa: E402

WINDOWS = [("10:00", "10:30", 2), ("11:00", "12:00", 2), ("12:00", "12:30", 2)]


def run_cap(c, bars, windows, cap, max_day=99):
    """Like W.run (always) but no new trade once the day's P&L (closed + open marked at that moment) <= -cap %."""
    out = []
    for day, g in c.sort_values(["day", "time", "score"], ascending=[True, True, False]).groupby("day"):
        taken, secs, stocks = [], set(), set()
        for a, b, mx in windows:
            n = 0
            for _, r in g[(g["time"] >= a) & (g["time"] < b)].iterrows():
                if n >= mx or len(taken) >= max_day or r["stock"] in stocks or r["sector"] in secs:
                    continue
                if taken and cap is not None:
                    t0 = day + pd.Timedelta(hours=int(r["time"][:2]), minutes=int(r["time"][3:]))
                    pnl = sum(W.path_pct(bars[x["stock"]][bars[x["stock"]].index.normalize() == day], x, t0) for x in taken)
                    if pnl <= -cap:
                        continue
                taken.append(r)
                stocks.add(r["stock"])
                secs.add(r["sector"])
                n += 1
        out += [dict(x, window=next(f"{a}-{b}" for a, b, _ in windows if a <= x["time"] < b)) for x in taken]
    return pd.DataFrame(out)


def show(name, t, nd):
    p = t["pct"]
    d = t.groupby("day")["pct"].sum()
    mid = sorted(t["day"].unique())[t["day"].nunique() // 2]
    mon = t.groupby(t["day"].dt.strftime("%b"))["pct"].sum().round(1).to_dict()
    print(f"{name:44s} {len(p):3d} tr ({len(p) / nd:.1f}/d) win {(p > 0).mean() * 100:3.0f}% avg {p.mean():+.3f}% "
          f"t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} h1 {p[t['day'] < mid].mean():+.2f} h2 {p[t['day'] >= mid].mean():+.2f} "
          f"| total {p.sum():+5.1f}% worst day {d.min():+.1f}% losing days {(d < 0).sum()} | {mon}")


def main(argv):
    stocks, _ = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items()}
    c = pd.read_pickle(argv[2])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"])
    nd = c["day"].nunique()
    base = W.run(c, bars, WINDOWS)
    show("BASE: 10:00 2 + 11-12 2 + 12:00 2", base, nd)
    for thr in (0.8, 1.0, 1.2, 1.5):
        show(f"skip moved > {thr} day-ATR already", W.run(c[c["move_atr"] <= thr], bars, WINDOWS), nd)
    for thr in (1.5, 2.0, 2.5):
        show(f"skip > {thr}% stronger than Nifty", W.run(c[c["rel_nifty"] <= thr], bars, WINDOWS), nd)
    for cap in (1.0, 1.5, 2.0):
        show(f"day loss cap {cap}% (no new trades)", run_cap(c, bars, WINDOWS, cap), nd)
    for mx in (4, 5):
        show(f"max {mx} trades a day", run_cap(c, bars, WINDOWS, None, mx), nd)
    f = c[c["move_atr"] <= 1.0]
    show("moved <= 1.0 ATR + loss cap 1.5%", run_cap(f, bars, WINDOWS, 1.5), nd)
    show("moved <= 1.0 ATR + max 5 a day", run_cap(f, bars, WINDOWS, None, 5), nd)
    print("\nsame filter on the LIVE rule (11:00-12:00, max 3):")
    show("  live as is", W.run(c, bars, [("11:00", "12:00", 3)]), nd)
    show("  live + moved <= 1.0 ATR", W.run(f, bars, [("11:00", "12:00", 3)]), nd)
    print("\nis the ATR cut steady? all market-aligned candidates (no window / limit), avg % by move_atr band:")
    print(c.groupby(pd.cut(c["move_atr"], [0, 0.5, 0.8, 1.0, 1.2, 1.5, 2, 9]), observed=True)["pct"]
          .agg(["size", "mean", lambda s: (s > 0).mean()]).round(3).to_string())


if __name__ == "__main__":
    main(sys.argv)

"""Super Bot in windows: 9:30-10:00, 10:00-10:30, 12:00-12:30, with an optional day rule (trade the next window only
when the day is flat / losing, or only when it is winning). The day's P&L at a window's start = closed trades plus open
trades marked at that moment's price (only what is known then). Candidates: research/superbot_strict.py (market-aligned).

Usage: python research/superbot_windows.py <bars.pkl> <superbot_candidates.pkl>
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import superbot_backtest as BT   # noqa: E402
import superbot_strict as X      # noqa: E402

COST = 0.12


def path_pct(df_day: pd.DataFrame, r, upto: pd.Timestamp) -> float:
    """The trade's % at time `upto` (closed: its result; open: marked at the last close before `upto`)."""
    et = r["day"] + pd.Timedelta(hours=int(r["entry_at"][:2]), minutes=int(r["entry_at"][3:]))
    if upto <= et:
        return 0.0
    xt = r["day"] + pd.Timedelta(hours=int(str(r["exit_at"])[:2]), minutes=int(str(r["exit_at"])[3:])) \
        if isinstance(r["exit_at"], str) else r["day"] + pd.Timedelta(hours=15, minutes=20)
    if upto > xt:
        return float(r["pct"])
    seen = df_day[(df_day.index >= et) & (df_day.index < upto)]
    if seen.empty:
        return 0.0
    return int(r["side"]) * (float(seen["Close"].iloc[-1]) / float(r["entry"]) - 1) * 100 - COST


def run(c: pd.DataFrame, bars: dict, windows: list, rule: str = "always") -> pd.DataFrame:
    """windows: [(start, end, max)]; rule: always / if_flat_or_losing / if_winning."""
    out = []
    for day, g in c.sort_values(["day", "time", "score"], ascending=[True, True, False]).groupby("day"):
        taken, secs, stocks = [], set(), set()
        for i, (a, b, mx) in enumerate(windows):
            if i > 0 and taken:
                t0 = day + pd.Timedelta(hours=int(a[:2]), minutes=int(a[3:]))
                pnl = sum(path_pct(bars[x["stock"]][bars[x["stock"]].index.normalize() == day], x, t0) for x in taken)
                if rule == "if_flat_or_losing" and pnl > 0:
                    break
                if rule == "if_winning" and pnl <= 0:
                    break
            n = 0
            for _, r in g[(g["time"] >= a) & (g["time"] < b)].iterrows():
                if n >= mx or r["stock"] in stocks or r["sector"] in secs:
                    continue
                taken.append(r)
                stocks.add(r["stock"])
                secs.add(r["sector"])
                n += 1
        out += [dict(x, window=next(f"{a}-{b}" for a, b, _ in windows if a <= x["time"] < b)) for x in taken]
    return pd.DataFrame(out)


def show(name: str, t: pd.DataFrame, n_days: int):
    if t.empty:
        print(f"{name:52s} no trades")
        return
    d = t.groupby("day")["pct"].sum()
    mon = t.groupby(t["day"].dt.strftime("%b"))["pct"].sum().round(1).to_dict()
    tt = t["pct"].mean() / t["pct"].std() * np.sqrt(len(t))
    print(f"{name:52s} {len(t):3d} tr ({len(t) / n_days:.1f}/d) win {(t['pct'] > 0).mean() * 100:3.0f}% avg {t['pct'].mean():+.3f}% "
          f"t {tt:+.2f} | days + {(d > 0).sum()}/{n_days} worst day {d.min():+.1f}% total {t['pct'].sum():+5.1f}% | {mon}")


def main(argv):
    stocks, _ = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items()}
    c = pd.read_pickle(argv[2])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"])
    nd = c["day"].nunique()
    W1, W2, W3 = ("09:30", "10:00"), ("10:00", "10:30"), ("12:00", "12:30")
    print("single windows:")
    for w, mx in ((W1, 2), (W2, 2), (W3, 2), (("11:00", "12:00"), 3)):
        show(f"  only {w[0]}-{w[1]} (max {mx})", run(c, bars, [(w[0], w[1], mx)]), nd)
    for m1, m2, m3 in ((1, 1, 2), (2, 2, 2), (1, 2, 2), (2, 1, 2)):
        ws = [(*W1, m1), (*W2, m2), (*W3, m3)]
        print(f"\nsplit {m1} + {m2} + {m3}:")
        for rule in ("always", "if_flat_or_losing", "if_winning"):
            t = run(c, bars, ws, rule)
            show(f"  {rule}", t, nd)
            if rule == "if_flat_or_losing" and (m1, m2, m3) == (1, 1, 2):
                print("    by window:", t.groupby("window")["pct"].agg(["size", "mean"]).round(3).to_dict("index"))


if __name__ == "__main__":
    main(sys.argv)

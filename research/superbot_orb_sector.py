"""Two questions on the Super Bot's candidates (research/superbot_strict.py, 40 days, every decision-stage arrival):

1. Breakouts: is the entry beyond today's opening range (first 15 / 30 min) or beyond yesterday's high / low (in the
   trade's direction)? Does that help?
2. Direction rule: with Nifty (live) vs with the stock's own SECTOR (its F&O peers' day move, at that moment) vs either vs
   both. Sector-only trades = against Nifty but with the sector (now skipped). Also by sector type: sectors that often
   move apart from Nifty (Pharma, IT, FMCG, Chemicals, Capital Goods, Telecom; research/sector_independence.py).
Each plan picks with the 3-window plan (10:00-10:30 x2, 11:00-12:00 x2, 12:00-12:30 x2; 1 per sector / stock a day).

Usage: python research/superbot_orb_sector.py <bars.pkl> <superbot_candidates.pkl>
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import superbot_backtest as BT   # noqa: E402
import superbot_windows as W     # noqa: E402

WINDOWS = [("10:00", "10:30", 2), ("11:00", "12:00", 2), ("12:00", "12:30", 2)]
INDEPENDENT = {"Pharma & Healthcare", "IT", "FMCG", "Chemicals", "Capital Goods & Infra", "Telecom"}


def pf(p):
    return p[p > 0].sum() / -p[p < 0].sum() if (p < 0).any() else np.inf


def line(name, t, nd):
    if len(t) < 8:
        return f"  {name:52s} n={len(t)}"
    p = t["pct"]
    mid = sorted(t["day"].unique())[t["day"].nunique() // 2]
    d = t.groupby("day")["pct"].sum()
    return (f"  {name:52s} n={len(p):4d} ({len(p) / nd:.1f}/d) win {(p > 0).mean() * 100:3.0f}% PF {pf(p):4.2f} "
            f"avg {p.mean():+.3f}% t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} h1 {p[t['day'] < mid].mean():+.2f} "
            f"h2 {p[t['day'] >= mid].mean():+.2f} total {p.sum():+6.1f}% worst day {d.min():+.1f}%")


def main(argv):
    stocks, _ = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items()}
    c = pd.read_pickle(argv[2]).dropna(subset=["entry"]).reset_index(drop=True)
    nd = c["day"].nunique()
    feats = []
    for _, r in c.iterrows():
        df, sd, px = bars[r["stock"]], int(r["side"]), float(r["entry"])
        day = df[df.index.normalize() == r["day"]]
        prev = df[df.index.normalize() < r["day"]]
        prev = prev[prev.index.normalize() == prev.index.normalize().max()]
        o15, o30 = day[day.index < r["day"] + pd.Timedelta(hours=9, minutes=30)], \
            day[day.index < r["day"] + pd.Timedelta(hours=9, minutes=45)]

        def beyond(hi, lo):
            return bool(px > hi) if sd > 0 else bool(px < lo)
        feats.append({"orb15": beyond(o15["High"].max(), o15["Low"].min()),
                      "orb30": beyond(o30["High"].max(), o30["Low"].min()),
                      "pdhl": beyond(prev["High"].max(), prev["Low"].min()) if len(prev) else False,
                      "inside_yday": bool(prev["Low"].min() <= px <= prev["High"].max()) if len(prev) else False})
    c = pd.concat([c, pd.DataFrame(feats)], axis=1)
    c["nifty_ok"] = ((c["side"] > 0) & (c["nifty_chg"] >= 0)) | ((c["side"] < 0) & (c["nifty_chg"] <= 0))
    c["sector_ok"] = c["sector_side_ok"].astype(bool)
    c["indep"] = c["sector"].isin(INDEPENDENT)

    print("ALL CANDIDATES (no window / limit), avg % a trade after costs:")
    for name, m in (("all", slice(None)), ("with Nifty (live rule)", c["nifty_ok"]), ("with sector", c["sector_ok"]),
                    ("with Nifty AND sector", c["nifty_ok"] & c["sector_ok"]),
                    ("with Nifty, AGAINST sector", c["nifty_ok"] & ~c["sector_ok"]),
                    ("AGAINST Nifty, with sector (now skipped)", ~c["nifty_ok"] & c["sector_ok"]),
                    ("against both", ~c["nifty_ok"] & ~c["sector_ok"]),
                    ("  ... of which independent sectors", ~c["nifty_ok"] & c["sector_ok"] & c["indep"]),
                    ("  ... of which Nifty-linked sectors", ~c["nifty_ok"] & c["sector_ok"] & ~c["indep"])):
        print(line(name, c[m] if not isinstance(m, slice) else c, nd))

    print("\nBREAKOUT FEATURES (market-aligned candidates):")
    a = c[c["nifty_ok"]]
    for col, txt in (("orb15", "beyond 15-min opening range"), ("orb30", "beyond 30-min opening range"),
                     ("pdhl", "beyond yesterday's high / low"), ("inside_yday", "inside yesterday's range")):
        print(line(f"{txt}: yes", a[a[col]], nd))
        print(line(f"{txt}: no", a[~a[col]], nd))

    print("\n3-WINDOW PLAN with each direction rule (skipped stocks replaced by the next best):")
    plans = {"with Nifty (live rule)": c["nifty_ok"],
             "with sector (instead of Nifty)": c["sector_ok"],
             "with Nifty OR sector": c["nifty_ok"] | c["sector_ok"],
             "with Nifty AND sector": c["nifty_ok"] & c["sector_ok"],
             "Nifty, but independent sectors follow their sector": (c["nifty_ok"] & ~c["indep"]) | (c["sector_ok"] & c["indep"]),
             "with Nifty + beyond yesterday's high/low": c["nifty_ok"] & c["pdhl"],
             "with Nifty + beyond 30-min range": c["nifty_ok"] & c["orb30"],
             "with Nifty + beyond 15-min range": c["nifty_ok"] & c["orb15"],
             "with Nifty AND sector + beyond 30-min range": c["nifty_ok"] & c["sector_ok"] & c["orb30"]}
    for name, m in plans.items():
        print(line(name, W.run(c[m], bars, WINDOWS), nd))
    print("\nonly the trades the sector rule ADDS (against Nifty, with sector), as their own 3-window plan:")
    print(line("against Nifty, with sector", W.run(c[~c["nifty_ok"] & c["sector_ok"]], bars, WINDOWS), nd))
    print(line("  same, independent sectors only", W.run(c[~c["nifty_ok"] & c["sector_ok"] & c["indep"]], bars, WINDOWS), nd))
    print("\nby sector, market-aligned 3-window trades:")
    t = W.run(c[c["nifty_ok"]], bars, WINDOWS)
    for k, z in t.groupby("sector"):
        print(line(k, z, nd))


if __name__ == "__main__":
    main(sys.argv)

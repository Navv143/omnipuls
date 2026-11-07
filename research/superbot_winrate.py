"""Can the windowed Super Bot reach 70%+ wins with profit factor > 1.5?

Same entries (3 windows: 10:00-10:30 x2, 11:00-12:00 x2, 12:00-12:30 x2, with the market, 1 per sector / stock; also with
'skip moved > 1.0 day-ATR'), exits re-simulated on 5-minute candles: stop (live swing / 1x / 1.5x / 2x 5-min ATR),
target (0.5R .. 3R / none), breakeven or profit lock after +0.5R / +1R, out at 15:20, cost 0.12%, stop checked first.
A row counts only if BOTH halves of the period also have win >= 70% and PF > 1.5.

Usage: python research/superbot_winrate.py <bars.pkl> <superbot_candidates.pkl>
"""
import itertools
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import superbot_backtest as BT   # noqa: E402
import superbot_exits as EX      # noqa: E402
import superbot_strict as X      # noqa: E402
import superbot_windows as W     # noqa: E402

COST = 0.12
WINDOWS = [("10:00", "10:30", 2), ("11:00", "12:00", 2), ("12:00", "12:30", 2)]


def sim(bars, side, e, stop, target, trig_r, lock):
    """trig_r: after this much profit (in R) move the stop to entry + lock x the best profit (lock 0 = breakeven)."""
    risk = abs(e - stop)
    best = e
    for (_, b), h in zip(bars.iterrows(), bars.index.strftime("%H:%M")):
        o, hi, lo = float(b["Open"]), float(b["High"]), float(b["Low"])
        if h >= "15:20":
            return side * (o / e - 1) * 100 - COST
        if (side > 0 and lo <= stop) or (side < 0 and hi >= stop):
            x = min(o, stop) if side > 0 else max(o, stop)
            return side * (x / e - 1) * 100 - COST
        if target is not None and ((side > 0 and hi >= target) or (side < 0 and lo <= target)):
            x = max(o, target) if side > 0 else min(o, target)
            return side * (x / e - 1) * 100 - COST
        best = max(best, hi) if side > 0 else min(best, lo)
        fav = side * (best - e)
        if trig_r is not None and fav >= trig_r * risk:
            lk = e + side * max(lock * fav, 0.0015 * e)       # at least cover costs
            stop = max(stop, lk) if side > 0 else min(stop, lk)
    return side * (float(bars["Close"].iloc[-1]) / e - 1) * 100 - COST


def pf(p):
    return p[p > 0].sum() / -p[p < 0].sum() if (p < 0).any() else np.inf


def main(argv):
    stocks, _ = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items()}
    c = pd.read_pickle(argv[2])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"])
    sets = {"3 windows": W.run(c, bars, WINDOWS),
            "3 windows, moved <= 1.0 ATR": W.run(c[c["move_atr"] <= 1.0], bars, WINDOWS),
            "live 11-12 x3": W.run(c, bars, [("11:00", "12:00", 3)])}
    for name, t in sets.items():
        print(f"{name}: as now {len(t)} trades, win {(t['pct'] > 0).mean() * 100:.0f}%, PF {pf(t['pct']):.2f}, "
              f"avg {t['pct'].mean():+.3f}%")
    stops = ["live", "1x ATR5", "1.5x ATR5", "2x ATR5"]
    targets = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, None]
    trails = [(None, 0), (0.5, 0.0), (0.5, 0.5), (1.0, 0.0), (1.0, 0.5)]
    rows = []
    for name, t in sets.items():
        prep = []
        for _, r in t.iterrows():
            df = bars[r["stock"]]
            et = r["day"] + pd.Timedelta(hours=int(r["entry_at"][:2]), minutes=int(r["entry_at"][3:]))
            day = df[df.index.normalize() == r["day"]]
            prep.append((r, day[day.index >= et], float(EX.atr5(df[df.index < et]).iloc[-1])))
        mid = sorted(t["day"].unique())[t["day"].nunique() // 2]
        for st, tg, (trig, lock) in itertools.product(stops, targets, trails):
            res, days = [], []
            for r, after, a5 in prep:
                sd, e = int(r["side"]), float(r["entry"])
                stop = float(r["stop"]) if st == "live" else e - sd * float(st.split("x")[0]) * a5
                risk = abs(e - stop)
                if not risk or after.empty:
                    continue
                res.append(sim(after, sd, e, stop, None if tg is None else e + sd * tg * risk, trig, lock))
                days.append(r["day"])
            p, d = np.array(res), np.array(days)
            h1, h2 = p[d < mid], p[d >= mid]
            rows.append({"set": name, "stop": st, "target": "none" if tg is None else f"{tg}R",
                         "trail": "none" if trig is None else f"after {trig}R lock {int(lock * 100)}%",
                         "n": len(p), "win%": round((p > 0).mean() * 100, 1), "PF": round(pf(p), 2),
                         "avg %": round(p.mean(), 3), "avg win": round(p[p > 0].mean(), 2),
                         "avg loss": round(p[p < 0].mean(), 2), "total %": round(p.sum(), 1),
                         "h1 win%": round((h1 > 0).mean() * 100), "h1 PF": round(pf(h1), 2),
                         "h2 win%": round((h2 > 0).mean() * 100), "h2 PF": round(pf(h2), 2),
                         "t": round(p.mean() / p.std() * np.sqrt(len(p)), 2)})
    res = pd.DataFrame(rows)
    res.to_csv(Path(argv[2]).resolve().parent / "superbot_winrate.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    ok = res[(res["win%"] >= 70) & (res["PF"] > 1.5) & (res["h1 win%"] >= 70) & (res["h2 win%"] >= 70)
             & (res["h1 PF"] > 1.5) & (res["h2 PF"] > 1.5)]
    print(f"\n{len(res)} exit combinations; {len(ok)} meet win >= 70% and PF > 1.5 in BOTH halves:")
    print(ok.sort_values(["set", "total %"], ascending=[True, False]).to_string(index=False))
    print("\nbest total % per set (any win rate), for comparison:")
    print(res.sort_values("total %", ascending=False).groupby("set").head(3).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv)

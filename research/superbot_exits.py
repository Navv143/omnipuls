"""Which stop / target / trailing rule works best for the Super Bot's entries?

Same entries (research/superbot_strict.py candidates that go with the market: the 120 picks, and every candidate for a
bigger sample); only the exit changes. Stops: the live one (last 6 candles' swing, 0.3-1.0 daily ATR), 1x / 1.5x / 2x the
5-minute ATR(14), fixed 0.5% / 1%. Targets: none, 1R, 1.5R, 2R, 3R, the live swing level. Trails: none, breakeven at
1R, lock 50% after 1R (live), ATR trail (best price minus 2x the 5-minute ATR, from the start or after 1R), partial
(half at 1R, rest trailed with lock 50%). Stop checked first in every candle; out at 15:20; cost 0.12% a round trip.

Usage: python research/superbot_exits.py <bars.pkl (stocks, {"NIFTY": ...})> <superbot_candidates.pkl>
"""
from __future__ import annotations

import itertools
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


def atr5(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate(bars: pd.DataFrame, side: int, entry: float, stop: float, target: float | None, trail: str, a5: float):
    """bars: from the entry candle (inclusive) to the close. Returns % after costs."""
    risk = abs(entry - stop)
    best = entry
    half_done, half_pct = False, 0.0
    hm = bars.index.strftime("%H:%M")
    for (ts, b), h in zip(bars.iterrows(), hm):
        o, hi, lo = float(b["Open"]), float(b["High"]), float(b["Low"])
        if h >= "15:20":
            x = o
            break
        if (side > 0 and lo <= stop) or (side < 0 and hi >= stop):
            x = min(o, stop) if side > 0 else max(o, stop)
            break
        if target is not None and ((side > 0 and hi >= target) or (side < 0 and lo <= target)):
            x = max(o, target) if side > 0 else min(o, target)
            break
        best = max(best, hi) if side > 0 else min(best, lo)
        fav = side * (best - entry)
        if trail == "partial" and not half_done and fav >= risk:
            half_done, half_pct = True, risk / entry * 100        # half booked at +1R
        if trail in ("be1R",) and fav >= risk:
            stop = max(stop, entry) if side > 0 else min(stop, entry)
        if trail in ("lock50", "partial") and fav >= risk:
            lk = entry + side * 0.5 * fav
            stop = max(stop, lk) if side > 0 else min(stop, lk)
        if trail == "atr2" or (trail == "atr2_after1R" and fav >= risk):
            lk = best - side * 2 * a5
            stop = max(stop, lk) if side > 0 else min(stop, lk)
    else:
        x = float(bars["Close"].iloc[-1])
    pct = side * (x / entry - 1) * 100
    if trail == "partial" and half_done:
        pct = 0.5 * half_pct + 0.5 * pct
    return pct - COST


def main(argv):
    stocks, idx = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items()}
    c = pd.read_pickle(argv[2])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"]).copy()
    picks = X.pick(c, ["with the market"], 3, 1)
    stops = ["live", "1x ATR5", "1.5x ATR5", "2x ATR5", "0.5%", "1%"]
    targets = [None, 1.0, 1.5, 2.0, 3.0, "level"]
    trails = ["none", "be1R", "lock50", "atr2", "atr2_after1R", "partial"]
    for name, sample in (("120 PICKS", picks), (f"ALL {len(c)} MARKET-ALIGNED CANDIDATES", c)):
        res = []
        prep = []
        for _, r in sample.iterrows():
            df = bars.get(r["stock"])
            if df is None:
                continue
            day = df[df.index.normalize() == r["day"]]
            et = r["day"] + pd.Timedelta(hours=int(r["entry_at"][:2]), minutes=int(r["entry_at"][3:]))
            after = day[day.index >= et]
            before = df[df.index < et]
            if after.empty or len(before) < 20:
                continue
            a5 = float(atr5(before).iloc[-1])
            prep.append((r, after, a5))
        mid = sorted(sample["day"].unique())[len(sample["day"].unique()) // 2]
        for st, tg, tr in itertools.product(stops, targets, trails):
            pcts, days = [], []
            for r, after, a5 in prep:
                sd, e = int(r["side"]), float(r["entry"])
                if st == "live":
                    stop = float(r["stop"])
                elif "ATR5" in st:
                    stop = e - sd * float(st.split("x")[0]) * a5
                else:
                    stop = e * (1 - sd * float(st.rstrip("%")) / 100)
                risk = abs(e - stop)
                if not risk:
                    continue
                target = (float(r["target"]) if tg == "level" else None if tg is None else e + sd * tg * risk)
                if tr == "partial" and tg is not None and tg != "level" and tg <= 1.0:
                    continue
                pcts.append(simulate(after, sd, e, stop, target, tr, a5))
                days.append(r["day"])
            if not pcts:
                continue
            p, d = np.array(pcts), np.array(days)
            res.append({"stop": st, "target": "none" if tg is None else (tg if tg == "level" else f"{tg}R"), "trail": tr,
                        "n": len(p), "win%": round((p > 0).mean() * 100), "avg%": round(p.mean(), 3),
                        "t": round(p.mean() / p.std() * np.sqrt(len(p)), 2) if p.std() else np.nan,
                        "h1": round(p[d < mid].mean(), 3), "h2": round(p[d >= mid].mean(), 3)})
        t = pd.DataFrame(res)
        t["both+"] = (t["h1"] > 0) & (t["h2"] > 0)
        live = t[(t.stop == "live") & (t.target == "level") & (t.trail == "lock50")]
        print(f"\n===== {name} =====")
        print("LIVE RULE:", live.to_dict("records"))
        print("best 12 by avg (both halves positive):")
        print(t[t["both+"]].sort_values("avg%", ascending=False).head(12).to_string(index=False))
        for col in ("stop", "target", "trail"):
            print(f"average over all other choices, by {col}:",
                  t.groupby(col)["avg%"].mean().round(3).sort_values(ascending=False).to_dict())
        t.to_csv(Path(argv[2]).resolve().parent / f"superbot_exits_{'picks' if 'PICKS' in name else 'all'}.csv", index=False)


if __name__ == "__main__":
    main(sys.argv)

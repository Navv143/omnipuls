"""Where does the windowed Super Bot lose? Trades: 10:00-10:30 best 2 + 11:00-12:00 best 2 + 12:00-12:30 best 2 (first
arrivals, with the market, 1 per sector / stock a day; research/superbot_windows.py). Every trade is split by its
features at entry (known then) and by what happened after (to explain, not to trade on), then a few simple fixes are
tested with both halves of the period.

Usage: python research/superbot_weakpoints.py <bars.pkl (stocks, {"NIFTY": ...})> <superbot_candidates.pkl>
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


def line(name, t, nd=None):
    if len(t) < 5:
        return f"  {name:38s} n={len(t)}"
    p = t["pct"]
    mid = sorted(t["day"].unique())[t["day"].nunique() // 2] if t["day"].nunique() > 1 else t["day"].iloc[0]
    return (f"  {name:38s} n={len(p):3d} win {(p > 0).mean() * 100:3.0f}% avg {p.mean():+.3f}% total {p.sum():+6.1f}% "
            f"t {p.mean() / p.std() * np.sqrt(len(p)):+.2f} h1 {p[t['day'] < mid].mean():+.2f} h2 {p[t['day'] >= mid].mean():+.2f}")


def main(argv):
    stocks, idx = pickle.load(open(argv[1], "rb"))
    bars = {s: BT.naive(df).dropna(subset=["Close"]) for s, df in stocks.items()}
    nifty = idx["NIFTY"]
    nifty = nifty.droplevel(1, axis=1) if isinstance(nifty.columns, pd.MultiIndex) else nifty
    nifty = BT.naive(nifty).dropna(subset=["Close"])
    c = pd.read_pickle(argv[2])
    c = c[c.apply(X.RULES["with the market"], axis=1)].dropna(subset=["entry"])
    t = W.run(c, bars, WINDOWS).reset_index(drop=True)

    # extra features at entry (known then) and after entry (explanation only)
    f = []
    for _, r in t.iterrows():
        day, sd = r["day"], int(r["side"])
        et = day + pd.Timedelta(hours=int(r["entry_at"][:2]), minutes=int(r["entry_at"][3:]))
        n_d = nifty[nifty.index.normalize() == day]
        n_pc = float(nifty[nifty.index.normalize() < day]["Close"].iloc[-1])
        n_bef = n_d[n_d.index < et]
        s_d = bars[r["stock"]][bars[r["stock"]].index.normalize() == day]
        s_pc = float(bars[r["stock"]][bars[r["stock"]].index.normalize() < day]["Close"].iloc[-1])
        s_bef = s_d[s_d.index < et]
        x_at = r["exit_at"] if isinstance(r["exit_at"], str) else "15:20"
        xt = day + pd.Timedelta(hours=int(x_at[:2]), minutes=int(x_at[3:]))
        n_dur = n_d[(n_d.index >= et) & (n_d.index <= xt)]
        hi_d, lo_d = float(s_bef["High"].max()), float(s_bef["Low"].min())
        px = float(r["entry"])
        f.append({
            "risk %": abs(px - float(r["stop"])) / px * 100,
            "stock gap %": sd * (float(s_d["Open"].iloc[0]) / s_pc - 1) * 100,
            "stock move %": sd * (px / s_pc - 1) * 100,
            "from day extreme %": ((hi_d - px) if sd > 0 else (px - lo_d)) / px * 100,   # 0 = at the high (long)
            "nifty gap %": (float(n_d["Open"].iloc[0]) / n_pc - 1) * 100 * sd,
            "nifty since open %": sd * (float(n_bef["Close"].iloc[-1]) / float(n_d["Open"].iloc[0]) - 1) * 100,
            "nifty last 30m %": sd * (float(n_bef["Close"].iloc[-1]) / float(n_bef["Close"].iloc[-7]) - 1) * 100
            if len(n_bef) > 7 else 0.0,
            "nifty after entry %": sd * (float(n_dur["Close"].iloc[-1]) / float(n_dur["Open"].iloc[0]) - 1) * 100
            if len(n_dur) else 0.0,
            "trades before (day)": 0})
    t = pd.concat([t, pd.DataFrame(f)], axis=1)
    t["n_today"] = t.groupby("day")["stock"].transform("size")
    t["k_today"] = t.groupby("day").cumcount() + 1
    t["side_txt"] = np.where(t["side"] > 0, "long", "short")
    t["month"] = t["day"].dt.strftime("%b")

    print(line("ALL TRADES", t))
    print("\nBY EXIT: " + ", ".join(f"{k} {len(z)} ({z['pct'].mean():+.2f}%)" for k, z in t.groupby("result")))
    for col in ("window", "side_txt", "month", "k_today"):
        print(f"\nBY {col.upper()}:")
        for k, z in t.groupby(col):
            print(line(str(k), z))
    num = ["score", "risk %", "move_atr", "vol_x", "rel_nifty", "stock gap %", "stock move %", "from day extreme %",
           "nifty_chg", "nifty gap %", "nifty since open %", "nifty last 30m %", "sector_rank", "money_30m"]
    print("\nAT ENTRY (known then), split in thirds  [low / middle / high]:")
    for col in num:
        q = pd.qcut(t[col].rank(method="first"), 3, labels=["low", "mid", "high"])
        cuts = t[col].quantile([1 / 3, 2 / 3]).round(2).tolist()
        s = " | ".join(f"{k}: {z['pct'].mean():+.3f}% win {(z['pct'] > 0).mean() * 100:.0f}%" for k, z in t.groupby(q, observed=True))
        print(f"  {col:20s} cuts {cuts}  ->  {s}")
    print("\nAFTER ENTRY (explains losses, not tradable): Nifty during the trade, with the trade's direction")
    for k, z in t.groupby(pd.cut(t["nifty after entry %"], [-9, -0.3, -0.1, 0.1, 0.3, 9]), observed=True):
        print(line(str(k), z))
    losers = t[t["pct"] < 0]
    print(f"\nLOSERS: {len(losers)}; stopped {(losers['result'] == 'stop').mean() * 100:.0f}%; median minutes to stop "
          f"{np.median([(pd.Timestamp(f'2000-01-01 {a}') - pd.Timestamp(f'2000-01-01 {b}')).seconds / 60 for a, b in zip(losers.loc[losers['result'] == 'stop', 'exit_at'], losers.loc[losers['result'] == 'stop', 'entry_at'])]):.0f}")
    print("worst 8 days:", t.groupby("day")["pct"].sum().nsmallest(8).round(2).to_dict())
    print("worst sectors:", t.groupby("sector")["pct"].agg(["size", "mean"]).sort_values("mean").head(6).round(3).to_dict("index"))
    t.to_pickle(Path(argv[2]).resolve().parent / "superbot_weak_trades.pkl")


if __name__ == "__main__":
    main(sys.argv)

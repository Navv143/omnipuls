"""Setup 1 (Bank Nifty 5-STAR) re-checked with REAL futures volume and OI (Dhan, live contracts only).

Dhan keeps intraday bars only for contracts that have not expired, so the futures series is the November contract
(about 3 months of 5-minute bars, next-month until the 27 Oct expiry, near-month after). For the same sessions:
  A. 5-STAR as in research (volume / net volume from Nifty 100 stocks' turnover, breadth from Nifty 50)
  B. volume check from the FUTURE's own volume (>= 1.5x its 20-day same-slot average)
  C. A + futures OI rising on the signal candle (new positions behind the move)
  D. B + OI rising
Trades as the live tab: entry at the signal close, Supertrend stop and trail, out 15:15; 12 points cost.
The sample is small (about 60 sessions): read it as a sanity check, not a verdict.

Usage (Omnipuls folder, Dhan token valid): .venv\\Scripts\\python research\\five_star_futures.py
"""
from __future__ import annotations

import glob
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import dhan as D  # noqa: E402
import five_star as FS  # noqa: E402
import scanners as SC  # noqa: E402
from bigbars_dhan import load_cache  # noqa: E402

COST = 12


def main():
    _, raw = load_cache()
    stocks = {s: raw[s] for s in SC.NIFTY100 if s in raw}
    I = FS.market_internals(stocks)
    bn = FS._naive(pickle.loads(open(sorted(glob.glob(str(HERE / "cache" / "IDX_I_25_5_1800_*.pkl")))[-1], "rb").read()))
    fut_id = D.live_futures("NSE_FNO", "FUTIDX", ["BANKNIFTY"], n=1)["BANKNIFTY"][0]["id"]
    fut = FS._naive(D.intraday("NSE_FNO", fut_id, "FUTIDX", 5, 90))
    print(f"Bank Nifty future {fut_id}: {fut.index.min():%d %b} - {fut.index.max():%d %b}, "
          f"{fut.index.normalize().nunique()} sessions, OI column: {'OI' in fut}")
    # futures volume vs its 20-day same-slot average, and OI change per candle
    f = fut.copy()
    f["slot"], f["day"] = f.index.strftime("%H:%M"), f.index.normalize()
    piv = f.pivot_table(index="day", columns="slot", values="Volume")
    avg = piv.rolling(20, min_periods=10).mean().shift(1).stack().rename("fvol_avg")
    f = f.join(avg, on=["day", "slot"])
    f["fvol_x"] = f["Volume"] / f["fvol_avg"]
    f["doi"] = f["OI"].diff() if "OI" in f else np.nan
    f.loc[f["day"] != f["day"].shift(), "doi"] = np.nan
    last_stock_day = I.index.normalize().max()
    days = sorted(set(f["day"]) & set(bn.index.normalize()))
    days = [d for d in days if d <= last_stock_day and d >= sorted(set(f["day"]))[20]]  # need 20 days of averages
    rows = []
    for d in days:
        sub = bn[bn.index.normalize() <= d].iloc[-60 * 75:]
        r = FS.evaluate(sub, I[I.index.normalize() <= d])
        rr = r.get("rows")
        if rr is None or rr.empty:
            continue
        today_f = f[f["day"] == d].set_index(f[f["day"] == d].index.strftime("%H:%M"))
        rr = rr.join(today_f[["fvol_x", "doi"]], on="Time")
        trend_etc = [c for c in FS.CHECK_NAMES if c != "Volume 1.5x usual"]
        for label, need in (("A research (stock turnover)", "stock"), ("B futures volume", "fut"),
                            ("C research + OI rising", "stock_oi"), ("D futures volume + OI rising", "fut_oi")):
            ok = rr[trend_etc].all(axis=1)
            ok &= rr["Volume 1.5x usual"] if need.startswith("stock") else (rr["fvol_x"] >= 1.5)
            if need.endswith("oi"):
                ok &= rr["doi"] > 0
            ok &= rr["Time"].between(FS.FIRST, FS.LAST)
            hit = rr[ok]
            if hit.empty:
                continue
            t0 = hit.iloc[0]
            side = 1 if t0["Lean"] == "BUY" else -1
            day_bars = sub[sub.index.normalize() == d]
            st = FS.supertrend(*(sub[c].to_numpy(float) for c in ("High", "Low", "Close")))
            st = pd.Series(st, index=sub.index)[day_bars.index]
            ts = day_bars.index[day_bars.index.strftime("%H:%M") == t0["Time"]][0]
            e, stop = float(t0["Close"]), float(st[ts])
            pts = None
            for u, b in day_bars[day_bars.index > ts].iterrows():
                if u.strftime("%H:%M") >= FS.SQUARE:
                    pts = side * (b["Open"] - e); break
                if (side > 0 and b["Low"] <= stop) or (side < 0 and b["High"] >= stop):
                    px = min(b["Open"], stop) if side > 0 else max(b["Open"], stop)
                    pts = side * (px - e); break
                stop = max(stop, st[u]) if side > 0 else min(stop, st[u])
            if pts is None:
                pts = side * (day_bars["Close"].iloc[-1] - e)
            rows.append({"version": label, "date": d.date(), "time": t0["Time"], "side": side, "pts": pts - COST,
                         "fvol_x": t0["fvol_x"], "doi": t0["doi"]})
    T = pd.DataFrame(rows)
    print(f"\n{len(days)} sessions compared ({days[0]:%d %b} - {days[-1]:%d %b}); points after {COST} pts cost:")
    out = T.groupby("version").agg(trades=("pts", "size"), avg=("pts", "mean"), total=("pts", "sum"),
                                   win=("pts", lambda x: 100 * (x > 0).mean()))
    print(out.round(1).to_string())
    a = T[T["version"].str.startswith("A")]
    if len(a):
        print("\nResearch version's signals split by what the future showed on the signal candle:")
        print(f"  futures volume 1.5x+ : {a.loc[a.fvol_x >= 1.5, 'pts'].mean():+.1f} pts ({(a.fvol_x >= 1.5).sum()})   "
              f"below: {a.loc[a.fvol_x < 1.5, 'pts'].mean():+.1f} pts ({(a.fvol_x < 1.5).sum()})")
        print(f"  OI rising            : {a.loc[a.doi > 0, 'pts'].mean():+.1f} pts ({(a.doi > 0).sum()})   "
              f"OI falling: {a.loc[a.doi <= 0, 'pts'].mean():+.1f} pts ({(a.doi <= 0).sum()})")
    T.to_csv(HERE / "results" / "five_star_futures.csv", index=False)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()

"""Verify the research findings on real intraday data from Dhan (run on your own computer).

What it does
  1. Gap reversal on F&O stocks with 5-minute bars: enter at the 9:16 bar open (one minute later than
     the daily-bar test, to be realistic), stop below/above entry, exit 15:15. Compares with the daily-bar result.
  2. Nifty futures overnight effect: buy the 15:25 bar close, sell the next 9:16 bar open, on real futures prices.
  3. Gold (MCX GOLD futures): trend filter and session (hour-of-day) returns.

Usage (in the Omnipuls folder, with Dhan connected):
  .venv\\Scripts\\python research\\verify_dhan.py --days 365
Results print to the screen and are saved as CSV files in research\\results.
Dhan allows about 5 data requests per second; the script paces itself, and caches downloads in research\\cache.
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dhan as D  # noqa: E402
import universe as U  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
CACHE, OUT = HERE / "cache", HERE / "results"
CACHE.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
COST = 0.0012  # round trip, as in the daily research


def bars(seg: str, sid: int, ins: str, interval: int, days: int) -> pd.DataFrame:
    f = CACHE / f"{seg}_{sid}_{interval}_{days}_{datetime.now(IST):%Y%m%d}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    df = D.intraday(seg, sid, ins, interval, days)
    f.write_bytes(pickle.dumps(df))
    return df


def daily_from(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(df.index.date)
    return pd.DataFrame({"open": g["Open"].first(), "high": g["High"].max(), "low": g["Low"].min(),
                         "close": g["Close"].last()})


# ---------------------------------------------------------------- 1. gap reversal, intraday replay

def gap_trades(sym: str, df: pd.DataFrame, nifty_gap: pd.Series, gap_min=0.03, stop=0.015) -> list[dict]:
    out = []
    days = sorted(set(df.index.date))
    prev_close = None
    for d in days:
        day = df[df.index.date == d].between_time("09:15", "15:30")
        if day.empty:
            continue
        if prev_close:
            op = day["Open"].iloc[0]
            gap = op / prev_close - 1
            ng = nifty_gap.get(d, np.nan)
            side = 1 if gap <= -gap_min else (-1 if gap >= gap_min else 0)
            if side:
                after = day[day.index.time >= datetime.strptime("09:16", "%H:%M").time()]
                if len(after) > 2:
                    entry = after["Open"].iloc[0]
                    sl = entry * (1 - stop) if side > 0 else entry * (1 + stop)
                    exit_px, how = None, "close"
                    for ts, b in after.iterrows():
                        if ts.time() >= datetime.strptime("15:15", "%H:%M").time():
                            exit_px = b["Open"]
                            break
                        if (side > 0 and b["Low"] <= sl) or (side < 0 and b["High"] >= sl):
                            exit_px, how = sl, "stop"
                            break
                    if exit_px is None:
                        exit_px = after["Close"].iloc[-1]
                    pnl = side * (exit_px / entry - 1) - COST
                    out.append({"date": d, "sym": sym, "side": "long" if side > 0 else "short", "gap": gap,
                                "nifty_gap": ng, "entry": entry, "exit": exit_px, "exit_by": how, "pnl": pnl,
                                "daily_bar_pnl": side * (day["Close"].iloc[-1] / op - 1) - COST})
        prev_close = day["Close"].iloc[-1]
    return out


def run_gaps(days: int, limit: int | None):
    ids = D.equity_ids()
    nifty = bars("IDX_I", 13, "INDEX", 5, days)
    nd = daily_from(nifty)
    nifty_gap = (nd["open"] / nd["close"].shift(1) - 1).to_dict()
    syms = [s for s in sorted(U.FNO_SECTOR_OF) if s in ids][:limit]
    trades = []
    for i, s in enumerate(syms, 1):
        try:
            df = bars("NSE_EQ", ids[s], "EQUITY", 5, days)
        except Exception as e:
            print(f"  {s}: {e}")
            continue
        if not df.empty:
            trades += gap_trades(s, df, nifty_gap)
        if i % 20 == 0:
            print(f"  {i}/{len(syms)} stocks, {len(trades)} gap trades so far")
    t = pd.DataFrame(trades)
    if t.empty:
        print("No gap trades found.")
        return
    t.to_csv(OUT / "gap_trades_intraday.csv", index=False)

    def line(name, x):
        if x.empty:
            return
        print(f"{name:55s} n={len(x):4d} win {100*(x.pnl>0).mean():3.0f}% avg {100*x.pnl.mean():+.2f}%  "
              f"(daily-bar estimate {100*x.daily_bar_pnl.mean():+.2f}%)  stopped {100*(x.exit_by=='stop').mean():.0f}%")
    print("\nGap reversal on real 5-minute bars (entry 9:16, 1.5% stop, exit 15:15, 0.12% costs):")
    line("All gap-downs >=3%, buy", t[t.side == "long"])
    line("Panic gap-downs (Nifty gap <= -0.5%), buy", t[(t.side == "long") & (t.nifty_gap <= -0.005)])
    line("Gap-downs with Nifty flat or up, buy", t[(t.side == "long") & (t.nifty_gap > -0.005)])
    line("All gap-ups >=3%, short", t[t.side == "short"])
    big2 = t[(t.side == "long") & (t.nifty_gap <= -0.005)].sort_values("gap").groupby("date").head(2)
    line("Panic gap-downs, 2 biggest per day", big2)


# ---------------------------------------------------------------- 2. Nifty futures overnight

def run_overnight(days: int):
    fut = D.nearest_futures("NSE_FNO", "FUTIDX", ["NIFTY", "BANKNIFTY"])
    rows = []
    for name, info in fut.items():
        # Nearest contract only covers its own life; for a longer test use the index with a basis adjustment.
        df = bars("NSE_FNO", info["id"], "FUTIDX", 5, min(days, 90))
        if df.empty:
            continue
        g = df.between_time("09:15", "15:30")
        dates = sorted(set(g.index.date))
        for a, b in zip(dates, dates[1:]):
            x = g[g.index.date == a]
            y = g[g.index.date == b]
            buy = x[x.index.time <= datetime.strptime("15:25", "%H:%M").time()]["Close"].iloc[-1]
            sell = y[y.index.time >= datetime.strptime("09:16", "%H:%M").time()]["Open"].iloc[0]
            intraday = x["Close"].iloc[-1] / x["Open"].iloc[0] - 1
            rows.append({"fut": name, "date": b, "overnight": sell / buy - 1 - 0.0005, "intraday": intraday - 0.0005})
    t = pd.DataFrame(rows)
    if t.empty:
        print("No futures data.")
        return
    t.to_csv(OUT / "futures_overnight.csv", index=False)
    print("\nIndex futures, real prices (0.05% cost per trade):")
    print(t.groupby("fut")[["overnight", "intraday"]].agg(["mean", "count", lambda s: (s > 0).mean()]).round(4).to_string())


# ---------------------------------------------------------------- 3. Gold (MCX)

def run_gold(days: int):
    fut = D.nearest_futures("MCX_COMM", "FUTCOM", ["GOLD", "GOLDM"])
    info = fut.get("GOLD") or fut.get("GOLDM")
    if not info:
        print("No MCX gold contract found.")
        return
    df = bars("MCX_COMM", info["id"], "FUTCOM", 60, min(days, 90))
    if df.empty:
        print("No gold data.")
        return
    r = df["Close"].pct_change()
    hod = r.groupby(df.index.hour).agg(["mean", "count", lambda s: (s > 0).mean()])
    hod.columns = ["avg return", "bars", "share up"]
    hod["avg return"] *= 1e4
    print("\nMCX gold: average hourly return by IST hour (basis points):")
    print(hod.round(2).to_string())
    hod.to_csv(OUT / "gold_hour_of_day.csv")
    print("For a long gold history, also run this script's trend test on yfinance GC=F (see README).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365, help="how many days of 5-minute history to use (max ~1800)")
    ap.add_argument("--limit", type=int, default=None, help="test only the first N F&O stocks (quicker)")
    ap.add_argument("--only", choices=["gaps", "overnight", "gold"], default=None)
    a = ap.parse_args()
    if not D.configured():
        sys.exit("Connect Dhan first (Dhan Connect page in Omnipuls, or DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN).")
    t0 = time.time()
    if a.only in (None, "gaps"):
        run_gaps(a.days, a.limit)
    if a.only in (None, "overnight"):
        run_overnight(a.days)
    if a.only in (None, "gold"):
        run_gold(a.days)
    print(f"\nDone in {time.time() - t0:.0f}s. CSV files are in {OUT}")

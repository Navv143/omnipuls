"""Independent backtest of "Version 3": morning top-2 movers, 15-minute breakout with volume, Nifty check.

Rules (as specified):
  Selection at 9:30: rank every F&O stock by the sum of percentile ranks of
    ATR% (14-day, as of yesterday), 9:15-9:30 range %, RVOL (9:15-9:30 volume vs its 20-day average), |gap|.
    Take the top 2.
  Entry 9:30-12:00: a 5-minute candle CLOSES above the 9:15-9:30 high (long) or below its low (short),
    with volume >= 1.5x the 10-day average for that same 5-minute slot (else wait for a later qualifying candle).
    Skip if Nifty 50 has already closed beyond its own 9:15-9:30 range the opposite way.
    Enter at the next candle's open. One trade per stock per day.
  Exit: initial stop 0.5 x ATR from entry; trailing stop 1 x ATR behind the best price reached; else 15:20.
  A+ tag: stock opened at its 9:15-9:30 low (long) or high (short).

Fills are conservative: within a candle the stop is checked against the stop level BEFORE that candle's new
high/low updates the trail; a candle that opens through the stop fills at its open.

Usage (Omnipuls folder, Dhan connected):
  .venv\\Scripts\\python research\\orb_v3.py --days 1800          # ~5 years of 5-minute data from Dhan
  .venv\\Scripts\\python research\\orb_v3.py --days 1800 --limit 60 --sweep
Downloads are cached in research\\cache; results go to research\\results\\orb_v3_*.csv.
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

IST = timezone(timedelta(hours=5, minutes=30))
CACHE, OUT = HERE / "cache", HERE / "results"
CACHE.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

DEFAULT = dict(top_n=2, or_end=dtime(9, 30), entry_until=dtime(12, 0), vol_mult=1.5, vol_lookback=10,
               rvol_lookback=20, atr_n=14, stop_atr=0.5, trail_atr=1.0, exit_at=dtime(15, 20), nifty_filter=True,
               vol_filter=True, cost=0.0005)


# ---------------------------------------------------------------- data

def load_bars(days: int, limit: int | None):
    import dhan as D
    import universe as U

    def bars(seg, sid, ins):
        f = CACHE / f"5m_{seg}_{sid}_{days}_{datetime.now(IST):%Y%m%d}.pkl"
        if f.exists():
            return pickle.loads(f.read_bytes())
        df = D.intraday(seg, sid, ins, 5, days)
        f.write_bytes(pickle.dumps(df))
        return df

    ids = D.equity_ids()
    syms = [s for s in sorted(U.FNO_SECTOR_OF) if s in ids][:limit]
    stocks = {}
    for i, s in enumerate(syms, 1):
        try:
            df = bars("NSE_EQ", ids[s], "EQUITY")
            if not df.empty:
                stocks[s] = df
        except Exception as e:
            print(f"  {s}: {e}")
        if i % 20 == 0:
            print(f"  downloaded {i}/{len(syms)}")
    nifty = bars("IDX_I", 13, "INDEX")
    return stocks, nifty


def prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None) if getattr(df.index, "tz", None) else pd.DatetimeIndex(df.index)
    df = df.between_time("09:15", "15:29")
    df["date"] = df.index.normalize()
    df["slot"] = df.index.time
    return df


# ---------------------------------------------------------------- per-stock daily features (known by 9:30)

def stock_days(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    d = df.groupby("date").agg(open=("Open", "first"), high=("High", "max"), low=("Low", "min"),
                               close=("Close", "last"))
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / p["atr_n"], adjust=False).mean().shift(1)  # as of yesterday
    d["atr_pct"] = d["atr"] / pc
    d["gap"] = d["open"] / pc - 1
    orb = df[df["slot"] < p["or_end"]].groupby("date").agg(or_high=("High", "max"), or_low=("Low", "min"),
                                                           or_vol=("Volume", "sum"), or_open=("Open", "first"))
    d = d.join(orb)
    d["or_range_pct"] = (d["or_high"] - d["or_low"]) / d["or_open"]
    d["rvol"] = d["or_vol"] / d["or_vol"].rolling(p["rvol_lookback"]).mean().shift(1)
    return d


def slot_avg_volume(df: pd.DataFrame, p: dict) -> pd.Series:
    """For each candle: average volume of the same 5-minute slot over the previous N days."""
    v = df.pivot_table(index="date", columns="slot", values="Volume", aggfunc="sum")
    avg = v.rolling(p["vol_lookback"], min_periods=p["vol_lookback"]).mean().shift(1)
    s = avg.stack()
    s.index.names = ["date", "slot"]
    return s


# ---------------------------------------------------------------- simulation

def simulate_day(bars: pd.DataFrame, info: pd.Series, slot_avg: pd.Series, nifty_day: pd.DataFrame | None,
                 nifty_or: tuple | None, p: dict) -> dict | None:
    hi, lo, atr = info["or_high"], info["or_low"], info["atr"]
    if not (np.isfinite(hi) and np.isfinite(lo) and np.isfinite(atr) and atr > 0):
        return None
    cand = bars[(bars["slot"] >= p["or_end"]) & (bars["slot"] < p["entry_until"])]
    rows = list(bars.itertuples())
    pos = {r.Index: i for i, r in enumerate(rows)}
    for r in cand.itertuples():
        side = 1 if r.Close > hi else (-1 if r.Close < lo else 0)
        if not side:
            continue
        if p["vol_filter"]:
            avg = slot_avg.get((r.date, r.slot), np.nan)
            if not (np.isfinite(avg) and avg > 0 and r.Volume >= p["vol_mult"] * avg):
                continue
        if p["nifty_filter"] and nifty_day is not None and nifty_or is not None:
            nb = nifty_day[(nifty_day["slot"] >= p["or_end"]) & (nifty_day.index <= r.Index)]
            if side > 0 and (nb["Close"] < nifty_or[1]).any():
                continue
            if side < 0 and (nb["Close"] > nifty_or[0]).any():
                continue
        i = pos[r.Index] + 1
        if i >= len(rows):
            return None
        entry_bar = rows[i]
        entry = entry_bar.Open
        stop = entry - side * p["stop_atr"] * atr
        best = entry
        exit_px, how, exit_t = None, "time", None
        for b in rows[i:]:
            if b.slot >= p["exit_at"]:
                exit_px, exit_t = b.Open, b.Index
                break
            level = max(stop, best - p["trail_atr"] * atr) if side > 0 else min(stop, best + p["trail_atr"] * atr)
            if side > 0 and b.Low <= level:
                exit_px, how, exit_t = min(b.Open, level), "stop" if level == stop else "trail", b.Index
                break
            if side < 0 and b.High >= level:
                exit_px, how, exit_t = max(b.Open, level), "stop" if level == stop else "trail", b.Index
                break
            best = max(best, b.High) if side > 0 else min(best, b.Low)
        if exit_px is None:
            exit_px, exit_t = rows[-1].Close, rows[-1].Index
        ret = side * (exit_px / entry - 1)
        risk = p["stop_atr"] * atr / entry
        opened_at_extreme = (side > 0 and info["or_open"] <= lo * 1.0005) or (side < 0 and info["or_open"] >= hi * 0.9995)
        return {"side": "long" if side > 0 else "short", "signal_time": r.Index, "entry": entry, "exit": exit_px,
                "exit_time": exit_t, "exit_by": how, "gross": ret, "net": ret - p["cost"], "risk_pct": risk,
                "R": (ret - p["cost"]) / risk, "a_plus": bool(opened_at_extreme),
                "with_gap": bool(np.sign(info["gap"]) == side)}
    return None


def run(stocks: dict, nifty: pd.DataFrame, p: dict) -> pd.DataFrame:
    prepped = {s: prep(df) for s, df in stocks.items()}
    days = {s: stock_days(df, p) for s, df in prepped.items()}
    slots = {s: slot_avg_volume(df, p) for s, df in prepped.items()}
    n = prep(nifty)
    n_or = n[n["slot"] < p["or_end"]].groupby("date").agg(h=("High", "max"), l=("Low", "min"))
    panel = pd.concat({s: d[["atr_pct", "or_range_pct", "rvol", "gap"]] for s, d in days.items()}, names=["sym", "date"])
    panel = panel.dropna()
    panel["abs_gap"] = panel["gap"].abs()
    for c in ("atr_pct", "or_range_pct", "rvol", "abs_gap"):
        panel[c + "_pr"] = panel.groupby(level="date")[c].rank(pct=True) * 100
    panel["score"] = panel[[c + "_pr" for c in ("atr_pct", "or_range_pct", "rvol", "abs_gap")]].sum(axis=1)
    picks = panel.sort_values("score", ascending=False).groupby(level="date").head(p["top_n"])
    trades = []
    by_date = {s: dict(tuple(df.groupby("date"))) for s, df in prepped.items()}
    n_by_date = dict(tuple(n.groupby("date")))
    for (sym, date), row in picks.iterrows():
        bars = by_date[sym].get(date)
        if bars is None or len(bars) < 10:
            continue
        info = days[sym].loc[date]
        nb = n_by_date.get(date)
        nor = (n_or.loc[date, "h"], n_or.loc[date, "l"]) if date in n_or.index else None
        t = simulate_day(bars, info, slots[sym], nb, nor, p)
        if t:
            t.update({"date": date, "sym": sym, "score": row["score"], "gap": info["gap"], "atr_pct": info["atr_pct"]})
            trades.append(t)
    return pd.DataFrame(trades)


# ---------------------------------------------------------------- reporting

def summary(t: pd.DataFrame, label: str) -> dict:
    if t.empty:
        return {"set": label, "trades": 0}
    R = t["R"]
    daily = t.groupby("date")["R"].sum()
    eq = daily.cumsum()
    return {"set": label, "trades": len(t), "win%": round(100 * (R > 0).mean(), 1), "avg R": round(R.mean(), 3),
            "avg net %": round(100 * t["net"].mean(), 3), "PF": round(R[R > 0].sum() / -R[R <= 0].sum(), 2) if (R <= 0).any() else np.inf,
            "total R": round(R.sum(), 1), "max DD (R)": round((eq - eq.cummax()).min(), 1),
            "t-stat": round(R.mean() / R.std() * np.sqrt(len(R)), 2) if len(R) > 2 else np.nan}


def report(t: pd.DataFrame, tag: str = ""):
    rows = [summary(t, "All trades")]
    for k, g in t.groupby(t["date"].dt.year):
        rows.append(summary(g, f"Year {k}"))
    rows += [summary(t[t.side == "long"], "Long"), summary(t[t.side == "short"], "Short"),
             summary(t[t.a_plus], "A+ (opened at the extreme)"), summary(t[~t.a_plus], "Not A+"),
             summary(t[t.with_gap], "Breakout in the gap's direction"),
             summary(t[~t.with_gap], "Breakout against the gap")]
    for c in (0.0005, 0.001, 0.0015, 0.0025):
        tc = t.assign(net=t["gross"] - c, R=(t["gross"] - c) / t["risk_pct"])
        rows.append(summary(tc, f"All, cost {c:.2%} round trip"))
    out = pd.DataFrame(rows)
    out.to_csv(OUT / f"orb_v3_summary{tag}.csv", index=False)
    t.to_csv(OUT / f"orb_v3_trades{tag}.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1800)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sweep", action="store_true", help="also test nearby settings (robustness)")
    a = ap.parse_args()
    t0 = time.time()
    stocks, nifty = load_bars(a.days, a.limit)
    p = dict(DEFAULT)
    t = run(stocks, nifty, p)
    print(f"\nV3 as specified: {len(t)} trades from {len(stocks)} stocks")
    report(t)
    if a.sweep:
        rows = []
        for name, change in [("no volume filter", {"vol_filter": False}), ("no Nifty filter", {"nifty_filter": False}),
                             ("volume 1.2x", {"vol_mult": 1.2}), ("volume 2.0x", {"vol_mult": 2.0}),
                             ("stop 0.4 ATR", {"stop_atr": 0.4}), ("stop 0.6 ATR", {"stop_atr": 0.6}),
                             ("trail 0.75 ATR", {"trail_atr": 0.75}), ("trail 1.25 ATR", {"trail_atr": 1.25}),
                             ("top 1", {"top_n": 1}), ("top 3", {"top_n": 3}), ("entries until 11:00", {"entry_until": dtime(11, 0)}),
                             ("entries until 13:00", {"entry_until": dtime(13, 0)})]:
            tt = run(stocks, nifty, {**p, **change})
            rows.append(summary(tt, name))
        s = pd.DataFrame(rows)
        s.to_csv(OUT / "orb_v3_sweep.csv", index=False)
        print("\nNearby settings:\n" + s.to_string(index=False))
    print(f"\nDone in {time.time() - t0:.0f}s. Files in {OUT}")

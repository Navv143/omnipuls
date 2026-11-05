"""Noise Area intraday momentum (Zarattini, Aziz & Barbon 2024, "Beat the Market: An Effective Intraday Momentum
Strategy for S&P500 ETF (SPY)"), as in the quant_labde "Noise Band Theory" reel.

- sigma(t): for each time of day, the average of |close(t) / open(day) - 1| over the previous `lookback` sessions.
- Upper band = max(open, previous close) x (1 + vm x sigma(t)); lower = min(open, previous close) x (1 - vm x sigma(t)).
- At each check (candle close at a check time): flat and close above the upper band → long; below the lower → short.
  In a long: close below max(upper band, session VWAP) → exit (and short if below the lower band); mirror for shorts.
- Orders fill at the next candle's open; everything is closed at the session's last candle close. Costs per side.
Returns are unlevered % of the position; a day's return is the sum of its trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sessions(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Keep candles whose local start time is in [start, end); the index must be tz-aware in the market's zone."""
    t = df.index.strftime("%H:%M")
    x = df[(t >= start) & (t < end)].copy()
    x["day"] = x.index.normalize()
    x["tod"] = x.index.strftime("%H:%M")
    return x


def run(x: pd.DataFrame, cost_side: float, lookback=14, vm=1.0, checks=None, use_vwap=True):
    """x: session candles with day / tod columns. checks: set of 'HH:MM' times when signals / stops are checked (None =
    every candle). Returns (trades, daily returns)."""
    x = x.copy()
    first = x.groupby("day")["Open"].transform("first")
    x["move"] = (x["Close"] / first - 1).abs()
    piv = x.pivot_table(index="day", columns="tod", values="move")
    sig = piv.rolling(lookback, min_periods=lookback).mean().shift()          # previous sessions only
    x["sigma"] = [sig.at[d, t] if (d in sig.index and t in sig.columns) else np.nan for d, t in zip(x["day"], x["tod"])]
    closes = x.groupby("day")["Close"].last()
    x["pclose"] = x["day"].map(closes.shift())
    x["ub"] = np.maximum(first, x["pclose"]) * (1 + vm * x["sigma"])
    x["lb"] = np.minimum(first, x["pclose"]) * (1 - vm * x["sigma"])
    tp = (x["High"] + x["Low"] + x["Close"]) / 3
    v = x["Volume"].replace(0, np.nan).fillna(1.0)
    x["vwap"] = (tp * v).groupby(x["day"]).cumsum() / v.groupby(x["day"]).cumsum()
    trades, daily = [], {}
    for d, g in x.groupby("day", sort=True):
        if g["sigma"].isna().all() or not np.isfinite(g["pclose"].iloc[0]):
            continue
        o, c, ub, lb, vw, tod = (g[k].to_numpy() for k in ("Open", "Close", "ub", "lb", "vwap", "tod"))
        pos, entry, day_ret = 0, None, 0.0
        n = len(g)
        for i in range(n - 1):
            if checks is not None and tod[i] not in checks:
                continue
            if not np.isfinite(ub[i]):
                continue
            want = pos
            if pos == 0:
                want = 1 if c[i] > ub[i] else -1 if c[i] < lb[i] else 0
            elif pos > 0:
                stop = max(ub[i], vw[i]) if use_vwap else ub[i]
                if c[i] < stop:
                    want = -1 if c[i] < lb[i] else 0
            else:
                stop = min(lb[i], vw[i]) if use_vwap else lb[i]
                if c[i] > stop:
                    want = 1 if c[i] > ub[i] else 0
            if want != pos:
                px = o[i + 1]
                if pos != 0:
                    r = pos * (px / entry - 1) * 100 - 2 * cost_side
                    trades.append({"day": d, "side": pos, "pct": r})
                    day_ret += r
                pos, entry = want, (px if want != 0 else None)
        if pos != 0:                                         # flat at the session's last close
            r = pos * (c[-1] / entry - 1) * 100 - 2 * cost_side
            trades.append({"day": d, "side": pos, "pct": r})
            day_ret += r
        daily[d] = day_ret
    return pd.DataFrame(trades), pd.Series(daily)


def stats(trades: pd.DataFrame, daily: pd.Series, per_year_days=252) -> dict:
    if trades.empty:
        return {"trades": 0}
    dr = daily / 100
    sharpe = dr.mean() / dr.std() * np.sqrt(per_year_days) if dr.std() > 0 else np.nan
    eq = (1 + dr).cumprod()
    dd = (eq / eq.cummax() - 1).min() * 100
    h = len(daily) // 2
    return {"days": len(daily), "trades": len(trades), "win%": round((trades.pct > 0).mean() * 100),
            "avg%/trade": round(trades.pct.mean(), 3), "total%": round(daily.sum(), 1), "sharpe": round(sharpe, 2),
            "maxDD%": round(dd, 1), "1st half%": round(daily.iloc[:h].sum(), 1), "2nd half%": round(daily.iloc[h:].sum(), 1),
            "years": daily.groupby(daily.index.year).sum().round(1).to_dict()}

"""Approximate P&L of buying a stock option instead of the shares.

- Strike: at the money at entry (K = entry price), call for longs, put for shorts.
- Expiry: NSE stock options are monthly: last Thursday of the month until Aug 2025, last Tuesday from Sep 2025.
  If fewer than 5 trading days remain we use the next month (as traders roll).
- IV: 20-day realized volatility of daily closes x 1.15 (stock option IV usually sits a little above realized),
  floored at 18% a year. IV is held constant intraday (no IV crush/expansion modelled).
- Time decay: time to expiry measured in trading days (252/yr) with the trading day split into 375 minutes.
- Costs: a fraction of premium for the round trip (spread + brokerage + STT + exchange). Default 2%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


def expiries(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Monthly expiry for every month spanned by the trading calendar, snapped to the last trading day on/before."""
    out = []
    tset = pd.DatetimeIndex(days)
    for per in pd.period_range(days.min(), days.max() + pd.offsets.MonthEnd(2), freq="M"):
        last = per.end_time.normalize()
        wd = 3 if last < pd.Timestamp("2025-09-01") else 1  # Thu, then Tue
        e = last - pd.Timedelta(days=(last.weekday() - wd) % 7)
        prior = tset[tset <= e]
        if len(prior) and (e - prior[-1]).days < 7 and e <= tset.max():
            e = prior[-1]
        out.append(e)
    return pd.DatetimeIndex(out)


def dte_table(days: pd.DatetimeIndex, roll=5) -> np.ndarray:
    """Trading days to the expiry used on each day (0 = expiry day itself), rolling when fewer than `roll` remain."""
    ex = expiries(days)
    pos = np.arange(len(days))
    out = np.zeros(len(days))
    for i, d in enumerate(days):
        fut = ex[ex >= d]
        for e in fut:
            n = np.searchsorted(days, e, side="right") - 1 - i if e <= days[-1] else \
                int(np.busday_count(d.date(), e.date()))
            if n >= roll:
                out[i] = n
                break
    return out


def bs(S, K, T, sig, call):
    T = np.maximum(T, 1e-6)
    d1 = (np.log(S / K) + 0.5 * sig ** 2 * T) / (sig * np.sqrt(T))
    d2 = d1 - sig * np.sqrt(T)
    c = S * norm.cdf(d1) - K * norm.cdf(d2)
    return np.where(call, c, c - S + K)


def option_return(entry, exit_px, side, dte, entry_slot, exit_slot, iv, cost=0.02, moneyness=0.0):
    """Return on premium for buying an option. Slots are 5-minute bar indexes from 09:15 (75 per day).
    moneyness: 0 = ATM, +0.01 = 1% in the money."""
    side = np.asarray(side)
    call = side > 0
    K = entry * (1 - side * moneyness)
    mins_left_entry = (75 - np.asarray(entry_slot)) * 5 / 375.0
    mins_left_exit = (75 - np.asarray(exit_slot)) * 5 / 375.0
    T0 = (dte + mins_left_entry) / 252.0
    T1 = (dte + mins_left_exit) / 252.0
    p0 = bs(entry, K, T0, iv, call)
    p1 = bs(exit_px, K, T1, iv, call)
    return p1 / p0 - 1 - cost, p0 / entry

"""Index trend-day + OI alert for option BUYING (Omnipuls research, Nov 2026).

Rule (from Nifty / Bank Nifty futures 1-min data 2015-2023, real volume and OI):
  Between 10:30 and 13:00, the first 5-minute close where
    1. the index is at least THR x daily ATR(14) away from today's open (up = CALL, down = PUT),
    2. the index future is on the same side of its VWAP,
    3. the index future's open interest is ABOVE yesterday's close (new positions are being opened behind the move).
  Buy the ATM weekly option. Stop: premium -30%. Once up 30%+, exit if the premium falls 30% from its best.
  Otherwise exit at 15:15.

What the backtest found (option P&L after 2% costs, Black-Scholes premiums from India VIX):
  - Fixed check times 10:30-12:30, threshold 0.5-0.8 ATR: Bank Nifty profitable in 19 of 20 combinations
    (avg +4.1% of premium per trade); Nifty in 14 of 19 (+1.9%).
  - Without the OI condition the edge halves (Bank Nifty) or disappears (Nifty): OI is the key.
  - 'First time it happens' entries: Bank Nifty +5% to +6.5% only at 1.0 ATR; Nifty +6% to +8% at 0.7 ATR.
  - 10-20 trades a year per index, win rate ~40-47%: profits come from a few big trend days.
  Statistically weak on its own (t ~1-1.7): treat as a paper-trading candidate, size small.
"""
from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd

_ncdf = np.vectorize(lambda x: 0.5 * (1 + erf(x / sqrt(2))))  # standard normal CDF, no scipy needed

DEFAULT_THR = {"NIFTY": 0.7, "BANKNIFTY": 1.0, "FINNIFTY": 0.8, "MIDCPNIFTY": 0.8, "SENSEX": 0.7}
STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25, "SENSEX": 100}
IV_MULT = {"NIFTY": 1.0, "BANKNIFTY": 1.2, "FINNIFTY": 1.1, "MIDCPNIFTY": 1.3, "SENSEX": 1.0}
WINDOW = ("10:30", "13:00")


def _clean(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.between_time("09:15", "15:29")


def _bs(S, K, T, s, call):
    T = max(T, 1e-7)
    s = max(s, 0.05)
    d1 = (np.log(S / K) + 0.5 * s * s * T) / (s * np.sqrt(T))
    d2 = d1 - s * np.sqrt(T)
    c = S * _ncdf(d1) - K * _ncdf(d2)
    return c if call else c - S + K


def evaluate(key: str, spot: pd.DataFrame, fut: pd.DataFrame | None, vix: pd.DataFrame | None = None,
             thr: float | None = None, dte_days: float = 2.0) -> dict:
    """Live state of the rule for one index on its latest session."""
    thr = DEFAULT_THR.get(key, 0.8) if thr is None else thr
    spot = _clean(spot)
    out = {"key": key, "thr": thr, "status": "no data"}
    if spot.empty:
        return out
    day = spot.index.normalize()
    sess = day.max()
    today, hist = spot[day == sess], spot[day < sess]
    g = hist.groupby(hist.index.normalize())
    daily = pd.DataFrame({"h": g["High"].max(), "l": g["Low"].min(), "c": g["Close"].last()})
    if len(daily) < 15 or today.empty:
        out["status"] = "need 15 earlier sessions"
        return out
    pc = daily["c"].shift(1)
    tr = pd.concat([daily["h"] - daily["l"], (daily["h"] - pc).abs(), (daily["l"] - pc).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    o = float(today["Open"].iloc[0])
    t = pd.DataFrame({"close": today["Close"], "move_atr": (today["Close"] - o) / atr})
    t["Time"] = t.index.strftime("%H:%M")
    # futures: VWAP and OI vs yesterday
    t["fut"] = np.nan
    t["vwap"] = np.nan
    t["oi_chg"] = np.nan
    fut = _clean(fut)
    if not fut.empty:
        fd = fut.index.normalize()
        ft, fh = fut[fd == sess], fut[fd < sess]
        if not ft.empty:
            tp = (ft["High"] + ft["Low"] + ft["Close"]) / 3
            vw = (tp * ft["Volume"]).cumsum() / ft["Volume"].cumsum().replace(0, np.nan)
            ft = ft.assign(vwap=vw)
            al = ft.reindex(t.index, method="ffill")
            t["fut"] = al["Close"].values
            t["vwap"] = al["vwap"].values
            if "OI" in ft and not fh.empty and "OI" in fh and fh["OI"].iloc[-1] > 0:
                t["oi_chg"] = (al["OI"] / fh["OI"].iloc[-1] - 1).values * 100
    t["vwap_side"] = np.sign(t["fut"] - t["vwap"])
    up = (t["move_atr"] >= thr) & (t["vwap_side"] > 0) & (t["oi_chg"] > 0)
    dn = (t["move_atr"] <= -thr) & (t["vwap_side"] < 0) & (t["oi_chg"] > 0)
    inwin = (t["Time"] >= WINDOW[0]) & (t["Time"] <= WINDOW[1])
    sig = t[(up | dn) & inwin]
    last = t.iloc[-1]
    out.update(status="watching", session=sess, atr=atr, open=o, last=float(last["close"]), last_time=last["Time"],
               move_atr=float(last["move_atr"]), vwap_side=float(last["vwap_side"]) if pd.notna(last["vwap_side"]) else np.nan,
               oi_chg=float(last["oi_chg"]) if pd.notna(last["oi_chg"]) else np.nan, bars=t)
    checks = {"Move ≥ threshold": abs(out["move_atr"]) >= thr,
              "Future on the same side of VWAP": pd.notna(last["vwap_side"]) and np.sign(out["move_atr"]) == last["vwap_side"],
              "Futures OI above yesterday": pd.notna(last["oi_chg"]) and last["oi_chg"] > 0,
              "Inside 10:30-13:00": bool(inwin.iloc[-1])}
    out["checks"] = checks
    if fut.empty:
        out["status"] = "no futures data (OI and VWAP need Dhan)"
    if sig.empty:
        if last["Time"] > WINDOW[1] and not fut.empty:
            out["status"] = "no signal today"
        return out
    s0 = sig.iloc[0]
    call = bool(s0["move_atr"] > 0)
    K = round(s0["close"] / STEP.get(key, 50)) * STEP.get(key, 50)
    out.update(status="SIGNAL", side="CALL" if call else "PUT", sig_time=s0["Time"], sig_px=float(s0["close"]), strike=K)
    # estimated option P&L and trailing-exit state (Black-Scholes, India VIX)
    iv0 = np.nan
    if vix is not None and not vix.empty:
        v = _clean(vix)
        v = v[v.index.normalize() == sess]["Close"].reindex(t.index, method="ffill")
        t["iv"] = v.values / 100 * IV_MULT.get(key, 1.0)
        iv0 = t.loc[sig.index[0], "iv"]
    if pd.isna(iv0):
        t["iv"] = 0.15 * IV_MULT.get(key, 1.0)
        iv0 = t["iv"].iloc[0]
    def T_at(ts):
        mins_left = max((15 * 60 + 30) - (ts.hour * 60 + ts.minute + 5), 0)
        return (dte_days + mins_left / 375) / 252
    i0 = t.index.get_loc(sig.index[0])
    p0 = _bs(s0["close"], K, T_at(sig.index[0]), iv0, call)
    peak, exit_at, state = 0.0, None, "open"
    path = []
    for ts, r in t.iloc[i0 + 1:].iterrows():
        val = _bs(r["close"], K, T_at(ts), r["iv"] if pd.notna(r["iv"]) else iv0, call) / p0 - 1
        peak = max(peak, val)
        path.append((r["Time"], val))
        if exit_at is None:
            if val <= -0.30 and peak < 0.30:
                exit_at, state = (r["Time"], val), "stopped (-30%)"
            elif peak >= 0.30 and val <= (1 + peak) * 0.70 - 1:
                exit_at, state = (r["Time"], val), f"trailed out (best {peak * 100:+.0f}%)"
            elif r["Time"] >= "15:15":
                exit_at, state = (r["Time"], val), "closed 15:15"
    cur = path[-1][1] if path else 0.0
    out.update(prem0=p0, opt_now=cur, opt_peak=peak, trade_state=state, exit=exit_at, opt_path=path,
               idx_move=float(last["close"] - s0["close"]) * (1 if call else -1))
    return out


def days_to_expiry(key: str, today) -> float:
    """Trading days to the nearest expiry (0 on expiry day). NSE: Nifty weekly Tuesday; Bank Nifty, Fin Nifty and
    Midcap Select monthly (last Tuesday). BSE: Sensex weekly Thursday. Holidays ignored."""
    today = pd.Timestamp(today).normalize()
    if key in ("NIFTY", "SENSEX"):
        wd = 1 if key == "NIFTY" else 3
        e = today + pd.Timedelta(days=(wd - today.weekday()) % 7)
    else:
        def last_tue(ts):
            m = ts + pd.offsets.MonthEnd(0)
            return m - pd.Timedelta(days=(m.weekday() - 1) % 7)
        e = last_tue(today)
        if e < today:
            e = last_tue(today + pd.offsets.MonthBegin(1))
    return float(np.busday_count(today.date(), e.date()))

"""BTC NY-session trend pullback: the best lead of research/SNIPER_STUDY.md, paper-traded live (not proven yet).

Rules (exactly as tested, Binance 5-minute candles 2023-2026: +0.09R a trade, 36% wins, t 1.3):
- Trend: the last finished 1-hour candle closes above its 50-hour EMA and the 20-hour EMA is rising (long), or the
  mirror (short). No trend, no trade.
- Window 13:30-18:00 London time (≈ 19:00-23:30 IST; New York morning). Session VWAP from London midnight.
- Dip: a 5-minute candle trades through VWAP and closes back on the trend side (within 0.2%).
- Trigger: a later 5-minute candle closes beyond the previous candle's high (long) / low (short).
- Entry at the next candle's open; stop beyond the last 6 candles' low (high); the stop must be 0.3-0.8% away, else
  wait for the next dip. Target 3R. Exit at 21:00 London if neither is hit. One trade a day.
Candles: Crypto.com BTC_USDT. Paper only.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LDN = ZoneInfo("Europe/London")
WIN_START, WIN_END, EXIT_AT = 13 * 60 + 30, 18 * 60, 21 * 60
RR, MIN_STOP, MAX_STOP, SWING = 3.0, 0.3, 0.8, 6
COST_PCT = 0.05
NAME = "BTC NY trend pullback"


def _hm(t: pd.Timestamp) -> int:
    return t.hour * 60 + t.minute


def trend_series(h1: pd.DataFrame) -> pd.Series:
    """+1 / -1 / 0 per finished hour (index = the hour's open time, UTC naive)."""
    c = h1["Close"]
    e50, e20 = c.ewm(span=50).mean(), c.ewm(span=20).mean()
    return pd.Series(np.where((c > e50) & (e20 > e20.shift(3)), 1, np.where((c < e50) & (e20 < e20.shift(3)), -1, 0)),
                     index=h1.index)


def evaluate(m5: pd.DataFrame, h1: pd.DataFrame, now_utc: pd.Timestamp | None = None) -> dict:
    """Today's (London day) state of the setup: trend, VWAP, the step it is on, and the trade with its result so far.
    m5 / h1: Crypto.com candles, UTC naive index, oldest first. The last 5-min candle is dropped if not finished."""
    now_utc = now_utc or pd.Timestamp.utcnow().tz_localize(None)
    m5 = m5[m5.index + pd.Timedelta(minutes=5) <= now_utc]          # finished candles only
    h1 = h1[h1.index + pd.Timedelta(hours=1) <= now_utc]
    if m5.empty or len(h1) < 60:
        return {"state": "no data"}
    loc = m5.index.tz_localize("UTC").tz_convert(LDN)
    day = loc[-1].normalize()
    x = m5[loc.normalize() == day].copy()
    lt = loc[loc.normalize() == day]
    if x.empty:
        return {"state": "no data"}
    x["hm"] = [t.hour * 60 + t.minute for t in lt]
    tp = (x["High"] + x["Low"] + x["Close"]) / 3
    v = x["Volume"].replace(0, np.nan).fillna(1e-9)
    x["vwap"] = (tp * v).cumsum() / v.cumsum()
    tr = trend_series(h1)
    # trend known at a 5-min candle = the last hour finished before that candle started
    x["trend"] = [int(tr[tr.index + pd.Timedelta(hours=1) <= t].iloc[-1]) if (tr.index + pd.Timedelta(hours=1) <= t).any()
                  else 0 for t in x.index]
    o, h, l, c, hm, vw, td = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close", "hm", "vwap", "trend"))
    out = {"day": day.strftime("%Y-%m-%d"), "price": float(c[-1]), "vwap": float(vw[-1]), "trend": int(td[-1]),
           "as_of": (lt[-1] + pd.Timedelta(minutes=5)).strftime("%H:%M"), "as_of_ist": (lt[-1] + pd.Timedelta(minutes=5))
           .tz_convert("Asia/Kolkata").strftime("%H:%M")}
    w = np.where((hm >= WIN_START) & (hm < WIN_END))[0]
    if hm[-1] < WIN_START:
        out["state"] = "before the window (13:30 London)"
        return out
    touched, sig = 0, None
    for k in w[1:]:
        if k + 1 >= len(x):   # the entry candle has not opened yet
            break
        sd = int(td[k])
        if not sd:
            continue
        if (sd > 0 and l[k] <= vw[k] and c[k] > vw[k] * 0.998) or (sd < 0 and h[k] >= vw[k] and c[k] < vw[k] * 1.002):
            touched = sd
            continue
        if touched == sd and ((sd > 0 and c[k] > h[k - 1]) or (sd < 0 and c[k] < l[k - 1])):
            e = float(o[k + 1])
            lo_, hi_ = float(l[max(0, k - SWING + 1):k + 1].min()), float(h[max(0, k - SWING + 1):k + 1].max())
            stop = lo_ if sd > 0 else hi_
            sp = abs(e - stop) / e * 100
            if not (MIN_STOP <= sp <= MAX_STOP) or sd * (e - stop) <= 0:
                touched = 0
                continue
            sig = {"side": sd, "signal_at": (lt[k] + pd.Timedelta(minutes=5)).strftime("%H:%M"),
                   "entry_at": lt[k + 1].strftime("%H:%M"), "entry_at_ist": lt[k + 1].tz_convert("Asia/Kolkata").strftime("%H:%M"),
                   "entry": round(e, 2), "sl": round(stop, 2), "tp": round(e + sd * RR * abs(e - stop), 2),
                   "stop_pct": round(sp, 3), "i": int(k + 1)}
            break
    if not sig:
        out["state"] = ("window closed: no trade today" if hm[-1] >= WIN_END else
                        "no trend: no trade" if not td[-1] else
                        f"waiting for a dip to VWAP ({'trend up' if td[-1] > 0 else 'trend down'})" if touched != td[-1] else
                        "dip done: waiting for the trigger candle")
        return out
    # result so far: stop / target / 21:00
    sd, e, stop, tp = sig["side"], sig["entry"], sig["sl"], sig["tp"]
    res, ex_at, ex_px = "open", None, None
    for j in range(sig["i"], len(x)):
        if hm[j] >= EXIT_AT:
            res, ex_at, ex_px = "time", lt[j].strftime("%H:%M"), float(o[j])
            break
        if (sd > 0 and l[j] <= stop) or (sd < 0 and h[j] >= stop):
            res, ex_at, ex_px = "stop", (lt[j] + pd.Timedelta(minutes=5)).strftime("%H:%M"), stop
            break
        if (sd > 0 and h[j] >= tp) or (sd < 0 and l[j] <= tp):
            res, ex_at, ex_px = "target", (lt[j] + pd.Timedelta(minutes=5)).strftime("%H:%M"), tp
            break
    risk = abs(e - stop)
    px = ex_px if ex_px is not None else float(c[-1])
    r = (sd * (px - e) - (e * COST_PCT / 100 if ex_px is not None else 0)) / risk
    sig.pop("i")
    out.update(state="in trade" if res == "open" else f"closed ({res})", signal=sig, result=res, exit_at=ex_at,
               exit_px=ex_px, r=round(r, 2), pct=round(sd * (px / e - 1) * 100, 3))
    return out

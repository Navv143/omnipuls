"""Bank Nifty Engulfing Bar Play on 1-hour candles, held overnight (paper). From research/ebp_study.py.

Rules (tested Nov 2023 - Nov 2026 on 1h candles, realistic gap fills, 0.02% costs: +0.40R a trade, positive in
every third of the period, +0.27R at double costs; ~1 trade a week; worst trade -12.7R on an overnight gap):
- EBP: bearish = the hour sweeps above the previous hour's high and closes below the previous hour's open, and the
  previous hour was up (bullish = the mirror).
- Entry: a limit at the EBP candle's 50%, valid for the next 3 hours.
- Stop: the EBP candle's high (low). A gap through the stop fills at the open.
- Target: the draw on liquidity = the lowest low (highest high) of the 20 hours before the EBP, at least 1R away.
- Exit after 14 trading hours (~2 days) if neither is hit. Held overnight.
Hourly candles: 9:15, 10:15, ..., 15:15 (the last one 15 minutes), built from the 5-minute candles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "Bank Nifty EBP 1h (overnight)"
DOL_N, WAIT, HOLD, MIN_RR, COST = 20, 3, 14, 1.0, 0.02


def hourly(m5: pd.DataFrame) -> pd.DataFrame:
    """1-hour candles from 9:15 (IST, tz-naive 5-min index), as on Yahoo / most brokers."""
    x = m5[~m5.index.duplicated(keep="last")].sort_index()
    x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:29")]
    mins = (x.index.hour * 60 + x.index.minute) - (9 * 60 + 15)
    start = x.index.normalize() + pd.to_timedelta(9 * 60 + 15 + (mins // 60) * 60, unit="m")
    g = x.groupby(start)
    return pd.DataFrame({"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
                         "Close": g["Close"].last()})


def trades(h1: pd.DataFrame, since: pd.Timestamp | None = None, last_complete: bool = True) -> list:
    """Every EBP trade (signal after `since`) with its state: waiting for the limit, open, or closed."""
    x = h1.copy()
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(x)
    out, busy = [], -1
    for k in range(DOL_N + 1, n):
        if k <= busy or (since is not None and x.index[k] < since):
            continue
        bull = l[k] < l[k - 1] and c[k] > o[k - 1] and c[k] > o[k] and c[k - 1] < o[k - 1]
        bear = h[k] > h[k - 1] and c[k] < o[k - 1] and c[k] < o[k] and c[k - 1] > o[k - 1]
        if not (bull or bear):
            continue
        s = 1 if bull else -1
        stop = l[k] if s > 0 else h[k]
        lvl = (h[k] + l[k]) / 2
        tg = h[k - DOL_N:k].max() if s > 0 else l[k - DOL_N:k].min()
        base = {"signal_at": x.index[k], "side": s, "limit": round(lvl, 2), "sl": round(stop, 2), "tp": round(tg, 2)}
        if s * (tg - lvl) < MIN_RR * s * (lvl - stop):
            continue
        i = None
        for j in range(k + 1, min(k + 1 + WAIT, n)):
            if (s > 0 and l[j] <= lvl) or (s < 0 and h[j] >= lvl):
                i, e = j, (min(o[j], lvl) if s > 0 else max(o[j], lvl))
                break
        if i is None:
            if n - (k + 1) < WAIT:
                out.append({**base, "status": "waiting for the limit"})
            continue
        risk = s * (e - stop)
        if risk <= 0:
            continue
        px, how, m = None, "open", i
        for m in range(i, min(i + HOLD, n)):
            if (s > 0 and l[m] <= stop) or (s < 0 and h[m] >= stop):
                px, how = ((min(o[m], stop) if s > 0 else max(o[m], stop)) if m > i else stop), "stop"
                break
            if (s > 0 and h[m] >= tg) or (s < 0 and l[m] <= tg):
                px, how = ((max(o[m], tg) if s > 0 else min(o[m], tg)) if m > i else tg), "target"
                break
        if px is None and i + HOLD <= n - 1:
            m = i + HOLD - 1
            px, how = c[m], "time"
        last = px if px is not None else c[-1]
        r = (s * (last - e) - (e * COST / 100 if px is not None else 0)) / risk
        out.append({**base, "entry_at": x.index[i], "entry": round(float(e), 2), "status": how,
                    "exit_at": x.index[m] if px is not None else None, "exit_px": round(float(px), 2) if px is not None else None,
                    "last": round(float(c[-1]), 2), "r": round(float(r), 2), "pts": round(float(s * (last - e)), 1)})
        busy = m if px is not None else n
    return out

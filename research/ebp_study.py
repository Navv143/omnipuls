"""Engulfing Bar Play (EBP, train_and_trade reel) on every timeframe.

Bearish EBP: the candle sweeps above the previous candle's high and closes below the previous candle's open (bullish:
sweeps below the previous low, closes above the previous open). Optional: the previous candle is the opposite colour.
Stop (invalidation) just beyond the EBP candle's wick. Target: the draw on liquidity (DOL) = the highest high (lowest low)
of the `dol_n` candles before the EBP for a buy (sell), or a fixed R multiple. Entry at the next open ('market') or a
limit at the EBP candle's 50% ('mid'), valid for `wait` candles. Exit at stop / target, or after `hold` candles.
Stop first when stop and target are in the same candle; costs per round trip.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule in ("5min", "5m"):
        return df
    return df.resample(rule, label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()


def ebp_trades(x: pd.DataFrame, cost: float, entry="market", target="dol", rr=2.0, dol_n=10, prior_opp=True, wait=3,
               hold=20, min_rr=1.0, side_filter=0, intraday_tz=None, last_entry="14:15", flat_at="15:15"):
    """intraday_tz (e.g. 'Asia/Kolkata'): no entry after last_entry, exit at the open of the first candle at / after
    flat_at, never held overnight."""
    o, h, l, c = (x[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(x)
    if intraday_tz:
        lt = x.index.tz_convert(intraday_tz) if x.index.tz is not None else x.index   # naive = already local time
        hhmm, dd = lt.strftime("%H:%M").to_numpy(), lt.normalize().to_numpy()
    out, busy = [], -1
    for k in range(max(dol_n, 1) + 1, n - 2):
        if k <= busy:
            continue
        bull = l[k] < l[k - 1] and c[k] > o[k - 1] and c[k] > o[k]
        bear = h[k] > h[k - 1] and c[k] < o[k - 1] and c[k] < o[k]
        if prior_opp:
            bull = bull and c[k - 1] < o[k - 1]
            bear = bear and c[k - 1] > o[k - 1]
        if not (bull or bear):
            continue
        s = 1 if bull else -1
        if side_filter and s != side_filter:
            continue
        stop = l[k] if s > 0 else h[k]
        # entry
        if intraday_tz and hhmm[k] >= last_entry:
            continue
        if entry == "market":
            i, e = k + 1, o[k + 1]
        else:
            lvl = (h[k] + l[k]) / 2
            i = None
            for j in range(k + 1, min(k + 1 + wait, n)):
                if (s > 0 and l[j] <= lvl) or (s < 0 and h[j] >= lvl):
                    i, e = j, (min(o[j], lvl) if s > 0 else max(o[j], lvl))
                    break
            if i is None:
                continue
        if intraday_tz and (dd[i] != dd[k] or hhmm[i] >= flat_at):
            continue
        risk = s * (e - stop)
        if risk <= 0:
            continue
        if target == "dol":
            tg = h[k - dol_n:k].max() if s > 0 else l[k - dol_n:k].min()
            if s * (tg - e) < min_rr * risk:          # liquidity too close for the minimum reward
                continue
        else:
            tg = e + s * rr * risk
        px, how, m = None, "time", i
        for m in range(i, min(i + hold, n)):
            if intraday_tz and m > i and (dd[m] != dd[i] or hhmm[m] >= flat_at):
                px, how = o[m], "15:15"
                break
            if (s > 0 and l[m] <= stop) or (s < 0 and h[m] >= stop):
                px, how = stop, "stop"
                break
            if (s > 0 and h[m] >= tg) or (s < 0 and l[m] <= tg):
                px, how = tg, "target"
                break
        if px is None:
            px = c[m]
        out.append({"t": x.index[k], "side": s, "r": (s * (px - e) - e * cost / 100) / risk,
                    "pct": s * (px / e - 1) * 100 - cost, "how": how, "stop_pct": risk / e * 100,
                    "rr_planned": abs(tg - e) / risk})
        busy = m
    return pd.DataFrame(out)

"""5-STAR improvement search. Same signal as five_star.py plus optional filters / exits:
  vol_thr      : signal-candle turnover >= thr x its 20-day same-slot average (market or bank stocks)
  net_align    : signal candle's net volume (buy-minus-sell pressure) must point the trade's way (z >= net_min)
  last         : latest signal time
  trend        : trade only with the daily trend (prev close above/below its 20-day average)
  exit_mode    : 'trail' (Supertrend), 'be_trail' (stop to breakeven at +1R, then trail),
                 'half_trail' (book half at +1R, trail the rest with the stop at breakeven)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, NSLOT


def run(d: Data, sym: str, ind: dict, vol_ratio, net_z, vol_thr=2.0, net_align=False, net_min=0.0, first="09:30",
        last="15:00", exit_at="15:15", exit_mode="trail", trend=False, max_risk_atr=None, mom_long=None, mom_short=None):
    s = d.idx(sym)
    O, H, L, C = d.O[s], d.H[s], d.L[s], d.C[s]
    st, ema, vwap, vwma = ind["st"], ind["ema"], ind["vwap"], ind["vwma"]
    ma20 = pd.Series(d.dclose[s]).rolling(20).mean().shift(1).to_numpy()
    prev_close = np.r_[np.nan, d.dclose[s][:-1]]
    f, la, xs = slot(first), slot(last), slot(exit_at)
    out = []
    for day in range(len(d.days)):
        for t in range(f, la + 1):
            c = C[day, t]
            if not np.isfinite(c) or not np.isfinite(vwma[day, t]):
                continue
            buy = c > ema[day, t] and c > vwap[day, t] and c > vwma[day, t] and c > st[day, t]
            sell = c < ema[day, t] and c < vwap[day, t] and c < vwma[day, t] and c < st[day, t]
            side = 1 if buy else (-1 if sell else 0)
            if side == 0 or not (vol_ratio[day, t] >= vol_thr):
                continue
            if net_align and not (side * net_z[day, t] >= net_min):
                continue
            if mom_long is not None and not (mom_long[day, t] if side > 0 else mom_short[day, t]):
                continue
            if trend and np.isfinite(ma20[day]) and side * (prev_close[day] - ma20[day]) <= 0:
                continue
            stop = st[day, t]
            risk = side * (c - stop)
            if risk <= 0:
                continue
            if max_risk_atr is not None and risk > max_risk_atr * d.atr[s, day] / 75 * 10:
                continue
            # walk
            pts_total, done, half = 0.0, False, False
            why, xt = "eod", t
            cur_stop = stop
            for u in range(t + 1, NSLOT):
                if not np.isfinite(O[day, u]):
                    continue
                xt = u
                w = 0.5 if half else 1.0
                if u >= xs:
                    pts_total += w * side * (C[day, u] - c); why = "square-off"; done = True
                    break
                if (side > 0 and L[day, u] <= cur_stop) or (side < 0 and H[day, u] >= cur_stop):
                    px = min(O[day, u], cur_stop) if side > 0 else max(O[day, u], cur_stop)
                    pts_total += w * side * (px - c); why = "stop"; done = True
                    break
                one_r = c + side * risk
                if exit_mode in ("be_trail", "half_trail") and ((side > 0 and H[day, u] >= one_r) or (side < 0 and L[day, u] <= one_r)):
                    if exit_mode == "half_trail" and not half:
                        pts_total += 0.5 * risk
                        half = True
                    cur_stop = max(cur_stop, c) if side > 0 else min(cur_stop, c)
                cur_stop = max(cur_stop, st[day, u]) if side > 0 else min(cur_stop, st[day, u])
            if not done:
                last_i = np.where(np.isfinite(C[day]))[0][-1]
                pts_total += (0.5 if half else 1.0) * side * (C[day, last_i] - c); xt = last_i
            out.append({"date": d.days[day], "side": side, "signal_slot": t, "entry_slot": t + 1, "exit_slot": xt,
                        "entry": c, "risk": risk, "reason": why, "pts": pts_total})
            break
    return pd.DataFrame(out)

"""9 EMA + Fibonacci daily pivots on 5-minute index bars (from an Instagram video, @tradexpavan).

Long: a 5-min candle closes above the 9 EMA after the previous close was at/below it. Enter next candle open.
      Stop: the signal candle's low (or recent swing low). Target: next Fibonacci pivot level above entry.
Short: mirror image. Variant 'pivot_break': the signal candle must also close beyond a pivot level it opened inside.
Fibonacci pivots from yesterday's H/L/C: P=(H+L+C)/3, R1/S1=P+-0.382*(H-L), R2/S2=P+-0.618*(H-L), R3/S3=P+-1.0*(H-L).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, NSLOT

FIB = (-1.0, -0.618, -0.382, 0.0, 0.382, 0.618, 1.0)


def ema_series(close_2d: np.ndarray, n=9) -> np.ndarray:
    """EMA over the continuous 5-min series (carries across days like TradingView)."""
    flat = close_2d.reshape(-1)
    s = pd.Series(flat).ffill()
    e = s.ewm(span=n, adjust=False).mean().to_numpy(copy=True)
    e[np.isnan(flat)] = np.nan
    return e.reshape(close_2d.shape)


def run(d: Data, sym="NIFTY 50", variant="all", stop_mode="candle", min_rr=0.0, max_trades=3,
        first="09:30", last="14:45", exit_at="15:20", sides=(1, -1), buffer=0.0002, swing_n=5):
    s = d.idx(sym)
    O, H, L, C = d.O[s], d.H[s], d.L[s], d.C[s]
    E = ema_series(C)
    ph, pl, pc = d.dhigh[s], d.dlow[s], d.dclose[s]
    out = []
    f, la, xs = slot(first), slot(last), slot(exit_at)
    for day in range(1, len(d.days)):
        rng = ph[day - 1] - pl[day - 1]
        P = (ph[day - 1] + pl[day - 1] + pc[day - 1]) / 3
        if not np.isfinite(P) or rng <= 0:
            continue
        levels = np.array([P + k * rng for k in FIB])
        n_tr, t = 0, f
        while t <= la and n_tr < max_trades:
            if not (np.isfinite(C[day, t]) and np.isfinite(C[day, t - 1]) and np.isfinite(E[day, t])):
                t += 1
                continue
            side = 0
            if C[day, t] > E[day, t] and C[day, t - 1] <= E[day, t - 1]:
                side = 1
            elif C[day, t] < E[day, t] and C[day, t - 1] >= E[day, t - 1]:
                side = -1
            if side not in sides:
                t += 1
                continue
            if variant == "pivot_break":
                crossed = [(O[day, t] < lv < C[day, t]) if side > 0 else (O[day, t] > lv > C[day, t]) for lv in levels]
                if not any(crossed):
                    t += 1
                    continue
            if t + 1 >= xs:
                break
            e = O[day, t + 1]
            if stop_mode == "candle":
                sp = L[day, t] if side > 0 else H[day, t]
            else:
                lo = max(0, t - swing_n + 1)
                sp = np.nanmin(L[day, lo:t + 1]) if side > 0 else np.nanmax(H[day, lo:t + 1])
            ahead = levels[levels > e * (1 + buffer)] if side > 0 else levels[levels < e * (1 - buffer)]
            if len(ahead) == 0 or side * (e - sp) <= 0:
                t += 1
                continue
            tg = ahead.min() if side > 0 else ahead.max()
            risk, reward = abs(e - sp), abs(tg - e)
            if reward / risk < min_rr:
                t += 1
                continue
            # walk: stop first if both inside one bar (conservative)
            px, how, xt = None, "time", None
            for u in range(t + 1, NSLOT):
                if not np.isfinite(O[day, u]):
                    continue
                if u >= xs:
                    px, xt = O[day, u], u
                    break
                if (side > 0 and L[day, u] <= sp) or (side < 0 and H[day, u] >= sp):
                    px, how, xt = (min(O[day, u], sp) if side > 0 else max(O[day, u], sp)), "stop", u
                    break
                if (side > 0 and H[day, u] >= tg) or (side < 0 and L[day, u] <= tg):
                    px, how, xt = (max(O[day, u], tg) if side > 0 else min(O[day, u], tg)), "target", u
                    break
            if px is None:
                last_i = np.where(np.isfinite(C[day]))[0][-1]
                px, xt = C[day, last_i], last_i
            out.append({"date": d.days[day], "side": side, "signal": t, "entry_slot": t + 1, "exit_slot": xt,
                        "entry": e, "exit": px, "stop": sp, "target": tg, "exit_by": how,
                        "pts": side * (px - e), "risk_pts": risk, "rr": reward / risk, "gross": side * (px / e - 1)})
            n_tr += 1
            t = xt + 1  # one trade at a time
    return pd.DataFrame(out)

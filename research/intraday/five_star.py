"""'NIFTY 5-STAR Buy/Sell' Pine indicator, replicated on 5-minute bars.

BUY : close > EMA21, VWAP, VWMA20 and the script's Supertrend, and volume >= threshold. SELL: mirror.
One signal per day, signals on bars opening 09:30-15:00. Entry at the signal close, stop = Supertrend value,
target = entry +/- k x risk (script: 1R). Exit at stop/target or 15:15 (the script has no exit; we square off).
The index has no volume, so VWAP / VWMA / the volume test use the constituent stocks' turnover per bar as weights.
Supertrend reproduced exactly as written in the script (mid-HL +/- factor x ATR, flips on close vs previous value).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, NSLOT


def rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def indicators(d: Data, sym: str, weights: np.ndarray, atr_n=10, factor=3.0, ema_n=21, vwma_n=20):
    s = d.idx(sym)
    O, H, L, C = (a[s].reshape(-1) for a in (d.O, d.H, d.L, d.C))
    W = weights.reshape(-1)
    ok = np.isfinite(C)
    idx = np.where(ok)[0]
    o, h, l, c, w = O[idx], H[idx], L[idx], C[idx], W[idx]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = rma(tr, atr_n)
    mid = (h + l) / 2
    up, lo = mid + factor * atr, mid - factor * atr
    st = np.empty_like(c)
    dir_up = np.empty(len(c), bool)
    st[0] = lo[0] if c[0] > up[0] else up[0]
    dir_up[0] = c[0] > up[0]
    for i in range(1, len(c)):
        if c[i] > st[i - 1]:
            st[i], dir_up[i] = max(lo[i], st[i - 1]), True
        else:
            st[i], dir_up[i] = min(up[i], st[i - 1]), False
    ema = pd.Series(c).ewm(span=ema_n, adjust=False).mean().to_numpy()
    tp = (h + l + c) / 3
    vwma = pd.Series(c * w).rolling(vwma_n).sum().to_numpy() / pd.Series(w).rolling(vwma_n).sum().to_numpy()
    day_of = np.repeat(np.arange(len(d.days)), NSLOT)[idx]
    df = pd.DataFrame({"tpw": tp * w, "w": w, "day": day_of})
    vwap = (df.groupby("day")["tpw"].cumsum() / df.groupby("day")["w"].cumsum()).to_numpy()
    out = {}
    for name, arr in (("st", st), ("ema", ema), ("vwap", vwap), ("vwma", vwma)):
        full = np.full(len(C), np.nan)
        full[idx] = arr
        out[name] = full.reshape(d.C[s].shape)
    return out


def run(d: Data, sym: str, ind: dict, vol_ok: np.ndarray | None, rr=1.0, first="09:30", last="15:00",
        exit_at="15:15", exit_mode="target", sides=(1, -1)):
    s = d.idx(sym)
    O, H, L, C = d.O[s], d.H[s], d.L[s], d.C[s]
    st, ema, vwap, vwma = ind["st"], ind["ema"], ind["vwap"], ind["vwma"]
    f, la, xs = slot(first), slot(last), slot(exit_at)
    out = []
    for day in range(len(d.days)):
        for t in range(f, la + 1):
            c = C[day, t]
            if not np.isfinite(c) or not np.isfinite(vwma[day, t]):
                continue
            if vol_ok is not None and not vol_ok[day, t]:
                continue
            buy = c > ema[day, t] and c > vwap[day, t] and c > vwma[day, t] and c > st[day, t]
            sell = c < ema[day, t] and c < vwap[day, t] and c < vwma[day, t] and c < st[day, t]
            side = 1 if buy else (-1 if sell else 0)
            if side == 0:
                continue
            if side not in sides:
                break  # one signal a day: the day's signal was the other side
            stop = st[day, t]
            risk = side * (c - stop)
            if risk <= 0:
                break
            tgt = c + side * rr * risk
            px = why = None
            xt = t
            for u in range(t + 1, NSLOT):
                if not np.isfinite(O[day, u]):
                    continue
                xt = u
                if u >= xs:
                    px, why = C[day, u], "square-off"
                    break
                if (side > 0 and L[day, u] <= stop) or (side < 0 and H[day, u] >= stop):
                    px, why = (min(O[day, u], stop) if side > 0 else max(O[day, u], stop)), "stop"
                    break
                if exit_mode == "target" and ((side > 0 and H[day, u] >= tgt) or (side < 0 and L[day, u] <= tgt)):
                    px, why = (max(O[day, u], tgt) if side > 0 else min(O[day, u], tgt)), "target"
                    break
                if exit_mode == "trail":  # ride with the Supertrend: exit on a close back through it
                    stop = max(stop, st[day, u]) if side > 0 else min(stop, st[day, u])
            if px is None:
                last_i = np.where(np.isfinite(C[day]))[0][-1]
                px, why, xt = C[day, last_i], "eod", last_i
            out.append({"date": d.days[day], "side": side, "signal_slot": t, "entry_slot": t + 1, "exit_slot": xt,
                        "entry": c, "exit": px, "risk": risk, "reason": why, "pts": side * (px - c)})
            break
    return pd.DataFrame(out)

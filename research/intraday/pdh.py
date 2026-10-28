"""Setup: open within +-1% of previous close -> stock completes a 1% move from the open -> first 5-minute candle that
closes beyond the previous day's high (long) / low (short). Entry at the next candle's open.
Builds one row per signal with volume / ATR / VWAP / candle features known at the signal candle's close."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, NSLOT


def events(d: Data, gap_max=0.01, move=0.01, last_signal="14:30", vol_days=(10, 20)) -> pd.DataFrame:
    si = np.array(d.stock_idx)
    O, H, L, C, V = d.O[si], d.H[si], d.L[si], d.C[si], d.V[si]
    pdh = np.roll(d.dhigh[si], 1, axis=1)
    pdl = np.roll(d.dlow[si], 1, axis=1)
    pdh[:, 0] = pdl[:, 0] = np.nan
    o0 = O[..., 0]
    gap = d.gap[si]
    atrp = d.atr[si] / d.prev_close[si]
    valid = d.valid[si] & (np.abs(gap) <= gap_max) & np.isfinite(pdh)
    with np.errstate(all="ignore"):
        cmax = np.fmax.accumulate(np.nan_to_num(H, nan=-np.inf), axis=2)
        cmin = np.fmin.accumulate(np.nan_to_num(L, nan=np.inf), axis=2)
        Vz = np.nan_to_num(V)
        cumV = np.cumsum(Vz, axis=2)
        tp = (H + L + C) / 3
        vwap = np.cumsum(np.nan_to_num(tp) * Vz, axis=2) / np.where(cumV > 0, cumV, np.nan)
    S, D, T = C.shape
    # average cumulative volume up to each slot over the previous N days
    avg_cum = {}
    for n in vol_days:
        a = cumV.transpose(0, 2, 1).reshape(S * T, D)
        a = pd.DataFrame(a.T).rolling(n, min_periods=n).mean().shift(1).values.T
        avg_cum[n] = a.reshape(S, T, D).transpose(0, 2, 1)
    sav = d.slot_avg_vol(10)[si]
    last = slot(last_signal)
    rows = []
    for side in (1, -1):
        lvl = pdh if side > 0 else pdl
        brk = (C > lvl[..., None]) if side > 0 else (C < lvl[..., None])
        brk[..., last + 1:] = False
        brk[..., :1] &= True
        first = np.argmax(brk, axis=2)
        has = brk.any(axis=2) & valid
        # the open must be on the near side of the level (the break happens intraday, not at the open)
        has &= (o0 < lvl) if side > 0 else (o0 > lvl)
        s_idx, d_idx = np.where(has)
        t_idx = first[s_idx, d_idx]
        ext = cmax if side > 0 else cmin
        mv = side * (ext[s_idx, d_idx, t_idx] / o0[s_idx, d_idx] - 1)
        for s, dd, t, m in zip(s_idx, d_idx, t_idx, mv):
            if m < move or t + 1 >= NSLOT:
                continue
            gs = si[s]
            a = atrp[s, dd]
            rng_ = (cmax[s, dd, t] - cmin[s, dd, t]) / d.prev_close[gs, dd]
            ch, cl, cc, co = H[s, dd, t], L[s, dd, t], C[s, dd, t], O[s, dd, t]
            r = {"date": d.days[dd], "sym": d.syms[gs], "s": gs, "d": dd, "side": side, "signal_slot": t,
                 "entry_slot": t + 1, "signal_time": f"{(555 + 5 * t) // 60}:{(555 + 5 * t) % 60:02d}",
                 "gap": gap[s, dd], "atr_pct": a, "level": lvl[s, dd],
                 "move_from_open": side * (cc / o0[s, dd] - 1), "move_atr": side * (cc / o0[s, dd] - 1) / a,
                 "range_atr": rng_ / a,
                 "level_dist_atr": side * (lvl[s, dd] / o0[s, dd] - 1) / a,
                 "candle_vol_x": V[s, dd, t] / sav[s, dd, t] if sav[s, dd, t] > 0 else np.nan,
                 "candle_body_atr": side * (cc - co) / d.prev_close[gs, dd] / a,
                 "close_strength": ((cc - cl) / (ch - cl) if side > 0 else (ch - cc) / (ch - cl)) if ch > cl else 0.5,
                 "above_vwap": side * (cc / vwap[s, dd, t] - 1) / a,
                 "nifty_ret": d.C[d.idx("NIFTY 50"), dd, t] / d.O[d.idx("NIFTY 50"), dd, 0] - 1}
            for n in vol_days:
                av = avg_cum[n][s, dd, t]
                r[f"cumvol_x{n}"] = cumV[s, dd, t] / av if av > 0 else np.nan
            rows.append(r)
    ev = pd.DataFrame(rows).sort_values(["date", "signal_slot"]).reset_index(drop=True)
    ev["nifty_with"] = np.sign(ev["nifty_ret"]) == ev["side"]
    return ev

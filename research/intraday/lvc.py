"""Top-5 gainers / losers at 10:00 -> lowest-volume opposite-colour 5-min candle (9:15-10:00) -> entry when a later
candle closes beyond it (above its high for gainers = long, below its low for losers = short). Enter next bar open."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, walk, slot
import optmodel as M

RANK_SLOT = slot("10:00")  # bars 0..8 (9:15-9:55) are complete at 10:00


def signals(d: Data, rank_by="prev_close", top=5, until="13:00", fresh_cross=False, min_move=0.0):
    si = np.array(d.stock_idx)
    k = RANK_SLOT
    px10 = d.C[si, :, k - 1]
    base = d.prev_close[si] if rank_by == "prev_close" else d.O[si, :, 0]
    chg = np.where(d.valid[si], px10 / base - 1, np.nan)
    last = slot(until)
    out = []
    for day in range(len(d.days)):
        c = chg[:, day]
        ok = np.where(np.isfinite(c))[0]
        if len(ok) < 20:
            continue
        order = ok[np.argsort(c[ok])]
        for side, picks in ((1, order[::-1][:top]), (-1, order[:top])):
            for rnk, k_ in enumerate(picks, 1):
                if side * c[k_] < min_move:
                    continue
                s = si[k_]
                O, H, L, C, V = (a[s, day] for a in (d.O, d.H, d.L, d.C, d.V))
                opp = [t for t in range(k) if np.isfinite(C[t]) and (C[t] < O[t] if side > 0 else C[t] > O[t])]
                if not opp:
                    continue
                ref = min(opp, key=lambda t: V[t])
                lvl = H[ref] if side > 0 else L[ref]
                other = L[ref] if side > 0 else H[ref]
                for t in range(k, last):
                    if not np.isfinite(C[t]):
                        continue
                    crossed = C[t] > lvl if side > 0 else C[t] < lvl
                    if fresh_cross:
                        prev = C[t - 1] if np.isfinite(C[t - 1]) else C[t]
                        crossed &= (prev <= lvl) if side > 0 else (prev >= lvl)
                    if crossed:
                        out.append({"s": s, "d": day, "side": side, "entry_slot": t + 1, "signal_slot": t, "ref_slot": ref,
                                    "level": lvl, "ref_other": other, "rank": rnk, "chg10": c[k_],
                                    "ref_vol_x": V[ref] / np.nanmean(V[:k]), "already_beyond_at_10": t == k and
                                    ((C[k - 1] > lvl) if side > 0 else (C[k - 1] < lvl))})
                        break
    return pd.DataFrame(out)


def simulate(d: Data, sig: pd.DataFrame, stop="ref", stop_atr=0.5, trail_atr=None, exit_at="15:20"):
    dte = M.dte_table(d.days)
    rv = pd.DataFrame(np.log(d.dclose / d.prev_close).T).rolling(20, min_periods=15).std().shift(1).values.T
    xs = slot(exit_at)
    rows = []
    for r in sig.itertuples():
        s, day, side, es = int(r.s), int(r.d), int(r.side), int(r.entry_slot)
        if es >= xs:
            continue
        e = d.O[s, day, es]
        atr = d.atr[s, day]
        if not (np.isfinite(e) and np.isfinite(atr)):
            continue
        sp = r.ref_other if stop == "ref" else e - side * stop_atr * atr
        if side * (e - sp) <= 0:
            sp = e - side * 0.1 * atr
        px, how, xt = walk(d, s, day, side, es, e, sp, trail=trail_atr * atr if trail_atr else None, exit_slot=xs)
        rows.append({"date": d.days[day], "sym": d.syms[s], "side": side, "entry_slot": es, "exit_slot": xt, "entry": e,
                     "exit": px, "exit_by": how, "gross": side * (px / e - 1), "risk_pct": abs(e - sp) / e,
                     "rank": r.rank, "chg10": r.chg10, "ref_vol_x": r.ref_vol_x, "beyond10": r.already_beyond_at_10,
                     "s": s, "d": day})
    t = pd.DataFrame(rows)
    iv = np.maximum(rv[t.s, t.d] * np.sqrt(252) * 1.15, 0.18)
    t["opt"], _ = M.option_return(t.entry.values, t.exit.values, t.side.values, dte[t.d], t.entry_slot.values,
                                  t.exit_slot.values, iv, cost=0.02)
    t["opt4"] = t["opt"] - 0.02
    return t

"""Strategies tested on the 5-minute cube."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, slot, walk, trade_row, NSLOT

V3 = dict(top_n=2, entry_until="12:00", vol_mult=1.5, vol_n=10, stop_atr=0.5, trail_atr=1.0, exit_at="15:20",
          nifty_filter=True, vol_filter=True, score=("atr", "orr", "rvol", "gap"), fade=False, first_only=False)


def rank_pct(x: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Percentile rank (0-100) across stocks for each day, only among valid entries."""
    df = pd.DataFrame(np.where(valid, x, np.nan))
    return df.rank(axis=0, pct=True).values * 100


def v3(d: Data, **kw) -> pd.DataFrame:
    p = {**V3, **kw}
    si = np.array(d.stock_idx)
    valid = d.valid[si]
    feats = {"atr": d.atr[si] / d.prev_close[si], "orr": d.or_range_pct[si], "rvol": d.rvol[si],
             "gap": np.abs(d.gap[si])}
    for k in p["score"]:
        valid &= np.isfinite(feats[k])
    score = sum(np.nan_to_num(rank_pct(feats[k], valid)) for k in p["score"])
    score = np.where(valid, score, -1)
    ni = d.idx("NIFTY 50")
    n_hi, n_lo, nC = d.or_high[ni], d.or_low[ni], d.C[ni]
    sav = d.slot_avg_vol(p["vol_n"])
    until, exit_slot = slot(p["entry_until"]), slot(p["exit_at"])
    out = []
    order = np.argsort(-score, axis=0)
    for day in range(len(d.days)):
        for rank in range(p["top_n"]):
            k = order[rank, day]
            if score[k, day] < 0:
                break
            s = si[k]
            hi, lo, atr = d.or_high[s, day], d.or_low[s, day], d.atr[s, day]
            C, V = d.C[s, day], d.V[s, day]
            for t in range(3, until):
                if not np.isfinite(C[t]):
                    continue
                side = 1 if C[t] > hi else (-1 if C[t] < lo else 0)
                if not side:
                    continue
                if p["vol_filter"] and not (np.isfinite(sav[s, day, t]) and sav[s, day, t] > 0
                                            and V[t] >= p["vol_mult"] * sav[s, day, t]):
                    if p["first_only"]:
                        break
                    continue
                if p["nifty_filter"]:
                    nc = nC[day, 3:t + 1]
                    if (side > 0 and np.nanmin(nc, initial=np.inf) < n_lo[day]) or \
                            (side < 0 and np.nanmax(nc, initial=-np.inf) > n_hi[day]):
                        if p["first_only"]:
                            break
                        continue
                if t + 1 >= exit_slot or not np.isfinite(d.O[s, day, t + 1]):
                    break
                trade_side = -side if p["fade"] else side
                entry = d.O[s, day, t + 1]
                stop = entry - trade_side * p["stop_atr"] * atr
                px, how, xt = walk(d, s, day, trade_side, t + 1, entry, stop,
                                   trail=p["trail_atr"] * atr if p["trail_atr"] else None, exit_slot=exit_slot)
                op = d.or_open[s, day]
                a_plus = (side > 0 and op <= lo * 1.0005) or (side < 0 and op >= hi * 0.9995)
                out.append(trade_row(d, s, day, trade_side, entry, px, how, p["stop_atr"] * atr / entry,
                                     signal=f"{9 + (15 + 5 * t) // 60}:{(15 + 5 * t) % 60:02d}", a_plus=bool(a_plus),
                                     with_gap=bool(np.sign(d.gap[s, day]) == side), gap=d.gap[s, day],
                                     atr_pct=atr / d.prev_close[s, day], rank=rank + 1))
                break
    return pd.DataFrame(out)


def gap_setup(d: Data, kind: str = "fade", gap_min=0.03, top_n=2, stop=0.01, entry="09:15", exit_at="15:20",
              nifty_max=None, sector_gap=None, target=None, longs_only=False) -> pd.DataFrame:
    """Gap trades. kind='fade' trades against the gap, 'go' with it. Entry at the open of the `entry` bar.
    nifty_max: only on days Nifty gap <= this (panic). sector_gap: require gap - sector average gap <= -x (longs)."""
    si = np.array(d.stock_idx)
    gap = np.where(d.valid[si], d.gap[si], np.nan)
    ng = d.gap[d.idx("NIFTY 50")]
    if sector_gap is not None:
        secs = np.array([d.sector[d.syms[s]] for s in si])
        sec_avg = np.full_like(gap, np.nan)
        for sec in set(secs):
            m = secs == sec
            tot, cnt = np.nansum(gap[m], 0), np.isfinite(gap[m]).sum(0)
            for j in np.where(m)[0]:  # sector average excluding the stock itself
                g = np.nan_to_num(gap[j])
                c = cnt - np.isfinite(gap[j])
                sec_avg[j] = np.where(c > 0, (tot - g) / np.maximum(c, 1), np.nan)
    es, xs = slot(entry), slot(exit_at)
    out = []
    for day in range(len(d.days)):
        if nifty_max is not None and not (ng[day] <= nifty_max):
            continue
        g = gap[:, day]
        cand = np.where(np.abs(g) >= gap_min)[0]
        if longs_only or nifty_max is not None or sector_gap is not None:
            cand = cand[g[cand] < 0] if kind == "fade" else cand[g[cand] > 0]
        if sector_gap is not None:
            cand = cand[(g[cand] - sec_avg[cand, day]) <= -sector_gap]
        cand = cand[np.argsort(-np.abs(g[cand]))][:top_n]
        for k in cand:
            s = si[k]
            side = -int(np.sign(g[k])) if kind == "fade" else int(np.sign(g[k]))
            e = d.O[s, day, es]
            if not np.isfinite(e):
                continue
            sp = e * (1 - side * stop)
            tp = e * (1 + side * target) if target else None
            px, how, _ = walk(d, s, day, side, es, e, sp, target_px=tp, exit_slot=xs)
            out.append(trade_row(d, s, day, side, e, px, how, stop, gap=g[k], nifty_gap=ng[day]))
    return pd.DataFrame(out)


def index_orb(d: Data, sym="NIFTY 50", or_bars=3, stop="range", exit_at="15:20", until="12:00", target_r=None):
    """Index opening-range breakout: first 5-minute close beyond the range, enter next open, stop at the other
    side of the range (or a fraction of it), exit 15:20."""
    s = d.idx(sym)
    out = []
    for day in range(len(d.days)):
        H, L, C, O = d.H[s, day], d.L[s, day], d.C[s, day], d.O[s, day]
        hi, lo = np.nanmax(H[:or_bars]), np.nanmin(L[:or_bars])
        if not (np.isfinite(hi) and np.isfinite(lo)):
            continue
        for t in range(or_bars, slot(until)):
            side = 1 if C[t] > hi else (-1 if C[t] < lo else 0)
            if side and np.isfinite(O[t + 1]):
                e = O[t + 1]
                sp = (lo if side > 0 else hi) if stop == "range" else e - side * (hi - lo) * stop
                risk = abs(e - sp) / e
                tp = e + side * target_r * abs(e - sp) if target_r else None
                px, how, _ = walk(d, s, day, side, t + 1, e, sp, target_px=tp, exit_slot=slot(exit_at))
                out.append(trade_row(d, s, day, side, e, px, how, max(risk, 1e-4)))
                break
    return pd.DataFrame(out)


def index_overnight(d: Data, sym="NIFTY 50"):
    """Buy the 15:20 bar open, sell next day's 09:20 bar open (skips the possibly stale 09:15 print)."""
    s = d.idx(sym)
    b = d.O[s, :, slot("15:20")]
    sl = d.O[s, :, slot("09:20")]
    intr = d.O[s, :, slot("15:20")] / d.O[s, :, slot("09:20")] - 1
    t = pd.DataFrame({"date": d.days[1:], "gross": sl[1:] / b[:-1] - 1, "risk_pct": 0.01, "sym": sym})
    i = pd.DataFrame({"date": d.days, "gross": intr, "risk_pct": 0.01, "sym": sym})
    return t.dropna(), i.dropna()

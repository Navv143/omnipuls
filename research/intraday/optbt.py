"""Evaluate picks as option trades. picks: DataFrame with s, d, side (+1/-1), entry_slot."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import Data, walk, slot
import optmodel as M

_dte = None


def simulate(d: Data, picks: pd.DataFrame, stop_atr=0.5, trail_atr=None, exit_at="15:20", target_atr=None):
    global _dte
    if _dte is None:
        _dte = M.dte_table(d.days)
    rows = []
    xs = slot(exit_at)
    for r in picks.itertuples():
        s, day, side, es = int(r.s), int(r.d), int(r.side), int(r.entry_slot)
        if es >= xs:
            continue
        e = d.O[s, day, es]
        atr = d.atr[s, day]
        if not (np.isfinite(e) and np.isfinite(atr)):
            continue
        stop = e - side * stop_atr * atr if stop_atr else None
        tgt = e + side * target_atr * atr if target_atr else None
        px, how, xt = walk(d, s, day, side, es, e, stop, trail=trail_atr * atr if trail_atr else None,
                           target_px=tgt, exit_slot=xs)
        rows.append({"date": d.days[day], "sym": d.syms[s], "side": side, "entry_slot": es, "exit_slot": xt,
                     "entry": e, "exit": px, "exit_by": how, "gross": side * (px / e - 1), "risk_pct": (stop_atr or 1) * atr / e,
                     "s": s, "d": day, **{c: getattr(r, c) for c in picks.columns if c not in ("s", "d", "side", "entry_slot")}})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    rv = pd.DataFrame(np.log(d.dclose / d.prev_close).T).rolling(20, min_periods=15).std().shift(1).values.T
    t["iv"] = np.maximum(rv[t.s, t.d] * np.sqrt(252) * 1.15, 0.18)
    t["dte"] = _dte[t.d]
    for cost, tag in ((0.02, "opt"), (0.04, "opt_hi")):
        t[tag], prem = M.option_return(t.entry.values, t.exit.values, t.side.values, t.dte.values,
                                       t.entry_slot.values, t.exit_slot.values, t.iv.values, cost=cost)
    t["premium_pct"] = prem
    return t


def stats(t: pd.DataFrame, label: str, stock_cost=0.0012) -> dict:
    if t is None or len(t) == 0:
        return {"setup": label, "trades": 0}
    o = t["opt"]
    g = t["gross"] - stock_cost
    yrs = o.groupby(t["date"].dt.year).mean()
    daily = o.groupby(t["date"]).mean()
    eq = (daily * 0.02).cumsum()  # each day risks 2% of capital as premium, split across that day's trades
    span = max((t["date"].max() - t["date"].min()).days / 365.25, 0.5)
    return {"setup": label, "trades": len(t), "per yr": round(len(t) / span),
            "stock avg %": round(100 * g.mean(), 3),
            "opt win%": round(100 * (o > 0).mean(), 1), "opt avg %": round(100 * o.mean(), 2),
            "opt median %": round(100 * o.median(), 1), "opt PF": round(o[o > 0].sum() / -o[o <= 0].sum(), 2),
            "opt avg (4% cost)": round(100 * t["opt_hi"].mean(), 2),
            "t-stat": round(o.mean() / o.std() * np.sqrt(len(o)), 2),
            "yrs +": f"{(yrs > 0).sum()}/{len(yrs)}",
            "22-26 opt %": round(100 * o[t.date >= "2022"].mean(), 2),
            "2025-26 opt %": round(100 * o[t.date >= "2025"].mean(), 2),
            "maxDD (2%/day)": round(100 * (eq - eq.cummax()).min(), 1)}


def yearly(t, col="opt"):
    return (100 * t[col]).groupby(t["date"].dt.year).mean().round(1)

"""Bank Nifty failed-break fade, live (tested in research/bn_fade.py, Dec 2021 - Oct 2026: +26 pts a trade after
5 pts cost, 58 trades a year, 49% wins, positive in both halves and in all 36 tried stop / window / exit mixes).

Rule, on 5-minute candles:
1. The day opens inside yesterday's range (not above the high or below the low).
2. Between 9:20 and 14:30 a candle CLOSES beyond yesterday's high (or low).
3. Within the next 30 minutes (6 candles) a candle closes back inside the level: trade AGAINST the break at that
   close (short after a high break, long after a low break). One trade per level per day.
4. Stop 0.4 x the daily ATR(14) from the entry; target 2 x that risk; otherwise out at the 15:10 candle's close.
   Inside a candle the stop counts before the target.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

FIRST, LAST_BREAK, OUT = "09:20", "14:30", "15:10"
BACK_WITHIN = 6      # candles
STOP_ATR = 0.4
TARGET_R = 2.0
COST = 5.0


def _daily(bn: pd.DataFrame) -> pd.DataFrame:
    d = bn.groupby(bn.index.normalize()).agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
                                             Close=("Close", "last"))
    pc = d["Close"].shift(1)
    tr = np.maximum(d["High"] - d["Low"], np.maximum((d["High"] - pc).abs(), (d["Low"] - pc).abs()))
    d["ATR"] = tr.rolling(14, min_periods=5).mean().shift(1)
    d["PDH"], d["PDL"] = d["High"].shift(1), d["Low"].shift(1)
    return d


def evaluate(bn: pd.DataFrame, now: datetime | None = None) -> dict:
    """The latest session in `bn` (5-minute candles): levels, what each side is doing, and any trades."""
    if bn is None or bn.empty:
        return {"status": "no data"}
    bn = bn.sort_index()
    bn = bn[~bn.index.duplicated(keep="last")]
    t = bn.index.strftime("%H:%M")
    bn = bn[(t >= "09:15") & (t <= "15:25")]
    if now is not None:  # closed candles only
        bn = bn[bn.index + pd.Timedelta(minutes=5) <= pd.Timestamp(now)]
    days = bn.index.normalize().unique()
    if len(days) < 6:
        return {"status": "need more sessions"}
    D = _daily(bn)
    day = days[-1]
    lv = D.loc[day]
    today = bn[bn.index.normalize() == day]
    hm = today.index.strftime("%H:%M").to_numpy()
    C, H, L = (today[c].to_numpy(float) for c in ("Close", "High", "Low"))
    atr, op = float(lv["ATR"]), float(lv["Open"])
    out = {"status": "ok", "session": day, "pdh": float(lv["PDH"]), "pdl": float(lv["PDL"]), "atr": atr,
           "risk": STOP_ATR * atr, "open": op, "last": float(C[-1]), "last_time": hm[-1], "sides": [], "trades": []}
    for brk, lvl, name in ((1, out["pdh"], "Yesterday's high"), (-1, out["pdl"], "Yesterday's low")):
        side = {"level": name, "price": lvl, "break": None, "back": None}
        if brk * (op - lvl) > 0:
            side["state"] = "opened beyond it: no trade today"
            out["sides"].append(side)
            continue
        ok = (hm >= FIRST) & (hm <= LAST_BREAK) & (brk * (C - lvl) > 0)
        hit = np.flatnonzero(ok)
        if not len(hit):
            side["state"] = "not broken" + (" (break window over)" if hm[-1] > LAST_BREAK else "")
            out["sides"].append(side)
            continue
        kb = int(hit[0])
        side["break"] = (hm[kb], float(C[kb]))
        back = [j for j in range(kb + 1, min(kb + 1 + BACK_WITHIN, len(C))) if hm[j] < OUT and brk * (C[j] - lvl) <= 0]
        if not back:
            waited = len(C) - 1 - kb
            side["state"] = ("broke and held: no fade" if waited >= BACK_WITHIN or hm[-1] >= OUT else
                             f"broke at {hm[kb]}: watching for a close back inside until "
                             f"{(today.index[kb] + pd.Timedelta(minutes=5 * BACK_WITHIN)).strftime('%H:%M')}")
            out["sides"].append(side)
            continue
        k = back[0]
        side["back"] = (hm[k], float(C[k]))
        s = -brk
        e = float(C[k])
        risk = STOP_ATR * atr
        stop, target = e - s * risk, e + s * risk * TARGET_R
        state, exit_px, exit_time, pts = "open", None, None, s * (float(C[-1]) - e)
        for j in range(k + 1, len(C)):
            if (s > 0 and L[j] <= stop) or (s < 0 and H[j] >= stop):
                state, exit_px, exit_time = "stopped", stop, hm[j]
                break
            if (s > 0 and H[j] >= target) or (s < 0 and L[j] <= target):
                state, exit_px, exit_time = "target hit", target, hm[j]
                break
            if hm[j] >= OUT:
                state, exit_px, exit_time = "closed 15:15", float(C[j]), hm[j]
                break
        if exit_px is not None:
            pts = s * (exit_px - e)
        side["state"] = f"FADE {'SELL' if s < 0 else 'BUY'} at {hm[k]}: {state}"
        out["sides"].append(side)
        out["trades"].append({"side": s, "level": name, "time": hm[k], "entry": e, "stop": stop, "target": target,
                              "risk": risk, "state": state, "exit": exit_px, "exit_time": exit_time, "pts": pts,
                              "break_time": hm[kb]})
    return out

"""1-minute 'first swing breakout' on Nifty / Bank Nifty futures (continuous near-month, real volume), out within 1 hour.

Data: github.com/aeron7/nifty-banknifty-intraday-data (1-min OHLCV + OI, 2015 - Feb 2023), files <SYM>_F1.txt.
Bar time in the files is the bar's END minute (09:16 = 09:15-09:16).

Swing high at bar i: high[i] > high of the N bars before and the N bars after (confirmed only N bars later).
Rules per day: take the FIRST swing high and FIRST swing low formed after 09:15. Once both are known (or as each is
confirmed), the first 1-min CLOSE above the swing high = long, below the swing low = short (one trade a day).
Entry at that close. Stop: the opposite first swing (mode 'swing') or the breakout candle's extreme (mode 'candle').
Exit: target rr x risk, or after `hold` minutes at the close, or 15:15. Stop checked before target inside a minute.
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

ROOT = "/tmp/nbm"


def load(sym: str) -> pd.DataFrame:
    files = [f for f in glob.glob(f"{ROOT}/20*/**/{sym}_F1.txt", recursive=True)]
    frames = []
    for f in files:
        try:
            x = pd.read_csv(f, header=None, usecols=range(9),
                            names=["sym", "d", "t", "o", "h", "l", "c", "v", "oi"], dtype={"d": str, "t": str})
            frames.append(x)
        except Exception:
            pass
    df = pd.concat(frames, ignore_index=True)
    df["dt"] = pd.to_datetime(df["d"] + " " + df["t"], format="%Y%m%d %H:%M", errors="coerce")
    df = df.dropna(subset=["dt"]).drop_duplicates("dt").sort_values("dt")
    df = df[(df.dt.dt.time >= pd.Timestamp("09:16").time()) & (df.dt.dt.time <= pd.Timestamp("15:30").time())]
    return df[["dt", "o", "h", "l", "c", "v", "oi"]].reset_index(drop=True)


def run_day(g: pd.DataFrame, N=3, stop_mode="swing", rr=2.0, hold=60, first_minute="09:16", last_entry="13:30",
            vol_mult=None, max_risk_pct=None, min_risk_pct=None):
    h, l, c, o, v = (g[k].to_numpy() for k in ("h", "l", "c", "o", "v"))
    tm = g["dt"].dt.strftime("%H:%M").to_numpy()
    n = len(g)
    sh = sl = None  # (index, level)
    vavg = pd.Series(v).rolling(20, min_periods=5).mean().shift(1).to_numpy()
    for i in range(n):
        # confirm swings whose pivot is at i - N
        p = i - N
        if p >= N and tm[p] >= first_minute:
            if sh is None and h[p] > h[p - N:p].max() and h[p] > h[p + 1:i + 1].max():
                sh = (p, h[p])
            if sl is None and l[p] < l[p - N:p].min() and l[p] < l[p + 1:i + 1].min():
                sl = (p, l[p])
        if tm[i] > last_entry:
            return None
        side = 0
        if sh is not None and i > sh[0] + N - 1 and c[i] > sh[1] and (i == 0 or c[i - 1] <= sh[1]):
            side = 1
        elif sl is not None and i > sl[0] + N - 1 and c[i] < sl[1] and (i == 0 or c[i - 1] >= sl[1]):
            side = -1
        if not side:
            continue
        if vol_mult and not (np.isfinite(vavg[i]) and v[i] >= vol_mult * vavg[i]):
            continue
        e = c[i]
        if stop_mode == "swing":
            opp = sl if side > 0 else sh
            if opp is None:
                stop = l[i] if side > 0 else h[i]
            else:
                stop = opp[1]
        else:
            stop = l[i] if side > 0 else h[i]
        risk = side * (e - stop)
        if risk <= 0:
            continue
        if max_risk_pct and risk / e > max_risk_pct:
            continue
        if min_risk_pct and risk / e < min_risk_pct:
            continue
        tgt = e + side * rr * risk if rr else None
        end = min(n - 1, i + hold)
        px = why = None
        j = i
        for j in range(i + 1, n):
            if tm[j] >= "15:15":
                px, why = c[j], "15:15"; break
            if (side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop):
                px, why = (min(o[j], stop) if side > 0 else max(o[j], stop)), "stop"; break
            if tgt is not None and ((side > 0 and h[j] >= tgt) or (side < 0 and l[j] <= tgt)):
                px, why = (max(o[j], tgt) if side > 0 else min(o[j], tgt)), "target"; break
            if j >= end:
                px, why = c[j], "time"; break
        if px is None:
            px, why = c[-1], "eod"
        return {"date": g["dt"].iloc[0].normalize(), "entry_time": tm[i], "side": side, "entry": e, "stop": stop,
                "risk": risk, "exit": px, "reason": why, "mins": j - i, "pts": side * (px - e),
                "swing_time": tm[(sh if side > 0 else sl)[0]]}
    return None


def run(df: pd.DataFrame, **kw) -> pd.DataFrame:
    out = []
    for _, g in df.groupby(df["dt"].dt.date):
        if len(g) < 200:
            continue
        r = run_day(g.reset_index(drop=True), **kw)
        if r:
            out.append(r)
    return pd.DataFrame(out)

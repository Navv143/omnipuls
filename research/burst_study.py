"""Burst study: every wild 5-minute candle (|return| ≥ K x the normal 5-min move) on crypto, gold, oil, forex and
index futures, and what the next 1-7 candles do. Which conditions make the burst run on (momentum) and which make it
snap back?

Per burst: direction, size (z), volume vs the usual volume at that time of day, where it closed in its own range,
whether it broke the last hour's / last 24 hours' high or low, the 1-hour trend, the hour (New York time), and whether
the next candle confirmed it. Forward result = direction x (close after N candles / entry - 1), entry at the next
candle's open (or after the confirming candle), in % and in multiples of the normal move, minus costs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COST = {"BTC": 0.05, "ETH": 0.05, "SOL": 0.06, "GOLD": 0.02, "GC": 0.02, "OIL": 0.03, "EURUSD": 0.01, "GBPUSD": 0.012,
        "USDJPY": 0.01, "USDINR": 0.02, "NQ": 0.01}


def events(df: pd.DataFrame, k: float = 4.0, win_days: int = 20, min_days: int = 5, horizon: int = 7) -> pd.DataFrame:
    x = df[~df.index.duplicated(keep="last")].sort_index().copy()
    o, h, l, c, v = (x[k_].to_numpy(float) for k_ in ("Open", "High", "Low", "Close", "Volume"))
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1] * 100
    r = pd.Series(ret, index=x.index)
    sd = r.rolling(288 * win_days, min_periods=288 * min_days).std().shift().to_numpy()
    z = ret / sd
    ny = x.index.tz_convert("America/New_York")
    hm = ny.hour * 60 + ny.minute
    tod = pd.Series(v, index=x.index).groupby(hm).transform(lambda s: s.rolling(20, min_periods=5).median().shift())
    vol_x = v / tod.to_numpy()
    hi12, lo12 = pd.Series(h).rolling(12).max().shift().to_numpy(), pd.Series(l).rolling(12).min().shift().to_numpy()
    hi288, lo288 = pd.Series(h).rolling(288).max().shift().to_numpy(), pd.Series(l).rolling(288).min().shift().to_numpy()
    e = pd.Series(c).ewm(span=12 * 20, adjust=False).mean().to_numpy()          # ~20-hour EMA on 5-min candles
    slope = np.r_[np.full(12, np.nan), e[12:] - e[:-12]]
    idx = np.flatnonzero(np.abs(z) >= k)
    rows = []
    n = len(x)
    for i in idx:
        if i + horizon + 2 >= n or not np.isfinite(sd[i]):
            continue
        d = 1 if z[i] > 0 else -1
        rng = h[i] - l[i]
        clv = ((c[i] - l[i]) / rng if d > 0 else (h[i] - c[i]) / rng) if rng > 0 else 0.5
        conf = np.sign(c[i + 1] - o[i + 1]) == d
        row = {"t": x.index[i], "dir": d, "z": abs(z[i]), "vol_x": vol_x[i], "clv": clv,
               "brk1h": (c[i] > hi12[i]) if d > 0 else (c[i] < lo12[i]),
               "brk24h": (c[i] > hi288[i]) if d > 0 else (c[i] < lo288[i]),
               "trend": np.sign(slope[i]) == d if np.isfinite(slope[i]) else False,
               "hour": ny[i].hour, "hm": hm[i], "conf": bool(conf), "sd": sd[i], "price": c[i]}
        e0 = o[i + 1]
        for N in (1, 3, 6):
            row[f"f{N}"] = d * (c[i + N] / e0 - 1) * 100            # entry next open, exit close of candle i+N
        e1 = o[i + 2]                                               # after the confirming candle
        row["fc6"] = d * (c[i + 7] / e1 - 1) * 100
        seg_h, seg_l = h[i + 1:i + 7].max(), l[i + 1:i + 7].min()
        row["mfe6"] = d * ((seg_h if d > 0 else seg_l) / e0 - 1) * 100
        row["mae6"] = d * ((seg_l if d > 0 else seg_h) / e0 - 1) * 100
        rows.append(row)
    return pd.DataFrame(rows)


def table(ev: pd.DataFrame, cost: float, col: str = "f6", by=None, min_n: int = 30) -> pd.DataFrame:
    """Mean forward result (direction-adjusted, net of cost) and the share of bursts that ran on, by group."""
    if ev.empty:
        return pd.DataFrame()
    g = ev.groupby(by) if by is not None else ev.groupby(lambda _: "all")
    t = g[col].agg(n="size", mean="mean", std="std")
    t["net%"] = t["mean"] - cost
    t["run_on%"] = g[col].apply(lambda s: (s > cost).mean() * 100)
    t["t"] = t["mean"] / t["std"] * np.sqrt(t["n"])
    return t[t["n"] >= min_n].drop(columns="std").round(3)


def trades(df, cost, k=8.0, direction=1, hold=6, stop="low", stop_pct=1.0, wait=0, win_days=20, min_days=5):
    """Trade every burst of |z| ≥ k in `direction` (+1 up-bursts, -1 down-bursts traded long as a snap-back with
    direction=-1 & long=True is the crash buy): long in the burst's direction (momentum). Entry at the open `wait`
    candles after the burst candle (+1); stop = the burst candle's low ('low'), its midpoint ('mid') or stop_pct %;
    exit after `hold` candles. One position at a time."""
    x = df[~df.index.duplicated(keep="last")].sort_index()
    o, h, l, c = (x[k_].to_numpy(float) for k_ in ("Open", "High", "Low", "Close"))
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1] * 100
    sd = pd.Series(ret).rolling(288 * win_days, min_periods=288 * min_days).std().shift().to_numpy()
    z = ret / sd
    out, busy = [], -1
    for i in np.flatnonzero(z * direction >= k):
        s = direction
        j0 = i + 1 + wait
        if i <= busy or j0 + hold >= len(x):
            continue
        e = o[j0]
        st = (l[i] if s > 0 else h[i]) if stop == "low" else ((h[i] + l[i]) / 2 if stop == "mid" else e * (1 - s * stop_pct / 100))
        if s * (e - st) <= 0:
            continue
        px, how, m = None, "time", j0
        for m in range(j0, j0 + hold):
            if (s > 0 and l[m] <= st) or (s < 0 and h[m] >= st):
                px, how = st, "stop"
                break
        if px is None:
            px = c[j0 + hold - 1]
        out.append({"t": x.index[i], "r": (s * (px - e) - e * cost / 100) / abs(e - st), "pct": s * (px / e - 1) * 100 - cost,
                    "how": how, "stop_pct": abs(e - st) / e * 100})
        busy = m
    return pd.DataFrame(out)

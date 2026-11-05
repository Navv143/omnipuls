"""Crash-candle buy (paper): the strongest result of research/strategy_lab.py (the idea behind freqtrade's BinHV45).

A finished 5-minute candle whose close-to-close drop is at least Z x the standard deviation of 5-minute returns over
the previous 20 days → buy at the next candle's open, fixed target and stop, exit after 4 hours if neither is hit.
Long only (selling spikes lost money). At most 2 trades a day (New York day), one at a time.

Tested 2023-2026 (costs in): BTC Z=9, target 1.5%, stop 1.0%: +0.21R a trade (+0.16R at double costs), positive all
4 years, ~0.5 trades a week. Gold (PAXG, tracks spot gold 0.95) Z=4, target 0.4%, stop 0.4%: +0.12R, t 3.2, positive
all 4 years, ~3 a week. Candles: Crypto.com BTC_USDT / PAXG_USD (gold: weekdays only, as tested).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SETUPS = {
    "BTC": {"name": "BTC crash buy", "inst": "BTC_USDT", "z": 9.0, "tp": 1.5, "sl": 1.0, "cost": 0.05, "weekdays": False},
    "GOLD": {"name": "Gold crash buy", "inst": "PAXG_USD", "z": 4.0, "tp": 0.4, "sl": 0.4, "cost": 0.02, "weekdays": True},
    # burst momentum (research/burst_study.py): a giant UP candle (z >= 8) keeps running; enter one candle later, stop at
    # the burst candle's low, exit after 12 candles (1 hour). 2023-26: BTC +0.21% a trade, ETH +0.36%, SOL +0.61%,
    # positive in both halves for all three.
    "BTC_UP": {"name": "BTC burst momentum", "inst": "BTC_USDT", "kind": "burst", "z": 8.0, "hold": 12, "wait": 1, "cost": 0.05,
               "weekdays": False},
    "ETH_UP": {"name": "ETH burst momentum", "inst": "ETH_USDT", "kind": "burst", "z": 8.0, "hold": 12, "wait": 1, "cost": 0.05,
               "weekdays": False},
    "SOL_UP": {"name": "SOL burst momentum", "inst": "SOL_USDT", "kind": "burst", "z": 8.0, "hold": 12, "wait": 1, "cost": 0.06,
               "weekdays": False},
}
WINDOW = 288 * 20      # 20 days of 5-minute candles
MIN_HIST = 288 * 5
MAX_HOLD = 48          # 4 hours
MAX_PER_DAY = 2


def signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """df: 5-min candles, UTC naive index, finished candles only. Adds ret %, sigma (20-day, previous candles) and the
    crash flag."""
    x = df.copy()
    if cfg["weekdays"]:
        x = x[x.index.dayofweek < 5]
    x["ret"] = x["Close"].pct_change() * 100
    x["sd"] = x["ret"].rolling(WINDOW, min_periods=MIN_HIST).std().shift()
    x["crash"] = (x["ret"] >= cfg["z"] * x["sd"]) if cfg.get("kind") == "burst" else (x["ret"] <= -cfg["z"] * x["sd"])
    return x


def burst_trades(x: pd.DataFrame, cfg: dict, since: pd.Timestamp | None = None) -> list:
    """Burst momentum: entry at the open `wait` candles after the burst candle's next one, stop at the burst candle's
    low, exit at the close of the hold-th candle (or the stop). One position at a time."""
    o, h, l, c = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    out, busy = [], -1
    for i in np.flatnonzero(x["crash"].to_numpy()):
        if (since is not None and x.index[i] < since) or i <= busy:
            continue
        j0 = i + 1 + cfg["wait"]
        if j0 >= len(x):
            out.append({"signal_at": x.index[i], "status": "entry next candle", "ret": float(x["ret"].iloc[i]),
                        "sigma": float(x["sd"].iloc[i]), "ref": float(c[i])})
            break
        e, st = o[j0], l[i]
        if e <= st:
            continue
        res, m, px = "open", j0, None
        for m in range(j0, min(j0 + cfg["hold"], len(x))):
            if l[m] <= st:
                res, px = "stop", st
                break
        if px is None and j0 + cfg["hold"] - 1 < len(x):
            m = j0 + cfg["hold"] - 1
            res, px = "time", c[m]
        last = px if px is not None else c[-1]
        r = ((last - e) - (e * cfg["cost"] / 100 if px is not None else 0)) / (e - st)
        out.append({"signal_at": x.index[i], "entry_at": x.index[j0], "entry": round(float(e), 2), "sl": round(float(st), 2),
                    "tp": None, "ret": round(float(x["ret"].iloc[i]), 3), "sigma": round(float(x["sd"].iloc[i]), 4),
                    "status": res, "exit_at": (x.index[m] if px is not None else None),
                    "exit_px": (round(float(px), 2) if px is not None else None), "last": round(float(c[-1]), 2),
                    "r": round(float(r), 2), "pct": round(float((last / e - 1) * 100), 3)})
        busy = m if px is not None else len(x)
    return out


def trades(x: pd.DataFrame, cfg: dict, since: pd.Timestamp | None = None) -> list:
    """The paper trades from the crash flags (entry next open, stop / target / 4 hours; stop first if both in a
    candle; max 2 a New York day, one at a time). Open trades carry the latest price."""
    if cfg.get("kind") == "burst":
        return burst_trades(x, cfg, since)
    o, h, l, c = (x[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    ny = x.index.tz_localize("UTC").tz_convert("America/New_York")
    nyday = ny.normalize()
    flags = np.flatnonzero(x["crash"].to_numpy())
    out, busy, per = [], -1, {}
    for k in flags:
        if since is not None and x.index[k] < since:
            continue
        if k <= busy:
            continue
        d = nyday[k]
        if per.get(d, 0) >= MAX_PER_DAY:
            continue
        i = k + 1
        if i >= len(x):   # entry candle not finished yet: reported as a pending signal
            out.append({"signal_at": x.index[k], "status": "entry next candle", "ret": float(x["ret"].iloc[k]),
                        "sigma": float(x["sd"].iloc[k]), "ref": float(c[k])})
            break
        e = o[i]
        st, tp = e * (1 - cfg["sl"] / 100), e * (1 + cfg["tp"] / 100)
        res, j, px = "open", i, None
        for j in range(i, len(x)):
            if j - i >= MAX_HOLD:
                res, px = "time", o[j]
                break
            if l[j] <= st:
                res, px = "stop", st
                break
            if h[j] >= tp:
                res, px = "target", tp
                break
        last = px if px is not None else c[-1]
        r = ((last - e) - (e * cfg["cost"] / 100 if px is not None else 0)) / (e - st)
        out.append({"signal_at": x.index[k], "entry_at": x.index[i], "entry": round(float(e), 2), "sl": round(float(st), 2),
                    "tp": round(float(tp), 2), "ret": round(float(x["ret"].iloc[k]), 3), "sigma": round(float(x["sd"].iloc[k]), 4),
                    "status": res, "exit_at": (x.index[j] if px is not None else None), "exit_px": (round(float(px), 2) if px is not None else None),
                    "last": round(float(c[-1]), 2), "r": round(float(r), 2), "pct": round(float((last / e - 1) * 100), 3)})
        per[d] = per.get(d, 0) + 1
        busy = j if px is not None else len(x)
    return out

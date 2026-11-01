"""Trade odds: before a small fixed-target trade, how often does the target come before the stop?

Two answers, both from the market's own 5-minute bars over about the last 60 sessions:
  1. Replays: the rest of the trade is rebuilt 10,000 times. Each next candle is a real past candle from the same
     time of day (+/- 2 candles), scaled to the current price. Stop is checked before target inside a candle.
  2. History: the same trade (same side, target and stop in points, same entry time) taken on every past session,
     at that candle's open. Also shown for the "momentum" days only: the last 30 minutes already moved your way.
A trade with target T and stop S needs to win S / (T + S) of the decided trades just to break even, before costs.
This is a description of the recent past, not a forecast: news days and expiry days do things the pool may not hold.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import requests

# market: (default target pts, default cost per round trip, cost unit, India session?)
MARKETS = {"Nifty 50": (27.5, 2.0, "pts", True), "Bank Nifty": (47.5, 5.0, "pts", True),
           "F&O stock": (2.5, 0.06, "pct", True), "BTC": (450.0, 0.10, "pct", False),
           "ETH": (17.5, 0.10, "pct", False), "Gold": (9.0, 0.5, "pts", False)}  # gold: ~$0.5 spread + fees on XAUUSD
BINANCE = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "Gold": "PAXGUSDT"}  # PAXG: gold-backed token, tracks XAU
INDIA_FIRST, INDIA_LAST, INDIA_BARS = "09:15", "15:10", 75  # last candle used: 15:10 (out by 15:15)
WINDOW = 2


def binance_5m(symbol: str, days: int = 60) -> pd.DataFrame:
    """5-minute klines, UTC, from Binance's public market-data mirror (works where api.binance.com is blocked).
    The ~18 pages are fetched side by side."""
    from concurrent.futures import ThreadPoolExecutor
    now = int(time.time() * 1000)
    starts = list(range(now - days * 86400000, now, 1000 * 300000))
    err, rows = None, []
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        def page(st_, host=host):
            r = requests.get(f"{host}/api/v3/klines", timeout=20,
                             params={"symbol": symbol, "interval": "5m", "startTime": st_, "limit": 1000})
            r.raise_for_status()
            return r.json()
        try:
            with ThreadPoolExecutor(6) as ex:
                rows = [k for part in ex.map(page, starts) for k in part]
            break
        except Exception as e:  # try the next host
            err, rows = e, []
    if not rows:
        raise RuntimeError(f"Binance: {err}")
    df = pd.DataFrame([[float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in rows],
                      columns=["Open", "High", "Low", "Close", "Volume"],
                      index=pd.to_datetime([x[0] for x in rows], unit="ms"))
    return df[~df.index.duplicated()].sort_index()


def _slots(idx: pd.DatetimeIndex, india: bool) -> np.ndarray:
    m = idx.hour * 60 + idx.minute
    return ((m - (9 * 60 + 15)) // 5).to_numpy() if india else (m // 5).to_numpy()


def _ratios(bars: pd.DataFrame) -> np.ndarray:
    """Each candle's open, high, low, close over the previous candle's close."""
    pc = bars["Close"].shift(1).to_numpy(float)
    return np.column_stack([bars[c].to_numpy(float) / pc for c in ("Open", "High", "Low", "Close")])


def _plan_steps(start_slot: int, hold_bars: int | None, india: bool) -> list[int]:
    """The slots the trade lives through, from the entry candle on."""
    if india:
        end = INDIA_BARS - 1 if hold_bars is None else min(INDIA_BARS - 1, start_slot + hold_bars - 1)
        end = min(end, INDIA_BARS - 2)  # the 15:15 candle is not traded: out at the 15:10 close
        return list(range(start_slot, end + 1))
    return [(start_slot + k) % 288 for k in range(hold_bars or 12)]


def replays(bars: pd.DataFrame, side: int, entry: float, target: float, stop: float, start_slot: int,
            hold_bars: int | None, india: bool, today, n: int = 10000, seed: int = 19) -> dict:
    past = bars[bars.index.normalize() < pd.Timestamp(today)]
    R = _ratios(past)
    slot = _slots(past.index, india)
    day = past.index.normalize()
    first = np.r_[True, day[1:] != day[:-1]]
    ok = np.isfinite(R).all(1)
    if india:
        ok &= ~(first & (slot != 0))  # a day's first candle that is not 9:15: data gap
    if india:
        ok &= (slot >= 0) & (slot < INDIA_BARS)
    steps = _plan_steps(start_slot, hold_bars, india)
    if not steps:
        return {}
    pools = {}
    for j in set(steps):
        if india:
            near = (np.abs(slot - j) <= WINDOW) & ((slot != 0) | (j == 0))
        else:
            d = np.abs(slot - j)
            near = np.minimum(d, 288 - d) <= WINDOW
        pools[j] = R[ok & near]
    if any(len(p) < 20 for p in pools.values()):
        return {"error": "not enough past candles at this time of day"}
    rng = np.random.default_rng(seed)
    px = np.full(n, float(entry))
    res = np.zeros(n, int)  # 1 target, -1 stop, 0 still open
    tp, sl = entry + side * target, entry - side * stop
    for j in steps:
        p = pools[j][rng.integers(0, len(pools[j]), n)]
        hi, lo, cl = px * p[:, 1], px * p[:, 2], px * p[:, 3]
        live = res == 0
        if side > 0:
            s_hit, t_hit = lo <= sl, hi >= tp
        else:
            s_hit, t_hit = hi >= sl, lo <= tp
        res[live & s_hit] = -1
        res[live & ~s_hit & t_hit] = 1
        px = np.where(res == 0, cl, px)
    open_pts = side * (px - entry)
    return {"target": float((res == 1).mean()), "stop": float((res == -1).mean()), "open": float((res == 0).mean()),
            "open_avg_pts": float(open_pts[res == 0].mean()) if (res == 0).any() else 0.0,
            "steps": len(steps), "pool_days": int(day.nunique()), "seed": seed, "n": n}


def history(bars: pd.DataFrame, side: int, target: float, stop: float, start_slot: int, hold_bars: int | None,
            india: bool, today) -> pd.DataFrame:
    """The same trade on every past session at the same time of day, entered at that candle's open."""
    b = bars.copy()
    b["slot"], b["day"] = _slots(b.index, india), b.index.normalize()
    O, H, L, C = (b[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
    slots, days = b["slot"].to_numpy(), b["day"].to_numpy()
    starts = np.flatnonzero((slots == start_slot) & (days < np.datetime64(pd.Timestamp(today))))
    steps = len(_plan_steps(start_slot, hold_bars, india))
    rows = []
    for i in starts:
        e = O[i]
        tp, sl = e + side * target, e - side * stop
        out, how, last = None, "still open", i
        for k in range(i, min(i + steps, len(b))):
            if india and days[k] != days[i]:
                break
            last = k
            s_hit = L[k] <= sl if side > 0 else H[k] >= sl
            t_hit = H[k] >= tp if side > 0 else L[k] <= tp
            if s_hit:
                out, how = -stop, "stop"
                break
            if t_hit:
                out, how = target, "target"
                break
        if out is None:
            out = side * (C[last] - e)
        back = i - 6
        mom = np.nan
        if back >= 0 and (not india or days[back] == days[i]):
            mom = side * (C[i - 1] - C[back])
        elif india and i >= 1 and days[i - 1] == days[i]:
            day_open = O[np.flatnonzero(days == days[i])[0]]
            mom = side * (C[i - 1] - day_open)
        rows.append({"Date": pd.Timestamp(days[i]).date(), "Entry": round(e, 2), "Result": how,
                     "Points": round(out, 2), "Momentum day": bool(mom > 0) if np.isfinite(mom) else False,
                     "Minutes": (last - i + 1) * 5})
    return pd.DataFrame(rows).sort_values("Date", ascending=False) if rows else pd.DataFrame()


def summary(h: pd.DataFrame, cost: float) -> dict:
    if h.empty:
        return {}
    return {"trades": len(h), "target": float((h["Result"] == "target").mean()),
            "stop": float((h["Result"] == "stop").mean()), "open": float((h["Result"] == "still open").mean()),
            "avg_pts": float(h["Points"].mean() - cost)}


def break_even(target: float, stop: float, cost: float) -> float:
    """Share of decided trades (target or stop) that must win to make zero after cost."""
    return (stop + cost) / (target + stop)


def verdict(target_p: float, stop_p: float, need: float) -> str:
    decided = target_p + stop_p
    if decided < 0.05:
        return "Most replays hit neither side: the time limit decides this trade, not the target."
    got = target_p / decided
    gap = 100 * (got - need)
    if abs(gap) < 5:
        return f"Close to a coin flip: wins {100 * got:.0f}% of decided replays, needs {100 * need:.0f}%."
    lean = "target" if gap > 0 else "stop"
    word = "Strongly toward" if abs(gap) >= 15 else "Leans toward"
    return f"{word} the {lean}: wins {100 * got:.0f}% of decided replays, needs {100 * need:.0f}% to break even."

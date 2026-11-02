"""Twelve Data as the fallback for global prices when Yahoo fails (common on cloud servers).

Free Basic plan: 8 credits a minute, 800 a day (reset at midnight UTC), 1 credit per symbol per /time_series call.
About 50 of the app's symbols are covered (crypto, forex, INR pairs, gold, WTI). Indian prices come from Dhan.

How the budget is used:
- A background worker fetches the symbols pages asked for, at most 7 calls a minute. Pages never wait on it (only a
  few seconds on the very first load) and the rest fill in within minutes, whatever the page refresh rate.
- Symbols asked for in the last 30 minutes are kept fresh. How often each is refreshed stretches with the credits left
  today, so the 800 a day last until the reset instead of running out by late morning.
- Running out of credits for the day pauses calls until midnight UTC; older prices keep showing.
Key: Streamlit Secrets [twelvedata] api_key, or the TWELVEDATA_API_KEY environment variable.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

URL = "https://api.twelvedata.com/time_series"
TTL = 600            # shortest time a symbol's daily bars are reused
PER_MIN = 7          # stay under the free plan's 8 credits a minute
DAY_CREDITS = 760    # stay under the free plan's 800 a day (leaves room for chart loads)
ACTIVE_FOR = 1800    # symbols asked for within this many seconds are kept fresh
FIRST_WAIT = 4.0     # seconds the very first load of a page waits for its first prices
SPECIAL = {"XAUUSD=X": "XAU/USD", "GC=F": "XAU/USD", "CL=F": "WTI/USD", "BZ=F": None, "SI=F": None}
INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1day",
             "1wk": "1week", "1mo": "1month"}

_lock = threading.Lock()
_calls: deque = deque()       # times of calls in the last minute
_cache: dict = {}             # td symbol -> (time, DataFrame) daily bars
_charts: dict = {}            # (td symbol, interval) -> (time, DataFrame)
_wanted: dict = {}            # td symbol -> last time a page asked for it
_bad: dict = {}               # td symbol -> time until which it is skipped (not covered by the plan)
_state = {"key": "", "day": "", "used": 0, "out_until": 0.0, "worker": None}
_GEN = object()               # a module reload makes a new one; the old worker sees that and stops
STATUS = {"error": "", "calls": 0}


def td_symbol(yahoo: str) -> str | None:
    """Yahoo symbol -> Twelve Data symbol, or None when the free plan has no match."""
    if yahoo in SPECIAL:
        return SPECIAL[yahoo]
    m = re.fullmatch(r"([A-Z]{2,10}?)\d*-(USD|USDT|EUR|INR)", yahoo)  # Yahoo's numbered names: TON11419-USD -> TON
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"([A-Z]{3})([A-Z]{3})=X", yahoo)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"([A-Z]{3})=X", yahoo)  # Yahoo's USD-quoted shorthand, e.g. INR=X is USD/INR
    if m:
        return f"USD/{m.group(1)}"
    return None

# ---------------------------------------------------------------- credit budget (call with _lock held)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _roll_day():
    day = _utc_now().strftime("%Y-%m-%d")
    if _state["day"] != day:
        _state.update(day=day, used=0)


def _seconds_to_reset() -> float:
    now = _utc_now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (nxt - now).total_seconds())


def _take_credit() -> bool:
    """One call allowed now? Counts it if so."""
    now = time.time()
    _roll_day()
    if now < _state["out_until"] or _state["used"] >= DAY_CREDITS:
        return False
    while _calls and now - _calls[0] > 60:
        _calls.popleft()
    if len(_calls) >= PER_MIN:
        return False
    _calls.append(now)
    _state["used"] += 1
    return True


def _ttl(active: int) -> float:
    """How long daily bars are reused: stretched so the active symbols fit in today's remaining credits."""
    _roll_day()
    left = max(1, DAY_CREDITS - _state["used"])
    return max(TTL, active * _seconds_to_reset() / left)

# ---------------------------------------------------------------- transport


def _fetch(sym: str, key: str, interval: str = "1day", size: int = 260) -> pd.DataFrame | None:
    r = requests.get(URL, params={"symbol": sym, "interval": interval, "outputsize": size, "order": "asc",
                                  "timezone": "UTC"},
                     headers={"Authorization": f"apikey {key}"}, timeout=12)
    body = r.json() if r.content else {}
    STATUS["calls"] += 1
    if r.status_code != 200 or body.get("status") != "ok":
        msg = str(body.get("message") or r.status_code)
        STATUS["error"] = f"{sym}: {msg}"[:200]
        low = msg.lower()
        with _lock:
            if "for the day" in low or "daily" in low:
                _state["out_until"] = time.time() + _seconds_to_reset()  # wait for the reset at midnight UTC
            elif "credits" in low or "minute" in low or r.status_code == 429:
                _calls.extend([time.time()] * PER_MIN)  # per-minute limit: pause for a minute
            elif r.status_code in (400, 404) or "symbol" in low or "plan" in low:
                _bad[sym] = time.time() + 6 * 3600  # not on this plan: don't spend credits on it for 6 hours
        return None
    df = pd.DataFrame(body.get("values") or [])
    if df.empty:
        return None
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    out = pd.DataFrame({c.title(): pd.to_numeric(df[c], errors="coerce") for c in ("open", "high", "low", "close")})
    out["Volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0) if "volume" in df else 0.0
    return out.dropna(subset=["Close"])

# ---------------------------------------------------------------- background worker for daily bars


def _next_symbol() -> str | None:
    """Missing symbols first (most recently asked first), then the stalest one past its reuse time."""
    now = time.time()
    active = [s for s, t in _wanted.items() if now - t < ACTIVE_FOR and _bad.get(s, 0) < now]
    missing = sorted((s for s in active if s not in _cache), key=lambda s: -_wanted[s])
    if missing:
        return missing[0]
    ttl = _ttl(len(active))
    stale = [s for s in active if now - _cache[s][0] >= ttl]
    return min(stale, key=lambda s: _cache[s][0]) if stale else None


def _worker(gen):
    while _GEN is gen:
        with _lock:
            sym = _next_symbol()
            key = _state["key"]
            go = bool(sym and key) and _take_credit()
        if not go:
            time.sleep(1.0)
            continue
        try:
            df = _fetch(sym, key)
        except Exception as e:
            STATUS["error"] = f"{sym}: {e}"[:200]
            df = None
        with _lock:
            _state["failing"] = df is None  # first loads don't wait on Twelve Data while it isn't answering
            if df is not None:
                _cache[sym] = (time.time(), df)
            elif sym in _cache:
                _cache[sym] = (time.time() - TTL / 2, _cache[sym][1])  # failed: keep old bars, retry a bit later
            else:
                _bad.setdefault(sym, time.time() + 120)  # failed with nothing cached: try again in 2 minutes


def _ensure_worker():
    w = _state.get("worker")
    if w is None or not w.is_alive():
        w = threading.Thread(target=_worker, args=(_GEN,), daemon=True, name="twelve-data")
        _state["worker"] = w
        w.start()


def daily(symbols, key: str) -> dict:
    """{yahoo symbol: daily OHLCV} for the symbols Twelve Data covers. Returns what is already loaded; the worker
    loads and refreshes the rest within the free plan's limits."""
    if not key:
        return {}
    pairs = [(ys, td) for ys in symbols if (td := td_symbol(ys))]
    if not pairs:
        return {}
    now = time.time()
    with _lock:
        _state["key"] = key
        first = any(td not in _wanted for _, td in pairs)  # wait only the first time these are asked for
        for _, td in pairs:
            _wanted[td] = now
    _ensure_worker()
    deadline = now + (FIRST_WAIT if first else 0)
    while True:  # first load of a page: give the worker a moment for its first prices
        with _lock:
            out = {ys: _cache[td][1] for ys, td in pairs if td in _cache}
        if out or time.time() >= deadline or _state["out_until"] > time.time() or _state.get("failing"):
            return out
        time.sleep(0.2)


def history(yahoo: str, interval: str, key: str, bars: int = 1500) -> pd.DataFrame | None:
    """Candles for the chart page when Yahoo fails (1 credit per load; reused for a minute, or 10 minutes for
    daily and longer). Index is UTC without a time zone."""
    td, iv = td_symbol(yahoo), INTERVALS.get(interval)
    if not (key and td and iv):
        return None
    reuse = 60 if interval.endswith(("m", "h")) else TTL
    with _lock:
        hit = _charts.get((td, iv))
        if hit is not None and time.time() - hit[0] < reuse:
            return hit[1]
        if not _take_credit():
            return hit[1] if hit is not None else None
    try:
        df = _fetch(td, key, iv, min(bars, 5000))
    except Exception as e:
        STATUS["error"] = f"{td}: {e}"[:200]
        df = None
    if df is None:
        return hit[1] if hit is not None else None
    with _lock:
        _charts[(td, iv)] = (time.time(), df)
    return df


def usage() -> dict:
    """Credits used today and how many symbols are loaded, for the status line."""
    with _lock:
        _roll_day()
        now = time.time()
        active = [s for s, t in _wanted.items() if now - t < ACTIVE_FOR]
        return {"used": _state["used"], "limit": DAY_CREDITS, "loaded": sum(1 for s in active if s in _cache),
                "active": len(active), "paused": _state["out_until"] > now, "error": STATUS["error"]}

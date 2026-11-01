"""Twelve Data as the fallback for global prices when Yahoo fails (common on cloud servers).

Free Basic plan: 8 credits a minute, 800 a day, 1 credit per symbol per /time_series call. So: one symbol per call,
daily bars cached for 10 minutes, at most 7 calls in any 60 seconds (the rest wait for the next refresh), and only
markets the free plan covers (crypto, forex, gold, WTI). Indian prices come from Dhan, not from here.
Key: Streamlit Secrets [twelvedata] api_key, or the TWELVEDATA_API_KEY environment variable.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque

import pandas as pd
import requests

URL = "https://api.twelvedata.com/time_series"
TTL = 600          # seconds a symbol's daily bars are reused
PER_MIN = 7        # stay under the free plan's 8 credits a minute
SPECIAL = {"XAUUSD=X": "XAU/USD", "GC=F": "XAU/USD", "CL=F": "WTI/USD", "BZ=F": None, "SI=F": None}

_lock = threading.Lock()
_calls: deque = deque()
_cache: dict = {}   # td symbol -> (time, DataFrame)
STATUS = {"error": "", "calls": 0}


def td_symbol(yahoo: str) -> str | None:
    """Yahoo symbol -> Twelve Data symbol, or None when the free plan has no match."""
    if yahoo in SPECIAL:
        return SPECIAL[yahoo]
    m = re.fullmatch(r"([A-Z0-9]{2,10})-(USD|USDT|EUR|INR)", yahoo)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"([A-Z]{3})([A-Z]{3})=X", yahoo)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"([A-Z]{3})=X", yahoo)  # Yahoo's USD-quoted shorthand, e.g. INR=X is USD/INR
    if m:
        return f"USD/{m.group(1)}"
    return None


def _budget_ok() -> bool:
    now = time.time()
    while _calls and now - _calls[0] > 60:
        _calls.popleft()
    if len(_calls) >= PER_MIN:
        return False
    _calls.append(now)
    return True


def _fetch(sym: str, key: str) -> pd.DataFrame | None:
    r = requests.get(URL, params={"symbol": sym, "interval": "1day", "outputsize": 260, "order": "asc"},
                     headers={"Authorization": f"apikey {key}"}, timeout=12)
    body = r.json() if r.content else {}
    if r.status_code != 200 or body.get("status") != "ok":
        STATUS["error"] = f"{sym}: {body.get('message') or r.status_code}"
        return None
    df = pd.DataFrame(body.get("values") or [])
    if df.empty:
        return None
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    out = pd.DataFrame({c.title(): pd.to_numeric(df[c], errors="coerce") for c in ("open", "high", "low", "close")})
    out["Volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0) if "volume" in df else 0.0
    return out.dropna(subset=["Close"])


def daily(symbols, key: str) -> dict:
    """{yahoo symbol: daily OHLCV} for the symbols Twelve Data covers, within the free rate limit."""
    out = {}
    if not key:
        return out
    for ys in symbols:
        sym = td_symbol(ys)
        if not sym:
            continue
        with _lock:
            hit = _cache.get(sym)
            fresh = hit is not None and time.time() - hit[0] < TTL
            can = fresh or _budget_ok()
        if fresh:
            out[ys] = hit[1]
            continue
        if not can:
            if hit is not None:
                out[ys] = hit[1]  # older bars beat nothing; refreshed on a later run
            continue
        try:
            df = _fetch(sym, key)
            STATUS["calls"] += 1
        except Exception as e:
            STATUS["error"] = f"{sym}: {e}"
            df = None
        if df is not None:
            with _lock:
                _cache[sym] = (time.time(), df)
            out[ys] = df
        elif hit is not None:
            out[ys] = hit[1]
    return out

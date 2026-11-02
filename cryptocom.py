"""Crypto.com Exchange public market data: free crypto prices with no API key and no daily limit.

Used for crypto when Yahoo fails (common on cloud servers), before Twelve Data, so Twelve Data's 800 daily credits
are left for forex, INR pairs and gold. Daily and intraday candles (up to 300 per call) from
https://api.crypto.com/exchange/v1/public/. Coins are matched to the exchange's USD pair, else its USDT pair, from
the instrument list (fetched once a day); coins the exchange doesn't list are skipped.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

BASE = "https://api.crypto.com/exchange/v1/public/"
REUSE = {"1D": 60, "7D": 600, "1M": 600}  # seconds candles are reused (intraday: 30 s)
TIMEFRAMES = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1D", "1wk": "7D", "1mo": "1M"}
DOWN_FOR = 300   # after a network failure, skip the exchange for 5 minutes (pages never wait on it)
TIMEOUT = 8

_lock = threading.Lock()
_cache: dict = {}                      # (instrument, timeframe) -> (time, DataFrame)
_inst = {"names": set(), "at": 0.0}    # exchange instrument names, refreshed daily
STATUS = {"error": "", "down_until": 0.0, "calls": 0}


def coin_of(yahoo: str) -> str | None:
    """'BTC-USD' -> 'BTC'; Yahoo's numbered names ('TON11419-USD') -> 'TON'. None for non-crypto symbols."""
    m = re.fullmatch(r"([A-Z]{2,10}?)\d*-USD", str(yahoo))
    return m.group(1) if m else None


def _get(path: str, params: dict) -> dict:
    r = requests.get(BASE + path, params=params, timeout=TIMEOUT)
    STATUS["calls"] += 1
    body = r.json() if r.content else {}
    if r.status_code != 200 or body.get("code", 0) != 0:
        raise RuntimeError(f"{path}: {body.get('message') or r.status_code}")
    return body.get("result") or {}


def _instruments() -> set:
    with _lock:
        if _inst["names"] and time.time() - _inst["at"] < 86400:
            return _inst["names"]
    data = _get("get-instruments", {}).get("data") or []
    names = {str(d.get("symbol") or d.get("instrument_name") or "") for d in data} - {""}
    with _lock:
        _inst.update(names=names, at=time.time())
    return names


def instrument(yahoo: str) -> str | None:
    """The exchange's pair for a Yahoo crypto symbol: USD first, else USDT."""
    coin = coin_of(yahoo)
    if not coin:
        return None
    names = _instruments()
    for quote in ("USD", "USDT"):
        if f"{coin}_{quote}" in names:
            return f"{coin}_{quote}"
    return None


def _num(row: dict, *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return float(row[k])
    return float("nan")


def _parse(rows: list) -> pd.DataFrame:
    """Candles in either of the exchange's formats ({t, o, h, l, c, v} or {timestamp, open, ...}) -> OHLCV with a
    UTC index without a time zone, oldest first."""
    out = []
    for r in rows:
        t = r.get("t", r.get("timestamp"))
        ts = pd.to_datetime(t, unit="ms", utc=True) if isinstance(t, (int, float)) else pd.to_datetime(t, utc=True)
        out.append({"ts": ts.tz_localize(None), "Open": _num(r, "o", "open"), "High": _num(r, "h", "high"),
                    "Low": _num(r, "l", "low"), "Close": _num(r, "c", "close"), "Volume": _num(r, "v", "volume")})
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df["Volume"] = df["Volume"].fillna(0.0)
    return df.dropna(subset=["Close"])


def candles(yahoo: str, interval: str = "1d", count: int = 300) -> pd.DataFrame | None:
    """Candles for a Yahoo crypto symbol at a Yahoo interval ('1d', '5m', ...), or None (not listed, or the exchange
    is not answering)."""
    tf = TIMEFRAMES.get(interval)
    if not tf or time.time() < STATUS["down_until"]:
        return None
    try:
        inst = instrument(yahoo)
        if not inst:
            return None
        key = (inst, tf)
        with _lock:
            hit = _cache.get(key)
        if hit is not None and time.time() - hit[0] < REUSE.get(tf, 30):
            return hit[1]
        df = _parse(_get("get-candlestick", {"instrument_name": inst, "timeframe": tf, "count": min(count, 300)})
                    .get("data") or [])
        if df.empty:
            return hit[1] if hit is not None else None
        with _lock:
            _cache[key] = (time.time(), df)
        return df
    except requests.RequestException as e:
        STATUS.update(error=str(e)[:200], down_until=time.time() + DOWN_FOR)
    except Exception as e:
        STATUS["error"] = f"{yahoo}: {e}"[:200]
    return None


def daily(symbols) -> dict:
    """{yahoo symbol: daily OHLCV} for the crypto symbols the exchange lists, fetched in parallel."""
    syms = [s for s in symbols if coin_of(s)]
    if not syms or time.time() < STATUS["down_until"]:
        return {}
    try:
        _instruments()  # once, before the parallel calls (each would fetch the list itself)
    except requests.RequestException as e:
        STATUS.update(error=str(e)[:200], down_until=time.time() + DOWN_FOR)
        return {}
    except Exception as e:
        STATUS["error"] = str(e)[:200]
        return {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = dict(zip(syms, ex.map(lambda s: candles(s, "1d"), syms)))
    return {s: df for s, df in res.items() if df is not None and not df.empty}

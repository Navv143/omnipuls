"""Candles for every signal: one timeframe for the whole system (default 3 minutes), closed candles only.

- Dhan has no 3-minute candles, so 3-minute candles are built from 1-minute ones, anchored to 09:15 each session
  (09:15-09:18, 09:18-09:21, ...). Native intervals (1, 5, 15, 25, 60) are fetched directly.
- closed(): the candle still forming is dropped. Dhan returns the current candle while it builds: at 09:16 the 09:15
  candle holds only the pre-open price and a minute of trade, which read as "buying" in every gap-up stock. With
  closed() nothing can signal before the first candle of the day has closed (09:18 on 3 minutes).
- History for the time-of-day volume averages comes from the same 1-minute cache the nightly candle study fills
  (<bot>/cache_m1), topped up with the last days from Dhan.
Default is 3 minutes (since 7 Nov 2026). Set OMNI_TF=5 to go back to 5-minute candles everywhere.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
TF = int(os.environ.get("OMNI_TF", 3))   # 3-minute candles from 7 Nov 2026; OMNI_TF=5 to go back
NATIVE = (1, 5, 15, 25, 60)


def naive(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    d.index = idx
    return d[~d.index.duplicated(keep="last")].sort_index()


def resample(df: pd.DataFrame, tf: int = TF) -> pd.DataFrame:
    """1-minute (or finer) bars -> tf-minute bars anchored to 09:15 each day; OI = last value."""
    x = naive(df)
    if x.empty or tf == 1:
        return x
    x = x[(x.index.strftime("%H:%M") >= "09:15") & (x.index.strftime("%H:%M") <= "15:29")]
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    if "OI" in x:
        agg["OI"] = "last"
    parts = []
    for d0, g in x.groupby(x.index.normalize()):
        r = g.resample(f"{tf}min", origin=d0 + pd.Timedelta(hours=9, minutes=15), label="left", closed="left").agg(agg)
        parts.append(r.dropna(subset=["Close"]))
    return pd.concat(parts) if parts else x.iloc[:0]


def fetch(seg: str, sid: int, ins: str, days: int, cfg=None, tf: int = TF) -> pd.DataFrame:
    """Intraday bars on the system timeframe (naive IST index)."""
    import dhan as D
    if tf in NATIVE:
        return naive(D.intraday(seg, sid, ins, tf, days, cfg))
    return resample(D.intraday(seg, sid, ins, 1, days, cfg), tf)


def closed(df: pd.DataFrame | None, tf: int = TF, now: datetime | None = None) -> pd.DataFrame:
    """Only candles that have finished: start + tf minutes <= now (IST)."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    now = (now or datetime.now(IST)).replace(tzinfo=None)
    end = pd.DatetimeIndex(df.index) + pd.Timedelta(minutes=tf)
    return df[end <= pd.Timestamp(now)]


def history(sym: str, seg: str, sid: int, ins: str, days: int, cfg=None, tf: int = TF) -> pd.DataFrame:
    """`days` of tf-minute history from the 1-minute cache (<bot>/cache_m1, shared with candle_study.py), topped up
    from Dhan when the cache is missing or older than a few days."""
    if tf in NATIVE:
        return fetch(seg, sid, ins, days, cfg, tf)
    import bot as B
    import dhan as D
    cache = B.BOT_DIR / "cache_m1"
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{sym.replace('&', '_and_')}.parquet"
    try:
        old = naive(pd.read_parquet(f)) if f.exists() else pd.DataFrame()
    except Exception:
        old = pd.DataFrame()
    stale = old.empty or (pd.Timestamp.now() - old.index.max()).days >= 2 or \
        (pd.Timestamp.now() - old.index.min()).days < days - 3
    if stale:
        span = days if old.empty or (pd.Timestamp.now() - old.index.min()).days < days - 3 else 7
        try:
            new = naive(D.intraday(seg, sid, ins, 1, span, cfg))
        except Exception:
            new = pd.DataFrame()
        df = pd.concat([old, new]) if not old.empty and not new.empty else (new if old.empty else old)
        if not df.empty:
            df = df[~df.index.duplicated(keep="last")].sort_index()
            try:
                tmp = f.with_suffix(f".{os.getpid()}.tmp")
                df[[c for c in ("Open", "High", "Low", "Close", "Volume") if c in df]].astype("float32").to_parquet(tmp)
                os.replace(tmp, f)
            except Exception:
                pass
        old = df
        time.sleep(0.2)
    if old.empty:
        return old
    old = old[old.index >= pd.Timestamp.now().normalize() - pd.Timedelta(days=days)]
    return resample(old.astype("float64"), tf)

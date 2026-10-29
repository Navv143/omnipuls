"""Index position build-up in the style of TradeFinder's 'Option Apex': every 3 minutes, who is building bullish and
who is building bearish positions, from the change in open interest (not volume).

For each 3-minute bar, using Dhan 1-minute data for today:
  options  (the `strikes` strikes each side of the money, nearest expiry):
      bullish = puts written (put OI up) + calls closed (call OI down)
      bearish = calls written (call OI up) + puts closed (put OI down)
  futures  (near month): long build-up (price up, OI up) and short covering (price up, OI down) are bullish;
      short build-up (price down, OI up) and long unwinding (price down, OI down) are bearish.
Futures OI counts fully, option OI at half (an at-the-money option moves about half as much as the future).
Bars are in lots-equivalent units; only their relative size and colour matter.
"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

import dhan as D

INDICES = {"NIFTY": ("IDX_I", 13, "NIFTY"), "BANKNIFTY": ("IDX_I", 25, "BANKNIFTY"),
           "FINNIFTY": ("IDX_I", 27, "FINNIFTY")}


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df.index = idx
    return df[~df.index.duplicated(keep="last")].sort_index()


def _last_session(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    day = df.index.normalize().max()
    d = df[df.index.normalize() == day]
    return d.between_time("09:15", "15:29")


def _bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """1-minute bars -> `minutes` bars anchored at 9:15."""
    if df.empty:
        return df
    origin = df.index[0].normalize() + pd.Timedelta(minutes=555)
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    if "OI" in df:
        agg["OI"] = "last"
    return df.resample(f"{minutes}min", origin=origin, label="left", closed="left").agg(agg).dropna(subset=["Close"])


def buildup(index: str = "NIFTY", strikes: int = 5, minutes: int = 3, cfg=None) -> tuple[pd.DataFrame, dict]:
    """(bars, info). bars: Open/High/Low/Close of the index, bull, bear, net, cum and the option/futures parts."""
    seg, sid, fut_sym = INDICES[index]
    exps = D.expiries(sid, seg, cfg)
    live = [e for e in exps if str(e) >= str(date.today())] or exps
    expiry = live[0]
    spot, chain = D.option_chain(sid, seg, expiry, cfg)
    if chain.empty:
        raise D.DhanError("DH-907", "Empty option chain")
    chain = chain.assign(dist=(chain["Strike"] - spot).abs()).nsmallest(2 * strikes + 1, "dist").sort_values("Strike")
    px = _bars(_last_session(_naive(D.intraday(seg, sid, "INDEX", 1, 4, cfg))), minutes)
    if px.empty:
        raise D.DhanError("DH-907", "No index bars")
    ce_oi, pe_oi = [], []
    for _, r in chain.iterrows():
        for side, store in (("CE", ce_oi), ("PE", pe_oi)):
            oid = r.get(f"{side} ID")
            if pd.isna(oid):
                continue
            b = _bars(_last_session(_naive(D.intraday("NSE_FNO", int(oid), "OPTIDX", 1, 4, cfg))), minutes)
            if not b.empty and "OI" in b:
                store.append(b["OI"].rename(f"{side}{r['Strike']:g}"))
    fut = D.nearest_futures("NSE_FNO", "FUTIDX", [fut_sym], cfg).get(fut_sym)
    fb = _bars(_last_session(_naive(D.intraday("NSE_FNO", fut["id"], "FUTIDX", 1, 4, cfg)))
               if fut else pd.DataFrame(), minutes)

    def total(cols):
        if not cols:
            return pd.Series(0.0, index=px.index)
        return pd.concat(cols, axis=1).reindex(px.index).ffill().fillna(0).sum(axis=1)

    ce, pe = total(ce_oi), total(pe_oi)
    lot = float(fut["lot"]) if fut and fut.get("lot") else 1.0
    d_ce, d_pe = ce.diff().fillna(0) / lot, pe.diff().fillna(0) / lot
    out = px[["Open", "High", "Low", "Close"]].copy()
    out["opt_bull"] = 0.5 * (d_pe.clip(lower=0) + (-d_ce).clip(lower=0))
    out["opt_bear"] = 0.5 * (d_ce.clip(lower=0) + (-d_pe).clip(lower=0))
    out["fut_bull"] = out["fut_bear"] = 0.0
    if not fb.empty and "OI" in fb:
        f = fb.reindex(px.index).ffill()
        d_oi = f["OI"].diff().fillna(0) / lot
        d_px = f["Close"].diff().fillna(0)
        up, dn = d_px > 0, d_px < 0
        out["fut_bull"] = np.where(up, d_oi.abs(), 0.0)  # long build-up or short covering
        out["fut_bear"] = np.where(dn, d_oi.abs(), 0.0)  # short build-up or long unwinding
    out["bull"] = out["opt_bull"] + out["fut_bull"]
    out["bear"] = out["opt_bear"] + out["fut_bear"]
    out.iloc[0, out.columns.get_indexer(["opt_bull", "opt_bear", "fut_bull", "fut_bear", "bull", "bear"])] = 0.0
    out["net"] = out["bull"] - out["bear"]
    out["cum"] = out["net"].cumsum()
    info = {"index": index, "expiry": expiry, "spot": spot, "strikes": list(chain["Strike"]),
            "session": out.index[0].date(), "updated": datetime.now().strftime("%H:%M:%S")}
    return out, info


def dominance(bars: pd.DataFrame, until: str | None = None) -> tuple[float, str]:
    """Share of bullish build-up (0-100) up to a time, and a label."""
    b = bars if until is None else bars[bars.index.time < pd.Timestamp(until).time()]
    tot = b["bull"].sum() + b["bear"].sum()
    if tot <= 0:
        return np.nan, "No build-up yet"
    share = 100 * b["bull"].sum() / tot
    label = ("Bulls dominate" if share >= 65 else "Bears dominate" if share <= 35 else
             "Leaning bullish" if share > 55 else "Leaning bearish" if share < 45 else "Balanced")
    return share, label
